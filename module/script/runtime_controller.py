# This Python file uses the following encoding: utf-8

from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from module.device.device import Device
from module.device.platform2 import Platform
from module.logger import logger


class ScriptRuntimeOwner(Protocol):
    """
    运行时控制器依赖的最小调度器接口。
    """
    config: Any
    device: Device
    _emulator_down: bool
    __dict__: dict[str, Any]

    def wait_until(self, future: datetime) -> bool:
        """
        等待到指定时间，返回等待是否完整结束。
        """

    def run(self, command: str) -> bool:
        """
        执行指定任务命令。
        """


class ScriptRuntimeController:
    """
    负责调度器运行环境保障，包括空闲策略、模拟器预热与游戏状态修正。
    """

    def __init__(self, script: ScriptRuntimeOwner) -> None:
        """
        Args:
            script: 调度器对象，提供运行时所需的配置、设备与等待接口。
        """
        self.script = script

    @property
    def config(self):
        return self.script.config

    @property
    def device(self) -> Device:
        return self.script.device

    @property
    def emulator_down(self) -> bool:
        return self.script._emulator_down

    @emulator_down.setter
    def emulator_down(self, value: bool) -> None:
        self.script._emulator_down = value

    @staticmethod
    def _time_to_timedelta(value) -> timedelta:
        """
        将配置中的时间对象转换为 `timedelta`。

        Args:
            value: 配置中的时间对象，允许为 None。

        Returns:
            timedelta: 转换后的时间间隔；当 value 为 None 时返回 0。
        """
        if value is None:
            return timedelta(0)
        return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)

    def _build_platform_probe(self) -> Platform:
        """
        构造一个仅用于探测目标模拟器状态的平台对象。

        Returns:
            Platform: 已注入当前配置和目标 serial 的平台探测对象。
        """
        probe = Platform()
        probe.config = self.config
        probe.serial = str(self.config.script.device.serial)
        return probe

    def _sync_emulator_down_state_on_startup(self) -> None:
        """
        在脚本尚未初始化 `device` 时，同步一次模拟器真实状态。

        仅用于关闭模拟器相关策略，避免在“模拟器本来就关闭”的情况下，
        因为访问 `self.device` 而触发 `Device` 初始化，反而把模拟器先拉起来。
        """
        if self.emulator_down or 'device' in self.script.__dict__:
            return

        try:
            online = self._build_platform_probe().probe_target_instance_online()
        except Exception as e:
            logger.info(f'Probe target emulator failed: {e}')
            return

        if online is False:
            logger.info('Target emulator is already offline, keep waiting without starting it')
            self.emulator_down = True

    def _ensure_emulator_running(self, reason: str | None = None) -> None:
        """
        确保模拟器处于启动状态。

        Args:
            reason: 当需要拉起模拟器时输出到日志的原因说明。
        """
        if self.emulator_down:
            if reason:
                logger.info(reason)
            self.script.device = Device(self.config)
            self.emulator_down = False
            return

        _ = self.device

    def _run_restart_recovery(self, reason: str) -> bool:
        """
        通过 `Restart` 任务恢复游戏运行环境。

        Args:
            reason: 触发恢复的原因说明。

        Returns:
            bool: True 表示恢复成功；False 表示恢复失败。
        """
        logger.info(reason)
        if not self.script.run('Restart'):
            logger.warning('Restart task failed during runtime recovery')
            return False

        if not self.device.app_is_running():
            logger.warning('Game is still not running after Restart recovery')
            return False

        return True

    def _ensure_game_running(self, require_main: bool = False) -> bool:
        """
        确保模拟器和游戏都处于运行状态。

        Args:
            require_main: 是否要求额外回到游戏主界面。

        Returns:
            bool: True 表示状态已满足；False 表示恢复失败。
        """
        self._ensure_emulator_running('Wake emulator before ensuring game state')

        if not self.device.app_is_running():
            if not self._run_restart_recovery('Game is not running, recover it via Restart'):
                return False

        if require_main:
            logger.info('Ensure game stays at main page during wait')
            return self.script.run('GotoMain')

        return True

    def _ensure_game_closed(self) -> bool:
        """
        确保模拟器已启动，但游戏处于关闭状态。
        """
        self._ensure_emulator_running('Wake emulator before ensuring close_game state')
        if self.device.app_is_running():
            logger.info('Ensure game is closed during wait')
            self.device.app_stop()
            return True

        logger.info('Game is already closed during wait')
        return True

    def _prepare_idle_goto_main(self) -> bool:
        """
        将空闲状态调整为“模拟器开启、游戏运行且位于主界面”。
        """
        return self._ensure_game_running(require_main=True)

    def _prepare_idle_close_game(self) -> bool:
        """
        将空闲状态调整为“模拟器开启、游戏关闭”。
        """
        return self._ensure_game_closed()

    def _prepare_idle_keep_game_running(self) -> bool:
        """
        将空闲状态调整为“模拟器开启、游戏运行”。
        """
        return self._ensure_game_running(require_main=False)

    def prepare_task_execution(self, task: str) -> bool:
        """
        在任务真正执行前补齐运行环境。

        Args:
            task: 即将执行的任务名，使用调度器中的下划线命名。

        Returns:
            bool: True 表示运行环境已就绪；False 表示恢复失败，应中断当前轮次。
        """
        self._ensure_emulator_running('Wake emulator before running task')

        if task == 'Restart':
            return True

        if not self.device.app_is_running():
            return self._run_restart_recovery(f'Game is not running before task `{task}`, recover it via Restart')

        return True

    def _wait_until_with_emulator_preheat(
        self,
        next_run: datetime,
        on_wake: Callable[[], bool] | None = None
    ) -> bool:
        """
        在等待下个任务期间处理模拟器预热。

        Args:
            next_run: 下一个任务的计划运行时间。
            on_wake: 模拟器被提前拉起后需要立即执行的状态修正动作。

        Returns:
            bool: True 表示等待完成；False 表示等待期间配置发生变化，需要重新调度。
        """
        startup_lead = self._time_to_timedelta(self.config.script.optimization.emulator_startup_lead_time)

        while self.emulator_down:
            now = datetime.now()
            wake_time = next_run - startup_lead if startup_lead > timedelta(0) else next_run
            if wake_time > now:
                logger.info(f'Wait before wake emulator: {wake_time.strftime("%Y-%m-%d %H:%M:%S")}')
                if not self.script.wait_until(wake_time):
                    return False
                continue

            logger.info('Wake emulator before next task')
            self._ensure_emulator_running()
            if on_wake is not None:
                if not on_wake():
                    return False
            break

        if datetime.now() < next_run:
            return self.script.wait_until(next_run)
        return True

    def _should_close_game_during_wait(self, next_run: datetime) -> bool:
        """
        判断本次空闲等待是否需要关闭游戏。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            bool: True 表示本次等待前应关闭游戏；False 表示保持当前状态直接等待。
        """
        close_game_limit_time = self.config.script.optimization.close_game_limit_time
        close_game_limit = self._time_to_timedelta(close_game_limit_time)

        if close_game_limit <= timedelta(0):
            logger.info('Close game during wait immediately (close_game_limit_time <= 0)')
            return True

        if next_run > datetime.now() + close_game_limit:
            logger.info('Close game during wait (next task exceeds close_game_limit_time)')
            return True

        logger.info('Keep game running during short wait (next task within close_game_limit_time)')
        return False

    def _wait_close_game(self, next_run: datetime) -> bool:
        """
        按“关闭游戏”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            bool: True 表示等待完成；False 表示等待被配置刷新打断。
        """
        if self._should_close_game_during_wait(next_run):
            if not self._prepare_idle_close_game():
                return False
            self.device.release_during_wait()
            return self.script.wait_until(next_run)

        if not self._prepare_idle_keep_game_running():
            return False
        self.device.release_during_wait()
        return self.script.wait_until(next_run)

    def _wait_goto_main(self, next_run: datetime) -> bool:
        """
        按“前往主界面”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            bool: True 表示等待完成；False 表示等待被配置刷新打断。
        """
        if not self._prepare_idle_goto_main():
            return False
        self.device.release_during_wait()
        return self.script.wait_until(next_run)

    def _wait_close_emulator_or_goto_main(self, next_run: datetime) -> bool:
        """
        按“关闭模拟器&前往主界面”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            bool: True 表示等待完成；False 表示等待被配置刷新打断。
        """
        return self._wait_close_emulator_or(
            next_run,
            fallback_waiter=self._wait_goto_main,
            on_wake=self._prepare_idle_goto_main,
        )

    def _wait_close_emulator_or_close_game(self, next_run: datetime) -> bool:
        """
        按“关闭模拟器&关闭游戏”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            bool: True 表示等待完成；False 表示等待被配置刷新打断。
        """
        return self._wait_close_emulator_or(
            next_run,
            fallback_waiter=self._wait_close_game,
            on_wake=self._prepare_idle_close_game,
        )

    def _wait_close_emulator_or(
        self,
        next_run: datetime,
        fallback_waiter: Callable[[datetime], bool],
        on_wake: Callable[[], bool]
    ) -> bool:
        """
        处理带“关闭模拟器”语义的空闲等待策略。

        Args:
            next_run: 下一个任务的计划运行时间。
            fallback_waiter: 未达到关模拟器阈值时使用的等待策略。
            on_wake: 模拟器预热完成后需要恢复到的目标状态动作。

        Returns:
            bool: True 表示等待完成；False 表示等待被配置刷新打断。
        """
        self._sync_emulator_down_state_on_startup()

        close_emulator_limit_time = self.config.script.optimization.close_emulator_limit_time
        close_emulator_limit = self._time_to_timedelta(close_emulator_limit_time)

        if self.emulator_down:
            logger.info('Emulator is down, keep close_emulator strategy and wait with preheat')
            return self._wait_until_with_emulator_preheat(next_run, on_wake=on_wake)

        if close_emulator_limit > timedelta(0) and next_run > datetime.now() + close_emulator_limit:
            logger.info('Close emulator during wait')
            self.device.emulator_stop()
            self.emulator_down = True
            return self._wait_until_with_emulator_preheat(next_run, on_wake=on_wake)

        return fallback_waiter(next_run)

    def _wait_stay_there(self, next_run: datetime) -> bool:
        """
        按“保持现状”策略等待下个任务。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            bool: True 表示等待完成；False 表示等待被配置刷新打断。
        """
        if self.emulator_down:
            logger.info('Stay_there during wait (emulator is down, with preheat)')
            return self._wait_until_with_emulator_preheat(next_run)

        logger.info('Stay_there (no action) during wait')
        self.device.release_during_wait()
        return self.script.wait_until(next_run)

    def handle_wait_during_idle(self, next_run: datetime) -> bool:
        """
        处理任务空闲期间的行为策略。

        Args:
            next_run: 下一个任务的计划运行时间。

        Returns:
            bool: True 表示等待成功完成；False 表示等待被中断。
        """
        method = self.config.script.optimization.when_task_queue_empty
        strategy_map = {
            'close_game': self._wait_close_game,
            'goto_main': self._wait_goto_main,
            'close_emulator_or_goto_main': self._wait_close_emulator_or_goto_main,
            'close_emulator_or_close_game': self._wait_close_emulator_or_close_game,
        }
        func = strategy_map.get(method)
        if func is None:
            logger.warning(f'Invalid Optimization_WhenTaskQueueEmpty: {method}, fallback to stay_there')
            func = self._wait_stay_there
        return func(next_run)
