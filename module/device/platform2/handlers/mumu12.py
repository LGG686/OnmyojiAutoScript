import ctypes
import json
import os
import re
import typing as t

from module.device.platform2.handlers.base import EmulatorHandler
from module.logger import logger


class MuMu12Handler(EmulatorHandler):
    """MuMuPlayer12 的 Handler，逻辑最复杂，单独维护。"""
    MuMuPlayer12 = 'MuMuPlayer12'

    @staticmethod
    def type_names() -> list[str]:
        return ['MuMuPlayer12']

    @staticmethod
    def path_to_type(path: str, exe: str, dir1: str, dir2: str) -> str:
        if exe in ['mumuplayer.exe', 'mumunxmain.exe']:
            return 'MuMuPlayer12'
        return ''

    @staticmethod
    def multi_to_single(exe: str) -> list[str]:
        if 'MuMuMultiPlayer.exe' in exe:
            return [exe.replace('MuMuMultiPlayer.exe', 'MuMuPlayer.exe')]
        if 'MuMuManager.exe' in exe:
            return [exe.replace('MuMuManager.exe', 'MuMuPlayer.exe')]
        return []

    @staticmethod
    def single_to_console(exe: str) -> t.Optional[str]:
        if 'MuMuPlayer.exe' in exe:
            return exe.replace('MuMuPlayer.exe', 'MuMuManager.exe')
        if 'MuMuNxMain.exe' in exe:
            return exe.replace('MuMuNxMain.exe', 'MuMuManager.exe')
        return None

    def get_instance_id(self, instance) -> t.Optional[int]:
        res = re.search(r'MuMuPlayer(?:Global)?-12.0-(\d+)', instance.name)
        if res:
            return int(res.group(1))
        res = re.search(r'YXArkNights-12.0-(\d+)', instance.name)
        if res:
            return int(res.group(1))
        return None

    def iter_instances(self, emulator) -> t.Iterable:
        from module.device.platform2.emulator_windows import EmulatorInstance, Emulator
        from module.device.platform2.utils import iter_folder

        # vms/MuMuPlayer-12.0-0
        for folder in emulator.list_folder('../vms', is_dir=True):
            for file in iter_folder(folder, ext='.nemu'):
                serial = Emulator.vbox_file_to_serial(file)
                name = os.path.basename(folder)
                if serial:
                    yield EmulatorInstance(
                        serial=serial,
                        name=name,
                        path=emulator.path,
                    )
                else:
                    # Fix for MuMu12 v4.0.4
                    instance = EmulatorInstance(
                        serial=serial,
                        name=name,
                        path=emulator.path,
                    )
                    mumu_id = self.get_instance_id(instance)
                    if mumu_id is not None:
                        instance.serial = f'127.0.0.1:{16384 + 32 * mumu_id}'
                        yield instance

    def iter_adb_binaries(self, emulator) -> t.Iterable[str]:
        # MuMu12 特有: ../vmonitor/bin/adb_server.exe
        exe = emulator.abspath('../vmonitor/bin/adb_server.exe')
        if os.path.exists(exe):
            yield exe
        yield from self._iter_common_adb(emulator)

    def start_show_window(self) -> bool:
        # MuMu12 通过 MuMuManager 启动，命令本身不需要窗口
        return False

    def build_start_command(self, instance) -> t.Optional[str]:
        exe = instance.emulator.path
        mumu_id = self.get_instance_id(instance)
        if mumu_id is None:
            logger.warning(f'Cannot get MuMu instance index from name {instance.name}')
        console = self.single_to_console(exe)
        # MuMuManager.exe control -v 0 launch
        return f'"{console}" control -v {mumu_id} launch'

    def build_stop_command(self, instance) -> t.Optional[str]:
        exe = instance.emulator.path
        mumu_id = self.get_instance_id(instance)
        if mumu_id is None:
            logger.warning(f'Cannot get MuMu instance index from name {instance.name}')
        console = self.single_to_console(exe)
        # MuMuManager.exe control -v 1 shutdown
        return f'"{console}" control -v {mumu_id} shutdown'

    # ------------------------------------------------------------------
    # MuMu12 专属扩展
    # ------------------------------------------------------------------

    def build_launch_confirm_timer(self, instance):
        from module.base.timer import Timer
        return Timer(12).start()

    def query_player_info(self, instance, platform) -> dict:
        mumu_id = self.get_instance_id(instance)
        if mumu_id is None:
            return {}

        manager = self.single_to_console(instance.emulator.path)
        command = f'"{manager}" info -v {mumu_id}'
        try:
            result = platform.execute_output(command, timeout=10)
        except Exception as e:
            logger.warning(f'[emu-start] state query failed: serial={instance.serial}, error={e}')
            return {}

        output = '\n'.join(
            part.strip()
            for part in [result.stdout, result.stderr]
            if isinstance(part, str) and part.strip()
        )
        if not output:
            return {}

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            logger.warning(f'[emu-start] invalid info output: serial={instance.serial}, output={output}')
            return {}

    def try_hide_window(self, instance, platform, info=None) -> bool:
        mumu_id = self.get_instance_id(instance)
        if mumu_id is None:
            return False

        if info is None:
            info = self.query_player_info(instance, platform)
        if not info:
            return False

        hwnd = info.get('main_wnd')
        if isinstance(hwnd, str):
            try:
                hwnd = int(hwnd, 16)
            except ValueError:
                return False
        if not isinstance(hwnd, int) or hwnd <= 0:
            return False
        if not ctypes.windll.user32.IsWindow(hwnd):
            return False

        from module.device.platform2.platform_windows import hide_window
        hide_window(hwnd)
        return True

    def check_launch_state(self, instance, state) -> tuple:
        if state.launch_confirm is None:
            return 'ready', None

        player_info = self.query_player_info(instance, state._platform)
        current_state = 'unknown'
        if player_info:
            if not player_info.get('is_process_started', False):
                current_state = 'stopped'
            else:
                current_state = player_info.get('player_state') or (
                    'start_finished' if player_info.get('is_android_started', False) else 'starting'
                )
        if current_state == 'stopped':
            if state.launch_confirm.reached():
                logger.warning(f'[emu-start] launch not started: serial={state.serial}')
                return 'fail', player_info
            return 'wait', player_info

        state.launch_confirm = None
        return 'ready', player_info
