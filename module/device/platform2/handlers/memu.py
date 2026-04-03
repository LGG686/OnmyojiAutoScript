import os
import typing as t

from module.device.platform2.handlers.base import EmulatorHandler


class MEmuHandler(EmulatorHandler):
    MEmuPlayer = 'MEmuPlayer'

    @staticmethod
    def type_names() -> list[str]:
        return ['MEmuPlayer']

    @staticmethod
    def path_to_type(path: str, exe: str, dir1: str, dir2: str) -> str:
        if exe == 'memu.exe':
            return 'MEmuPlayer'
        return ''

    @staticmethod
    def multi_to_single(exe: str) -> list[str]:
        if 'MEmuConsole.exe' in exe:
            return [exe.replace('MEmuConsole.exe', 'MEmu.exe')]
        return []

    @staticmethod
    def single_to_console(exe: str) -> t.Optional[str]:
        if 'MEmu.exe' in exe:
            return exe.replace('MEmu.exe', 'memuc.exe')
        return None

    def iter_instances(self, emulator) -> t.Iterable:
        from module.device.platform2.emulator_windows import EmulatorInstance, Emulator
        from module.device.platform2.utils import iter_folder

        # ./MemuHyperv VMs/{name}/{name}.memu
        for folder in emulator.list_folder('./MemuHyperv VMs', is_dir=True):
            for file in iter_folder(folder, ext='.memu'):
                serial = Emulator.vbox_file_to_serial(file)
                if serial:
                    yield EmulatorInstance(
                        serial=serial,
                        name=os.path.basename(folder),
                        path=emulator.path,
                    )

    def iter_adb_binaries(self, emulator) -> t.Iterable[str]:
        yield from self._iter_common_adb(emulator)

    def build_start_command(self, instance) -> t.Optional[str]:
        exe = instance.emulator.path
        # MEmu.exe MEmu_0
        return f'"{exe}" {instance.name}'

    def build_stop_command(self, instance) -> t.Optional[str]:
        exe = instance.emulator.path
        console = self.single_to_console(exe)
        # memuc.exe stop -n MEmu_0
        return f'"{console}" stop -n {instance.name}'
