# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import asyncio
import json
from functools import lru_cache
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime
from module.config.utils import convert_to_underscore
from module.config.config_menu import ConfigMenu
from module.config.config_model import ConfigModel

from module.logger import logger
from module.server.api_logger import ApiLoggingRoute, log_ws_event
from module.server.config_manager import (
    ConfigAlreadyExistsError,
    ConfigJsonError,
    ConfigManager,
    ConfigNameError,
    ConfigNotFoundError,
    ConfigTaskError,
    ConfigValidationError,
)
from module.server.i18n import Addition
from module.server.main_manager import mm
from module.server.script_process import ScriptProcess, ScriptState

from tasks.Component.config_base import TimeDelta


script_app = APIRouter(route_class=ApiLoggingRoute)


@script_app.get('/test')
async def script_test():
    return 'success'

@script_app.get('/script_menu')
async def script_menu():
    return mm.config_cache('template').gui_menu_list
# ----------------------------------   配置文件管理   ----------------------------------
@script_app.get('/config_list')
async def config_list():
    return mm.all_script_files()

@script_app.post('/config_copy')
async def config_copy(file: str, template: str = 'template'):
    mm.copy(file, template)
    return mm.all_script_files()

@script_app.get('/config_new_name')
async def config_new_name():
    return mm.generate_script_name()

@script_app.get('/config_all')
async def config_all():
    return mm.all_json_file()


@script_app.post('/config/import')
async def config_import(name: str = Form(...), file: UploadFile = File(...)):
    """
    导入脚本配置文件，上传文件名不会作为落盘名称。
    """
    try:
        raw = await file.read()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as e:
            raise ConfigJsonError(f'Config file must be UTF-8 JSON: {e}') from e
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConfigJsonError(f'Config JSON parse failed: {e}') from e

        config_name = mm.import_config(name, data)
        mm.add_script_file(config_name)
        return {"name": config_name, "file": f"{config_name}.json"}
    except ConfigAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConfigValidationError as e:
        raise HTTPException(
            status_code=400,
            detail={"message": str(e), "fields": e.fields},
        )
    except (ConfigNameError, ConfigJsonError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@script_app.get('/config/export')
async def config_export(name: str):
    """
    导出脱敏后的脚本配置文件。
    """
    try:
        config_name, data = mm.load_config_for_export(name)
    except ConfigNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConfigJsonError as e:
        raise HTTPException(status_code=400, detail=str(e))

    redacted = ConfigManager.redact_config(data)
    content = json.dumps(redacted, indent=2, ensure_ascii=False, sort_keys=False, default=str)
    filename = f"{config_name}.json"
    quoted_filename = quote(filename, safe='')
    fallback_filename = "config.json"
    return Response(
        content=content,
        media_type='application/json; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"{fallback_filename}\"; filename*=UTF-8''{quoted_filename}",
            'Cache-Control': 'no-store',
        },
    )


@script_app.post('/config/task/import')
async def config_task_import(
    config_name: str = Form(...),
    task_name: str = Form(...),
    json_text: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    """
    导入单个任务配置 JSON，内容必须是 {"task_key": {...}}。
    """
    try:
        file_content = await file.read() if file is not None else None
        data = mm.parse_task_json_source(json_text=json_text, file_content=file_content)
        config_name, task_key = mm.import_task_config(config_name, task_name, data)
        return {
            "config_name": config_name,
            "task_name": task_key,
            "file": f"{config_name}.json",
            "updated": True,
        }
    except ConfigValidationError as e:
        raise HTTPException(
            status_code=400,
            detail={"message": str(e), "fields": e.fields},
        )
    except ConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConfigNameError, ConfigJsonError, ConfigTaskError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@script_app.get('/config/task/export')
async def config_task_export(config_name: str, task_name: str):
    """
    导出脱敏后的单个任务配置 JSON 文件。
    """
    try:
        config_name, task_key, data = mm.load_task_for_export(config_name, task_name)
    except ConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConfigNameError, ConfigJsonError, ConfigTaskError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    content = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str)
    filename = f"{config_name}-{task_key}.json"
    quoted_filename = quote(filename, safe='')
    fallback_filename = "task.json"
    return Response(
        content=content,
        media_type='application/json; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"{fallback_filename}\"; filename*=UTF-8''{quoted_filename}",
            'Cache-Control': 'no-store',
        },
    )


