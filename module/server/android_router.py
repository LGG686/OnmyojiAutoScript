# This Python file uses the following encoding: utf-8
"""Android 原生面板的兼容层：把 `/android/*` 语义映射到 OAS 自己的进程与日志。

宿主 App 的主页状态卡、悬浮面板与日志板是按 AzurPilot 的薄接口写的，OAS 没有这些端点。这一层
只做转译，不引入新状态：配置名取自 `config/` 目录，`runner_alive` 取自脚本进程状态，日志取日志
服务的窗口；热更新与工具（tool）在 OAS 里没有对应概念，直接回 501 让面板隐藏这两块能力。

**边界（固定分法）**：这一层只回答宿主控制面的四个问题——进程活着没、启动、停止、日志尾。
业务数据（任务列表、调度、任务参数、实时日志流）一律走 OAS 原生端点（`/{script}/tasks`、
`/{script}/schedule`、`/{script}/{task}/args`、`/logs/{script}/stream`），**不要再往这里加**。
兼容层留在「宿主概念」上，OAS 上游升级不会与它冲突；把业务语义塞进来才会两边绑死。

The Android native panel compatibility layer maps the `/android/*` contract onto OAS's own
processes and logs. It only translates and introduces no new state: config names come from the
`config/` directory, `runner_alive` from the script process state, logs from the log service
window. Hot updates and tools have no OAS counterpart, so they answer 501 and the panels hide them.

**Boundary (a fixed split)**: this layer answers only the four host-control questions — is the
process alive, start, stop, tail the log. Business data (task list, schedule, task arguments, live
log stream) always goes through OAS's native endpoints (`/{script}/tasks`, `/{script}/schedule`,
`/{script}/{task}/args`, `/logs/{script}/stream`) and must **not** be added here. Keeping the layer
on host concepts means it never conflicts with upstream OAS; folding business semantics in is what
would couple both sides for good.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from module.logger import logger
from module.server.log_service import log_browser_service
from module.server.main_manager import mm
from module.server.script_process import ScriptState

android_app = APIRouter(prefix='/android', tags=['android'])

TEMPLATE_CONFIG = 'template'
MAX_LOG_TAIL = 2000
UNSUPPORTED = JSONResponse({'ok': False, 'error': 'not supported by OAS'}, status_code=501)


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
        'tool_alive': False,
        'tool_name': None,
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
    """启动调度进程，等价于 `/{script_name}/start`。"""
    name = _config_name(config)
    if not name:
        return JSONResponse({'ok': False, 'error': 'no config available'}, status_code=400)
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
async def android_update_status():
    """OAS 走 rootfs 整包更新，不做源码热更。

    `reason=unsupported` 让面板把「渠道没就绪」和「这类运行时永远不支持」区分开，
    后者不该提示用户去重启运行时。
    """
    return {'enabled': False, 'busy': False, 'phase': 'idle', 'reason': 'unsupported'}


@android_app.api_route('/update/apply', methods=['GET', 'POST'])
async def android_update_apply():
    return UNSUPPORTED


@android_app.api_route('/tool/start', methods=['GET', 'POST'])
@android_app.api_route('/tool/stop', methods=['GET', 'POST'])
async def android_tool_unsupported():
    """OAS 没有独立工具的概念。"""
    return UNSUPPORTED
