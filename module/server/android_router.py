# This Python file uses the following encoding: utf-8
"""Android 原生面板的兼容层：把 `/android/*` 语义映射到 OAS 自己的进程与日志。

宿主 App 的主页状态卡、悬浮面板与日志板是按 OAS Android 宿主的薄接口写的，OAS 没有这些端点。这一层
只做转译，不引入新状态：配置名取自 `config/` 目录，`runner_alive` 取自脚本进程状态，日志取日志
服务的窗口；热更转发给 `hot_update`（git fetch → reset 后重启），常驻工具（半自动点击）转给
`tool_process`，和调度进程互斥。

**边界（固定分法）**：这一层只回答宿主控制面的四个问题——进程活着没、启动、停止、日志尾，外加
宿主侧的源码更新。业务数据（任务列表、调度、任务参数、实时日志流）一律走 OAS 原生端点
（`/{script}/tasks`、`/{script}/schedule`、`/{script}/{task}/args`、`/logs/{script}/stream`），
**不要再往这里加**。兼容层留在「宿主概念」上，OAS 上游升级不会与它冲突；把业务语义塞进来才会
两边绑死。

The Android native panel compatibility layer maps the `/android/*` contract onto OAS's own
processes and logs. It only translates and introduces no new state: config names come from the
`config/` directory, `runner_alive` from the script process state, logs from the log service
window. Hot updates are forwarded to `hot_update`, which updates the source tree via Git and
restarts; long-running tools (semi-auto click) go through `tool_process` and are mutually
exclusive with the scheduler.

**Boundary (a fixed split)**: this layer answers only the four host-control questions — is the
process alive, start, stop, tail the log. Business data (task list, schedule, task arguments, live
log stream) always goes through OAS's native endpoints (`/{script}/tasks`, `/{script}/schedule`,
`/{script}/{task}/args`, `/logs/{script}/stream`) and must **not** be added here. Keeping the layer
on host concepts means it never conflicts with upstream OAS; folding business semantics in is what
would couple both sides for good.
"""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from module.logger import logger
from module.server import hot_update
from module.server.log_service import log_browser_service
from module.server.main_manager import mm
from module.server.script_process import ScriptState
from module.server.tool_process import tool_names, tool_process

android_app = APIRouter(prefix='/android', tags=['android'])

TEMPLATE_CONFIG = 'template'
MAX_LOG_TAIL = 2000


def _config_names() -> list[str]:
    """可用配置名；`template` 只是模板，不能当运行配置。"""
    return [name for name in mm.all_script_files() if name != TEMPLATE_CONFIG]


def _config_name(config: str) -> str:
    """解析请求里的配置名：已知就照用，否则优先回落正在运行的那份，再退到第一份。

    不传 config 时按「谁在跑」回落，宿主的状态卡才不会因为默认取到另一份没启动的配置
    而显示成空闲。With no config the running one wins, so the host's status card does not
    read idle just because the first config happens to be a different, stopped one.
    """
    names = _config_names()
    if config in names:
        return config
    running = [name for name in names if _is_alive(name)]
    if running:
        return running[0]
    return names[0] if names else ''


def _is_alive(name: str) -> bool:
    process = _runner(name)
    return process is not None and process.state != ScriptState.INACTIVE


def _runner(name: str):
    """取已注册的脚本进程；未访问过的配置还没有进程对象。"""
    if not name:
        return None
    return mm.script_process.get(name)


@android_app.get('/configs')
async def android_configs():
    """实例列表：面板靠它判定「服务是否活着」，并标出正在运行的那几份配置。"""
    names = _config_names()
    running = [name for name in names if _is_alive(name)]
    return {'configs': names, 'running': running}


@android_app.get('/status')
async def android_status(config: str = ''):
    """运行状态：调度进程是否在跑、当前实例、日志行数。"""
    name = _config_name(config)
    alive = _is_alive(name)
    log_lines = 0
    if name:
        try:
            window = log_browser_service.read_window(
                script_name=name, limit_lines=1, limit_bytes=4096)
            log_lines = int(((window.get('window') or {}).get('to') or {}).get('line_no') or 0)
        except Exception as error:  # 日志不可读不影响状态本身
            logger.warning(f'android status log window failed: {error}')
    return {
        'runner_alive': alive,
        'pid': getattr(getattr(_runner(name), '_process', None), 'pid', None) if alive else None,
        'config': name if alive else None,
        **tool_process.status(),
        'gui_alive': True,
        'log_lines': log_lines,
    }