@script_app.get('/config/task/copy-json')
async def config_task_copy_json(config_name: str, task_name: str):
    """
    复制单个任务配置 JSON，返回未脱敏普通 JSON。
    """
    try:
        _, _, data = mm.load_task_for_transfer(config_name, task_name)
        return data
    except ConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConfigNameError, ConfigJsonError, ConfigTaskError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@script_app.put('/config')
async def config_rename(old_name: str = '', new_name: str = ''):
    """
    update config name
    :param old_name: old config name
    :param new_name: new config name
    :return: True or False
    """
    if old_name == new_name or new_name == '':
        return False
    if old_name in mm.script_process:
        if mm.script_process[old_name].state != ScriptState.INACTIVE:
            mm.script_process[old_name].stop()
        del mm.script_process[old_name]
    if not mm.rename(old_name, new_name):
        raise HTTPException(status_code=400, detail='Rename failed')
    return True


@script_app.delete('/config')
async def config_delete(name: str = ''):
    """
    delete config file
    :param name: config name
    :return: True or False
    """
    if name == '' or name == 'template':
        raise HTTPException(status_code=400, detail='Delete failed')
    if name in mm.script_process:
        if mm.script_process[name].state != ScriptState.INACTIVE:
            mm.script_process[name].stop()
        del mm.script_process[name]
    if not mm.delete(name):
        raise HTTPException(status_code=400, detail='Delete failed')
    return True


@script_app.put('/config/task/copy')
async def task_copy(task_name: str, dest_config_name: str, source_config_name: str):
    if dest_config_name not in mm.script_process or source_config_name not in mm.script_process:
        return False
    source_task = getattr(mm.config_cache(source_config_name).model, convert_to_underscore(task_name), None)
    if source_task is None:
        return False
    return mm.config_cache(dest_config_name).model.copy_script_task(task_name, source_task)


@script_app.put('/config/task/group/copy')
async def task_group_copy(task_name: str, group_name: str, dest_config_name: str, source_config_name: str):
    if dest_config_name not in mm.script_process or source_config_name not in mm.script_process:
        return False
    source_task = getattr(mm.config_cache(source_config_name).model, convert_to_underscore(task_name), None)
    if source_task is None:
        return False
    return mm.config_cache(dest_config_name).model.copy_task_group(task_name, group_name, source_task)


# ---------------------------------   脚本实例管理   ----------------------------------
@script_app.get('/{script_name}/start')
async def script_start(script_name: str):
    if script_name not in mm.script_process:
        mm.script_process[script_name] = ScriptProcess(script_name)
    # start() 是 async，漏掉 await 只会返回一个从未执行的协程，接口 200 但脚本不启动
    await mm.script_process[script_name].start()
    return

@script_app.get('/{script_name}/stop')
async def script_stop(script_name: str):
    if script_name not in mm.script_process:
        logger.warning(f'[{script_name}] script process does not exist')
        return
    # 同 start()：stop() 也是 async，漏掉 await 只会返回一个从未执行的协程
    await mm.script_process[script_name].stop()
    return

@script_app.get('/{script_name}/desktop/launch-status')
async def desktop_launch_status(script_name: str):
    from module.device.desktop_launch import desktop_launch_status as read_status
    return read_status(script_name)


@script_app.get('/{script_name}/{task}/args')
async def script_task(script_name: str, task: str):
    return mm.config_cache(script_name).model.script_task(task)


