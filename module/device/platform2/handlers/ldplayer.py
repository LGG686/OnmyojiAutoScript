import os
import re
import typing as t

from module.device.platform2.handlers.base import EmulatorHandler


class LDPlayerHandler(EmulatorHandler):
    LDPlayer3 = 'LDPlayer3'
    LDPlayer4 = 'LDPlayer4'
    LDPlayer9 = 'LDPlayer9'

    @staticmethod
    def type_names() -> list[str]:
        return ['LDPlayer3', 'LDPlayer4', 'LDPlayer9']

    @staticmethod
    def path_to_type(path: str, exe: str, dir1: str, dir2: str) -> str:
        if exe == 'dnplayer.exe':
            if dir1 == 'ldplayer':
                return 'LDPlayer3'
            elif dir1 == 'ldplayer4':
                return 'LDPlayer4'
            elif dir1 == 'ldplayer9':
                return 'LDPlayer9'
            else:
                return 'LDPlayer3'
        return ''

    @staticmethod
    def multi_to_single(exe: str) -> list[str]:
        if 'dnmultiplayer.exe' in exe:
            return [exe.replace('dnmultiplayer.exe', 'dnplayer.exe')]
        return []

    @staticmethod
    def single_to_console(exe: str) -> t.Optional[str]:
        if 'dnplayer.exe' in exe:
            return exe.replace('dnplayer.exe', 'ldconsole.exe')
        if 'LDPlayer.exe' in exe:
            return exe.replace('LDPlayer.exe', 'ldconsole.exe')
        return None

    def get_instance_id(self, instance) -> t.Optional[int]:
        res = re.search(r'leidian(\d+)', instance.name)
        return int(res.group(1)) if res else None

    def iter_instances(self, emulator) -> t.Iterable:
        from module.device.platform2.emulator_windows import EmulatorInstance

        regex = re.compile(r'^leidian(\d+)$')
        for folder in emulator.list_folder('./vms', is_dir=True):
            folder_name = os.path.basename(folder)
            res = regex.match(folder_name)
            if not res:
                continue
            port = int(res.group(1)) * 2 + 5555
            yield EmulatorInstance(
                serial=f'127.0.0.1:{port}',
                name=folder_name,
                path=emulator.path,
            )

    def iter_adb_binaries(self, emulator) -> t.Iterable[str]:
        yield from self._iter_common_adb(emulator)

    def build_start_command(self, instance) -> t.Optional[str]:
        console = self.single_to_console(instance.emulator.path)
        ld_id = self.get_instance_id(instance)
        # ldconsole.exe launch --index 0
        return f'"{console}" launch --index {ld_id}'

    def build_stop_command(self, instance) -> t.Optional[str]:
        console = self.single_to_console(instance.emulator.path)
        ld_id = self.get_instance_id(instance)
        # ldconsole.exe quit --index 0
        return f'"{console}" quit --index {ld_id}'
