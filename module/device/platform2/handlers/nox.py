import os
import typing as t

from module.device.platform2.handlers.base import EmulatorHandler


class NoxHandler(EmulatorHandler):
    NoxPlayer = 'NoxPlayer'
    NoxPlayer64 = 'NoxPlayer64'

    @staticmethod
    def type_names() -> list[str]:
        return ['NoxPlayer', 'NoxPlayer64']

    @staticmethod
    def path_to_type(path: str, exe: str, dir1: str, dir2: str) -> str:
        if exe == 'nox.exe':
            if dir2 == 'nox':
                return 'NoxPlayer'
            elif dir2 == 'nox64':
                return 'NoxPlayer64'
            else:
                return 'NoxPlayer'
        return ''

    @staticmethod
    def multi_to_single(exe: str) -> list[str]:
        if 'MultiPlayerManager.exe' in exe:
            return [exe.replace('MultiPlayerManager.exe', 'Nox.exe')]
        return []

    @staticmethod
    def single_to_console(exe: str) -> t.Optional[str]:
        return None

    def iter_instances(self, emulator) -> t.Iterable:
        from module.device.platform2.emulator_windows import EmulatorInstance, Emulator
        from module.device.platform2.utils import iter_folder

        # ./BignoxVMS/{name}/{name}.vbox
        for folder in emulator.list_folder('./BignoxVMS', is_dir=True):
            for file in iter_folder(folder, ext='.vbox'):
                serial = Emulator.vbox_file_to_serial(file)
                if serial:
                    yield EmulatorInstance(
                        serial=serial,
                        name=os.path.basename(folder),
                        path=emulator.path,
                    )

    def iter_adb_binaries(self, emulator) -> t.Iterable[str]:
        exe = emulator.abspath('./nox_adb.exe')
        if os.path.exists(exe):
            yield exe
        yield from self._iter_common_adb(emulator)

    def build_start_command(self, instance) -> t.Optional[str]:
        exe = instance.emulator.path
        # Nox.exe -clone:Nox_1
        return f'"{exe}" -clone:{instance.name}'

    def build_stop_command(self, instance) -> t.Optional[str]:
        exe = instance.emulator.path
        # Nox.exe -clone:Nox_1 -quit
        return f'"{exe}" -clone:{instance.name} -quit'
