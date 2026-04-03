# Handlers 模块使用说明

## 概述

`handlers/` 模块采用**策略模式**管理不同模拟器的行为。每种模拟器（家族）对应一个 Handler 类，聚合了该模拟器的类型识别、实例枚举、启动/停止命令等全部逻辑。

新增模拟器支持只需：**创建一个 Handler 文件 → 注册到 `__init__.py`**。

## 目录结构

```
handlers/
├── __init__.py        # 注册表 + get_handler() / all_handlers()
├── base.py            # EmulatorHandler 抽象基类
├── nox.py             # NoxPlayer / NoxPlayer64
├── bluestacks.py      # BlueStacks4 / BlueStacks5
├── ldplayer.py        # LDPlayer3 / LDPlayer4 / LDPlayer9
├── mumu.py            # MuMuPlayer (MuMu6) / MuMuPlayerX (MuMu9)
├── mumu12.py          # MuMuPlayer12
└── memu.py            # MEmuPlayer
```

## 核心 API

### 获取 Handler

```python
from module.device.platform2.handlers import get_handler, all_handlers

# 根据类型名获取
handler = get_handler('MuMuPlayer12')  # -> MuMu12Handler 实例
handler = get_handler('LDPlayer9')     # -> LDPlayerHandler 实例
handler = get_handler('Unknown')       # -> None

# 获取全部已注册 Handler
for h in all_handlers():
    print(h.type_names())
```

### EmulatorHandler 接口一览

| 方法 | 用途 | 必须实现 |
|------|------|---------|
| `type_names()` | 返回管理的模拟器类型名列表 | 是 |
| `path_to_type(path, exe, dir1, dir2)` | 根据 exe 路径判断模拟器类型 | 是 |
| `multi_to_single(exe)` | 多开管理器 exe → 单实例 exe | 是 |
| `single_to_console(exe)` | 单实例 exe → 控制台 exe | 是 |
| `iter_instances(emulator)` | 枚举所有实例 | 是 |
| `iter_adb_binaries(emulator)` | 返回自带 adb 路径 | 是 |
| `build_start_command(instance)` | 构建启动命令 | 是 |
| `build_stop_command(instance)` | 构建停止命令 | 否（默认 None） |
| `stop_by_kill(instance)` | 返回 kill 进程正则 | 否（默认 None） |
| `get_instance_id(instance)` | 获取实例 ID | 否（默认 None） |
| `start_show_window()` | 启动命令是否需要窗口 | 否（默认 True） |
| `query_player_info(instance, platform)` | 查询实例运行信息 | 否（默认空 dict） |
| `try_hide_window(instance, platform, info)` | 隐藏模拟器窗口 | 否（默认 False） |
| `check_launch_state(instance, state)` | 检查启动状态 | 否（默认 ready） |
| `build_launch_confirm_timer(instance)` | 启动确认计时器 | 否（默认 None） |

**停止模拟器的优先级**: `stop_by_kill()` 返回非 None 时使用 kill 方式，否则使用 `build_stop_command()` 命令方式。

## 新增模拟器指南

以添加一个虚拟的 "FooPlayer" 模拟器为例：

### 1. 创建 Handler 文件

`handlers/foo.py`:

```python
import os
import typing as t

from module.device.platform2.handlers.base import EmulatorHandler


class FooHandler(EmulatorHandler):

    @staticmethod
    def type_names() -> list[str]:
        return ['FooPlayer']

    @staticmethod
    def path_to_type(path: str, exe: str, dir1: str, dir2: str) -> str:
        if exe == 'fooplayer.exe':
            return 'FooPlayer'
        return ''

    @staticmethod
    def multi_to_single(exe: str) -> list[str]:
        if 'FooManager.exe' in exe:
            return [exe.replace('FooManager.exe', 'FooPlayer.exe')]
        return []

    @staticmethod
    def single_to_console(exe: str) -> t.Optional[str]:
        if 'FooPlayer.exe' in exe:
            return exe.replace('FooPlayer.exe', 'fooconsole.exe')
        return None

    def iter_instances(self, emulator) -> t.Iterable:
        from module.device.platform2.emulator_windows import EmulatorInstance
        # 根据模拟器目录结构枚举实例
        for folder in emulator.list_folder('./vms', is_dir=True):
            name = os.path.basename(folder)
            yield EmulatorInstance(
                serial=f'127.0.0.1:5555',
                name=name,
                path=emulator.path,
            )

    def iter_adb_binaries(self, emulator) -> t.Iterable[str]:
        yield from self._iter_common_adb(emulator)

    def build_start_command(self, instance) -> t.Optional[str]:
        console = self.single_to_console(instance.emulator.path)
        return f'"{console}" launch --name {instance.name}'

    def build_stop_command(self, instance) -> t.Optional[str]:
        console = self.single_to_console(instance.emulator.path)
        return f'"{console}" stop --name {instance.name}'
```

### 2. 注册到 `__init__.py`

```python
from module.device.platform2.handlers.foo import FooHandler

_ALL_HANDLERS: list[EmulatorHandler] = [
    # ... 已有 handlers ...
    FooHandler(),
]
```

### 3. 添加类型常量（可选）

如果外部代码需要通过 `Emulator.FooPlayer` 比较类型，在 `emulator_base.py` 的 `EmulatorBase` 类中添加：

```python
class EmulatorBase:
    FooPlayer = 'FooPlayer'
    # ...
```

完成以上步骤后，框架会自动：
- 通过 exe 路径识别 FooPlayer
- 枚举已安装的 FooPlayer 实例
- 支持启动/停止 FooPlayer
- 将多开管理器路径转换为单实例路径

无需修改 `emulator_windows.py` 或 `platform_windows.py` 中的任何代码。