class TaskListChange(BaseModel):
    action: Literal['add', 'reorder', 'remove']
    type: str = ''
    id: str = ''
    ids: list[str] = Field(default_factory=list)
    preview: bool = False
    entries: list[dict] | None = None


@script_app.post('/{script_name}/{task}/list')
async def change_task_list(script_name: str, task: str, change: TaskListChange):
    from tasks.CustomTask.config import CustomTask

    model = mm.config_cache(script_name).model
    group = getattr(model, convert_to_underscore(task), None)
    if not isinstance(group, CustomTask):
        raise HTTPException(status_code=404, detail='Task list not found')
    try:
        if change.preview:
            group = CustomTask(entries=change.entries or [])
        match change.action:
            case 'add':
                group.add(change.type)
            case 'reorder':
                group.reorder(change.ids)
            case 'remove':
                group.remove(change.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not change.preview:
        model.save()
    return group.list_payload()


@script_app.post('/{script_name}/CustomTask/entry-args')
async def preview_custom_task_entry(script_name: str, entry: dict):
    from tasks.CustomTask.config import CustomTask, CustomTaskEntry, ENTRY_PREFIX
    try:
        candidate = CustomTaskEntry.model_validate(entry)
        group = CustomTask(entries=[candidate])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    model = mm.config_cache(script_name).model.model_copy(update={'custom_task': group}, deep=True)
    return model.script_task(ENTRY_PREFIX + candidate.id)


@script_app.put('/{script_name}/{task}/{group}/{argument}/value')
async def script_task(script_name: str, task: str, group: str, argument: str, types: str, value):
    try:
        match types:
            case 'task_list':
                value = json.loads(value)
            case 'multi_enum':
                from module.config.multi_select import normalize_multi_select
                value = normalize_multi_select(value)
            case 'integer':
                value = int(value)
            case 'number':
                value = float(value)
            case 'boolean':
                if isinstance(value, str):
                    logger.warning(f'[{script_name}] script argument {argument} value is string, try to convert to bool')
                    if value.lower() in ['true', '1']:
                        value = True
                    elif value.lower() in ['false', '0']:
                        value = False
                value = bool(value)
            case 'string':
                pass
            case 'date_time':
                value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            case 'time_delta':
                # strptime 是个好东西，但是不能解析00的天数
                day = int(value[1])
                date_time = datetime.strptime(value[3:], '%H:%M:%S')
                value = TimeDelta(days=day, hours=date_time.hour, minutes=date_time.minute, seconds=date_time.second)
            case 'time':
                value = datetime.strptime(value, '%H:%M:%S').time()
            case _: pass
    except Exception as e:
        # 类型不正确
        raise HTTPException(status_code=400, detail=f'Argument type error: {e}')
    return mm.config_cache(script_name).model.script_set_arg(task, group, argument, value)


@script_app.put('/{script_name}/{task}/sync_next_run')
async def sync_next_run(script_name: str, task: str, target_dt: str):
    if script_name not in mm.script_process:
        return False
    config = mm.config_cache(script_name)
    target = datetime.strptime(target_dt, '%Y-%m-%d %H:%M:%S') if target_dt else None
    config.task_delay(task=task, success=True, target=target)
    script_process = mm.script_process[script_name]
    config.get_next()
    await script_process.broadcast_state({"schedule": config.get_schedule_data()})
    return True


# --------------------------------------  调度  --------------------------------------
# 不在配置菜单里的任务归到这一类，避免新加的任务在面板上消失。
FALLBACK_MENU = 'Other'
FALLBACK_MENU_TITLE = {'en-US': 'Other', 'zh-CN': '其他'}


@lru_cache(maxsize=1)
def _translations() -> dict:
    """任务名与分类名的 zh-CN / en-US 词表。

    词表随 rootfs 出厂（assets/i18n），运行期不会变，进程内取一次就够；面板每几秒轮询一次，
    重复读盘不划算。
    """
    return Addition.load_additions()


def _panel_language(language: str | None) -> str:
    """请求语言归一：词表只有 en-US 与 zh-CN 两套。"""
    return 'zh-CN' if str(language or '').lower().startswith('zh') else 'en-US'


def _menu_positions() -> tuple[dict[str, tuple[str, int]], dict[str, int]]:
    """任务名 → (分类, 组内序号)，以及分类的先后顺序。

    菜单就是 OAS 桌面端左侧那份手写结构，面板沿用同一套分类，不另立一套。
    """
    menu = ConfigMenu().gui_menu_list
    positions: dict[str, tuple[str, int]] = {}
    order: dict[str, int] = {}
    for category_index, (category, tasks) in enumerate(menu.items()):
        order[category] = category_index
        if not isinstance(tasks, list):
            continue
        for task_index, task in enumerate(tasks):
            positions[task] = (category, task_index)
    return positions, order


def _task_rows(model, table: dict, language: str) -> list[dict]:
    """任务清单：命令行、本地化名称、所属分类与调度开关，顺序沿用配置字段顺序。

    只有带 scheduler 组的任务才参与调度，script/optimization 这类配置组跳过。
    """
    positions, order = _menu_positions()
    dumped = model.model_dump()
    rows = []
    for key in model.model_fields:
        data = dumped.get(key)
        if not isinstance(data, dict) or not isinstance(data.get('scheduler'), dict):
            continue
        scheduler = data['scheduler']
        command = ConfigModel.type(key)
        category, task_order = positions.get(command, (FALLBACK_MENU, 0))
        rows.append({
            'group': key,
            'command': command,
            'name': table.get(command, command),
            'menu': category,
            'menu_title': table.get(category) or (
                FALLBACK_MENU_TITLE[language] if category == FALLBACK_MENU else category),
            'menu_order': order.get(category, len(order)),
            'task_order': task_order,
            'enable': bool(scheduler.get('enable', False)),
            'next_run': str(scheduler.get('next_run', '')),
            'priority': int(scheduler.get('priority', 5)),
        })
    return rows


@script_app.get('/{script_name}/tasks')
async def script_tasks(script_name: str, language: str = 'zh-CN'):
    """任务清单与调度开关；`language` 决定 `name` / `menu_title` 用哪套词表。"""
    lang = _panel_language(language)
    return _task_rows(mm.config_cache(script_name).model, _translations().get(lang, {}), lang)


@script_app.get('/{script_name}/panel')
async def script_panel(script_name: str, language: str = 'zh-CN'):
    """调度面板：分类后的任务清单与调度运行态，一次请求取全。

    面板每几秒轮询一次，而 config_cache 每次都重新读配置并校验；把清单和运行态合成一个响应，
    只加载一次配置，也少一次请求往返。
    """
    lang = _panel_language(language)
    table = _translations().get(lang, {})
    config = mm.config_cache(script_name)
    rows = _task_rows(config.model, table, lang)
    config.update_scheduler()
    process = mm.script_process.get(script_name)
    state = int(process.state) if process is not None else 0

    menus: dict[str, dict] = {}
    for row in rows:
        menu = menus.get(row['menu'])
        if menu is None:
            menu = menus[row['menu']] = {
                'key': row['menu'],
                'title': row['menu_title'],
                'order': row['menu_order'],
                'tasks': [],
            }
        menu['tasks'].append({
            key: value for key, value in row.items()
            if key not in ('menu', 'menu_title', 'menu_order')
        })

    # 进程没起来时没有「正在执行」，整条 pending 都是待运行
    pending = config.pending_task
    running = None
    if state and pending:
        running = {'name': pending[0].command, 'next_run': str(pending[0].next_run)}
        pending = pending[1:]
    return {
        'language': lang,
        'state': state,
        'schedule': {
            'running': running,
            'pending': [{'name': f.command, 'next_run': str(f.next_run)} for f in pending],
            'waiting': [{'name': f.command, 'next_run': str(f.next_run)} for f in config.waiting_task],
        },
        'menus': sorted(menus.values(), key=lambda item: item['order']),
        'settings': _settings_entries(table),
    }


def _settings_entries(table: dict) -> list[dict]:
    """脚本级配置（脚本 / 全局配置 / 重启）：它们不参与调度，但同样能按任务参数读写。

    菜单里的 `Script` 分类就是这三项，面板把入口直接给出去，省得另立一份清单。
    """
    entries = ConfigMenu().gui_menu_list.get('Script') or []
    return [{'command': task, 'name': table.get(task, task)} for task in entries]


@script_app.get('/{script_name}/schedule')
async def script_schedule(script_name: str):
    """调度运行态：脚本进程状态与当前/待运行/等待中队列。

    config_cache 是请求级实例，update_scheduler 只刷新本次推导，不影响正在运行的脚本进程。
    """
    config = mm.config_cache(script_name)
    config.update_scheduler()
    process = mm.script_process.get(script_name)
    return {
        'state': int(process.state) if process is not None else 0,
        'schedule': config.get_schedule_data(),
    }


# --------------------------------------  SSE  --------------------------------------
@script_app.get('/{script_name}/state')
async def script_task_state(script_name: str):
    async def state_generate_events():
        while True:
            # 生成 SSE 事件数据
            event_data = "data: Hello, SSE!\n\n"
            yield event_data

            # 模拟异步操作，可以替换为您的实际处理逻辑
            await asyncio.sleep(1)

    response = StreamingResponse(state_generate_events(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response

@script_app.get('/{script_name}/log')
async def script_task_log(script_name: str):
    async def log_generate_events():
        while True:
            # 生成 SSE 事件数据
            event_data = "data: log\n"
            yield event_data

            # 模拟异步操作，可以替换为您的实际处理逻辑
            await asyncio.sleep(1)

    response = StreamingResponse(log_generate_events(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response

# -------------------------------------- websocket --------------------------------------

@script_app.websocket("/ws/{script_name}")
async def websocket_endpoint(websocket: WebSocket, script_name: str):
    if script_name not in mm.script_process:
        mm.script_process[script_name] = ScriptProcess(script_name)
    script_process = mm.script_process[script_name]
    await script_process.connect(websocket)
    log_ws_event(f"ws[{script_name}] connected")

    try:
        await script_process.send_json(websocket, {"state": script_process.state})
        log_ws_event(f"ws[{script_name}] connect state: {script_process.state}")
        config = mm.config_cache(script_name)
        config.get_next()
        schedule_data = config.get_schedule_data()
        await script_process.send_json(websocket, {"schedule": schedule_data})
        log_ws_event(f"ws[{script_name}] connect response: {schedule_data}")
        while True:
            # 初次进入，广播state schedule
            data = await websocket.receive_text()
            log_ws_event(f"ws[{script_name}] msg: {data}")
            if data == 'get_state':
                await script_process.broadcast_state({"state": script_process.state})
                log_ws_event(f"ws[{script_name}] response: {script_process.state}")
            elif data == 'get_schedule':
                config = mm.config_cache(script_name)
                config.get_next()
                schedule_data = config.get_schedule_data()
                await script_process.broadcast_state({"schedule": schedule_data})
                log_ws_event(f"ws[{script_name}] response: {schedule_data}")
            elif data == 'start':
                await script_process.start()
            elif data == 'stop':
                await script_process.stop()

    except WebSocketDisconnect:
        log_ws_event(f"ws[{script_name}] disconnect", level="warning")
        await script_process.disconnect(websocket)
    except Exception as e:
        log_ws_event(f"ws[{script_name}] error: {type(e).__name__}: {e}", level="error")
        logger.exception(f'[{script_name}] websocket error: {e}')
        await script_process.disconnect(websocket)