@android_app.get('/logs')
async def android_logs(config: str = '', tail: int = 120):
    """日志尾部纯文本，一行一条。"""
    name = _config_name(config)
    if not name:
        return PlainTextResponse('')
    limit = max(1, min(int(tail), MAX_LOG_TAIL))
    try:
        window = log_browser_service.read_window(script_name=name, limit_lines=limit)
    except Exception as error:
        logger.warning(f'android logs failed: {error}')
        return PlainTextResponse('')
    lines = [str(line.get('text', '')) for line in window.get('lines', [])]
    return PlainTextResponse('\n'.join(lines))


@android_app.api_route('/start', methods=['GET', 'POST'])
async def android_start(config: str = ''):
    """启动调度进程，等价于 `/{script_name}/start`；先停掉工具（两者互斥）。"""
    name = _config_name(config)
    if not name:
        return JSONResponse({'ok': False, 'error': 'no config available'}, status_code=400)
    if tool_process.alive:
        await asyncio.to_thread(tool_process.stop)
    if name not in mm.script_process:
        mm.add_script_file(name)
    await mm.script_process[name].start()
    return {'ok': True}


@android_app.api_route('/stop', methods=['GET', 'POST'])
async def android_stop(config: str = ''):
    """停止调度进程；未启动时直接成功。"""
    process = _runner(_config_name(config))
    if process is not None:
        await process.stop()
    return {'ok': True}


@android_app.get('/update/status')
async def android_update_status(refresh: int = 0):
    """热更状态：本地/远端提交、是否有新版、当前阶段与失败原因。

    `refresh=1` 跳过 60 秒探测缓存；App 只在那颗「检查更新」按钮上这么用。
    """
    return await asyncio.to_thread(hot_update.status, bool(refresh))


@android_app.post('/update/config')
async def android_update_config(request: Request):
    """只保存更新源，不触发更新：设置页改完地址先存下来，再去检查。"""
    payload = {}
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse({'ok': False, 'error': 'invalid payload'}, status_code=400)
    try:
        keep = payload.get('keepLocalChanges')
        config = await asyncio.to_thread(
            hot_update.save_requested,
            str(payload.get('repo') or ''), str(payload.get('branch') or ''),
            None if keep is None else bool(keep))
    except ValueError as error:
        return JSONResponse({'ok': False, 'error': str(error)}, status_code=400)
    return {'ok': True, **config}


@android_app.api_route('/update/apply', methods=['GET', 'POST'])
async def android_update_apply(request: Request, repo: str = '', branch: str = ''):
    """拉取指定仓库分支覆盖源码并重启 WebUI。

    先停掉所有脚本进程：重启会连带杀掉它们，留着会被 SIGTERM 打断在任务中途。
    请求体可带 `{"repo": ..., "branch": ...}`，留空沿用上次保存的地址与分支。
    """
    if request.method == 'POST' and await request.body():
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            repo = str(payload.get('repo') or repo)
            branch = str(payload.get('branch') or branch)
    for name, process in list(mm.script_process.items()):
        try:
            await process.stop()
        except Exception as error:
            logger.warning(f'android update stop {name} failed: {error}')
    if tool_process.alive:
        await asyncio.to_thread(tool_process.stop)
    try:
        return await asyncio.to_thread(hot_update.apply, repo, branch)
    except ValueError as error:
        return JSONResponse({'ok': False, 'error': str(error)}, status_code=400)


@android_app.api_route('/tool/start', methods=['GET', 'POST'])
async def android_tool_start(name: str = '', config: str = ''):
    """启动常驻工具（半自动点击）。

    工具与调度进程互斥：先停下所有脚本进程，再拉工具。工具名未知直接 400，宿主据此
    把按钮置灰，而不是让人对着一个永远不动的画面等。
    """
    if name not in tool_names():
        return JSONResponse(
            {'ok': False, 'error': f'unknown tool: {name}', 'tools': tool_names()}, status_code=400)
    config_name = _config_name(config)
    if not config_name:
        return JSONResponse({'ok': False, 'error': 'no config available'}, status_code=400)
    for script_name, process in list(mm.script_process.items()):
        try:
            await process.stop()
        except Exception as error:
            logger.warning(f'android tool stop {script_name} failed: {error}')
    try:
        await asyncio.to_thread(tool_process.start, name, config_name)
    except ValueError as error:
        return JSONResponse({'ok': False, 'error': str(error)}, status_code=400)
    return {'ok': True, 'tools': tool_names()}


@android_app.api_route('/tool/stop', methods=['GET', 'POST'])
async def android_tool_stop():
    """停止常驻工具；没在跑时直接成功。"""
    await asyncio.to_thread(tool_process.stop)
    return {'ok': True}
