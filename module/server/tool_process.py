# This Python file uses the following encoding: utf-8
"""常驻工具进程：半自动点击这类「停之前一直跑」的工具的进程壳。

和 `script_process` 的分工：脚本进程按配置跑调度、有状态队列与 websocket 广播；工具
只有一个、没有任务调度，日志仍写同一份 `log/YYYY-MM-DD_<config>.txt`（工具与调度互斥，
不会并发写同一文件），所以宿主的日志页不需要为工具另开通道。工具名到入口类的映射写
在 `_TOOLS`，新增工具只加一行。

Long-running tool processes: a process shell for tools that keep running until the user
stops them. Unlike `script_process`, there is only one tool, it has no scheduling, and
its log still goes to the same per-config file, so the host log page needs no extra channel.
"""
import importlib
import multiprocessing

from module.logger import logger

# 工具进程同样要用全新解释器，避免继承主服务已连接的 ZeroRPC/ZeroMQ context。
# Tool processes also need a fresh interpreter; inheriting the server's ZeroRPC context breaks it.
_TOOL_CONTEXT = multiprocessing.get_context('spawn')

# 工具名 → (模块, 入口类)。入口类接收 (config, device) 并实现 run()。
# Tool name -> (module, entry class). The entry class takes (config, device) and runs run().
_TOOLS = {
    'semi_auto': ('tasks.SemiAuto.script_task', 'SemiAuto'),
}


def tool_names() -> list[str]:
    """宿主可用的工具名。"""
    return sorted(_TOOLS)


def _tool_entry(module_name: str, class_name: str, config_name: str) -> None:
    """工具进程入口：日志落到配置同名文件，再构造 Config/Device 跑工具的 run()。"""
    try:
        from module.logger import set_file_logger
        set_file_logger(name=config_name)
    except Exception as error:
        logger.exception(f'Tool log init failed: {error}')

    from module.config.config import Config
    from module.device.device import Device

    logger.hr(f'Tool start: {class_name}', 0)
    config = Config(config_name=config_name)
    device = Device(config=config)
    tool_class = getattr(importlib.import_module(module_name), class_name)
    tool_class(config, device).run()


class ToolProcess:
    """进程壳：同一时刻只允许一个工具，start/stop 与状态查询都很薄。"""

    def __init__(self) -> None:
        self.name: str | None = None
        self.config_name: str | None = None
        self._process = None

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def status(self) -> dict:
        """宿主 `/android/status` 用：工具是否活着、在跑哪个、跟哪份配置。"""
        alive = self.alive
        return {
            'tool_alive': alive,
            'tool_name': self.name if alive else None,
            'tool_config': self.config_name if alive else None,
        }

    def start(self, name: str, config_name: str) -> None:
        """启动工具；同名工具已在跑时先收掉再起新的（配置可能换了）。"""
        if name not in _TOOLS:
            raise ValueError(f'unknown tool: {name}')
        if self.alive:
            logger.warning(f'Tool {self.name} is already running, stopping it first')
            self.stop()
        module_name, class_name = _TOOLS[name]
        self._process = _TOOL_CONTEXT.Process(
            target=_tool_entry,
            args=(module_name, class_name, config_name),
            name=f'tool-{name}',
            daemon=True,
        )
        self._process.start()
        self.name = name
        self.config_name = config_name
        logger.info(f'Tool {name} started with config {config_name} (pid={self._process.pid})')

    def stop(self) -> None:
        """停止工具；先 SIGTERM，进程不退出再强杀，避免设备侧留下的截图连接。"""
        process = self._process
        self._process = None
        self.name = None
        self.config_name = None
        if process is None:
            return
        if not process.is_alive():
            logger.warning('Tool process is not running')
            return
        process.terminate()
        process.join(timeout=3)
        if process.is_alive():
            logger.warning('Tool process ignored SIGTERM, killing it')
            process.kill()
            process.join(timeout=2)
        logger.info('Tool process stopped')


# 单例：工具是全局互斥的，宿主不需要按配置区分。
# Singleton: tools are globally exclusive; the host does not pick per config.
tool_process = ToolProcess()
