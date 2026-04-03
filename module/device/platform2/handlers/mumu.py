import os
import re
import typing as t

from module.device.platform2.handlers.base import EmulatorHandler


class MuMuHandler(EmulatorHandler):
    """MuMuPlayer (MuMu6) 和 MuMuPlayerX (MuMu9) 的 Handler。"""
    MuMuPlayer = 'MuMuPlayer'
    MuMuPlayerX = 'MuMuPlayerX'

    @staticmethod
    def type_names() -> list[str]:
        return ['MuMuPlayer', 'MuMuPlayerX']

    @staticmethod
    def path_to_type(path: str, exe: str, dir1: str, dir2: str) -> str:
        if exe == 'nemuplayer.exe':
            if dir2 == 'nemu':
                return 'MuMuPlayer'
            elif dir2 == 'nemu9':
                return 'MuMuPlayerX'
            else:
                return 'MuMuPlayer'
        return ''

    @staticmethod
    def multi_to_single(exe: str) -> list[str]:
        if 'NemuMultiPlayer.exe' in exe:
            return [exe.replace('NemuMultiPlayer.exe', 'NemuPlayer.exe')]
        return []

    @staticmethod
    def single_to_console(exe: str) -> t.Optional[str]:
        return None

    def iter_instances(self, emulator) -> t.Iterable:
        from module.device.platform2.emulator_windows import EmulatorInstance, Emulator
        from module.device.platform2.utils import iter_folder

        if emulator.type == self.MuMuPlayer:
            # MuMu6 无多实例，固定 7555
            yield EmulatorInstance(
                serial='127.0.0.1:7555',
                name='',
                path=emulator.path,
            )
        elif emulator.type == self.MuMuPlayerX:
            # vms/nemu-12.0-x64-default
            for folder in emulator.list_folder('../vms', is_dir=True):
                for file in iter_folder(folder, ext='.nemu'):
                    serial = Emulator.vbox_file_to_serial(file)
                    if serial:
                        yield EmulatorInstance(
                            serial=serial,
                            name=os.path.basename(folder),
                            path=emulator.path,
                        )

    def iter_adb_binaries(self, emulator) -> t.Iterable[str]:
        # MuMu 特有: ../vmonitor/bin/adb_server.exe
        exe = emulator.abspath('../vmonitor/bin/adb_server.exe')
        if os.path.exists(exe):
            yield exe
        yield from self._iter_common_adb(emulator)

    def build_start_command(self, instance) -> t.Optional[str]:
        exe = instance.emulator.path
        if instance.type == self.MuMuPlayer:
            # NemuPlayer.exe
            return f'"{exe}"'
        elif instance.type == self.MuMuPlayerX:
            # NemuPlayer.exe -m nemu-12.0-x64-default
            return f'"{exe}" -m {instance.name}'
        return None

    def stop_by_kill(self, instance) -> t.Optional[str]:
        if instance.type == self.MuMuPlayer:
            return (
                rf'('
                rf'NemuHeadless.exe'
                rf'|NemuPlayer.exe\"'
                rf'|NemuPlayer.exe$'
                rf'|NemuService.exe'
                rf'|NemuSVC.exe'
                rf')'
            )
        elif instance.type == self.MuMuPlayerX:
            return (
                rf'('
                rf'NemuPlayer.exe.*-m {instance.name}'
                rf'|Muvm6Headless.exe'
                rf'|Muvm6SVC.exe'
                rf')'
            )
        return None
