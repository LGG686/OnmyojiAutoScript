# This Python file uses the following encoding: utf-8
"""OAS Android 设备后端：所有设备 I/O 经 AzurPilot-for-Android 本机特权桥完成。

桥监听 127.0.0.1:22301，协议为行分隔 JSON；screencap 元数据行后紧接 BGR888 原始帧。
本模块不 import adb / uiautomator2；serial 使用哨兵值 "oasaos"。

注意：
- 桥输出 BGR888，OAS 的 device.image 约定是 RGB，这里交换红蓝通道。
- 目标游戏必须跑在 App 创建的虚拟屏上；displayId 由 ping 实时获取，不缓存。
- 虚拟屏固定 1280x720 横屏，get_orientation 直接返回 0。
- dump_hierarchy 不可用：uiautomator 只反映主屏，不能用于虚拟屏。
"""
import array
import json
import mmap
import os
import re
import shlex
import socket
import threading
import time

import numpy as np

from module.base.decorator import cached_property
from module.exception import GameNotRunningError, RequestHumanTakeover, ScriptError
from module.logger import logger

OASAOS_DEFAULT_ADDR = '127.0.0.1:22301'
OASAOS_SERIAL = 'oasaos'

# 桥的内建 click 是固定 50ms 的手势并同步等回调；用原地 swipe 表达同一次点击，
# 10ms 实测被游戏正常接受（庭院点开头像弹设置面板），单次耗时从约 60ms 降到 20~33ms。
OASAOS_CLICK_DURATION_MS = 10

# 共享内存帧通道：抽象 Unix socket，App 侧监听，握手时用 SCM_RIGHTS 交出只读映射 FD。
OASAOS_FRAME_SOCKET = 'com.azurpilot.ghio.frames.v1'
OASAOS_FRAME_MAX_BYTES = 32 * 1024 * 1024
OASAOS_FRAME_MAX_LINE = 4096
OASAOS_FRAME_TIMEOUT = 5
# 通道异常后回退 TCP 的冷却时间，避免每帧都多付一次失败握手。
OASAOS_FRAME_RETRY_SECONDS = 30


class OasaosBridgeError(Exception):
    """特权桥通信异常。"""
    pass


class OasaosFrameError(Exception):
    """共享内存帧通道异常。"""
    pass


class OasaosNoFrame(OasaosFrameError):
    """虚拟屏当前没有可读帧，等价于游戏未运行。"""
    pass


class OasaosSharedFrame:
    """按连接独占的共享内存截图：控制消息走抽象 Unix socket，像素只在本机内存里拷贝。

    服务端每帧先把最新画面拷进映射区再回响应，客户端必须在下一次请求前复制成自有图像，
    否则视图会被下一帧覆盖。映射 FD 由服务端通过 SCM_RIGHTS 交出，只读。

    Connection-owned shared-memory capture: control messages over an abstract Unix socket,
    pixels copied inside the local mapping. The server publishes the latest frame into the
    mapping before replying, so the client must copy before the next request.
    """

    def __init__(self, timeout=OASAOS_FRAME_TIMEOUT):
        self.timeout = timeout
        self.sock = None
        self.mapping = None
        self.capacity = 0
        self.pid = os.getpid()
        self.lock = threading.RLock()

    def close(self) -> None:
        with self.lock:
            sock, self.sock = self.sock, None
            mapping, self.mapping = self.mapping, None
            self.capacity = 0
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if mapping is not None:
            try:
                mapping.close()
            except (OSError, BufferError):
                pass

    def _recv_response(self, receive_fd=False) -> dict:
        header = bytearray()
        fds = []
        try:
            while b'\n' not in header:
                if receive_fd:
                    data, ancillary, _, _ = self.sock.recvmsg(
                        OASAOS_FRAME_MAX_LINE, socket.CMSG_SPACE(array.array('i').itemsize))
                    for level, kind, payload in ancillary:
                        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                            received = array.array('i')
                            received.frombytes(
                                payload[:len(payload) - len(payload) % received.itemsize])
                            fds.extend(received)
                else:
                    data = self.sock.recv(OASAOS_FRAME_MAX_LINE)
                if not data:
                    raise OasaosFrameError('capture channel closed')
                header.extend(data)
                if len(header) > OASAOS_FRAME_MAX_LINE:
                    raise OasaosFrameError('response line too long')
            # 本通道没有像素负载，只允许一个未完成请求，换行后多出的字节属于协议错误。
            line, extra = bytes(header).split(b'\n', 1)
            if extra:
                raise OasaosFrameError('unexpected response bytes')
            response = json.loads(line.decode('utf-8'))
            if not isinstance(response, dict):
                raise OasaosFrameError('invalid response')
            if not response.get('ok'):
                error = str(response.get('error', 'capture failed'))
                if 'no frame available' in error:
                    raise OasaosNoFrame(error)
                raise OasaosFrameError(error)
            if receive_fd:
                if len(fds) != 1 or response.get('version') != 1:
                    raise OasaosFrameError('invalid shared-memory handshake')
                capacity = response.get('capacity')
                if type(capacity) is not int or not 0 < capacity <= OASAOS_FRAME_MAX_BYTES:
                    raise OasaosFrameError('invalid shared-memory capacity')
                self.mapping = mmap.mmap(
                    fds[0], capacity, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ)
                self.capacity = capacity
            return response
        finally:
            for fd in fds:
                os.close(fd)

    def _connect(self) -> None:
        self.close()
        if not hasattr(socket, 'SCM_RIGHTS'):
            raise OasaosFrameError('SCM_RIGHTS unavailable')
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock = sock
        try:
            sock.settimeout(self.timeout)
            # 抽象地址无文件路径，不受 PRoot 路径重写影响。
            sock.connect('\0' + OASAOS_FRAME_SOCKET)
            sock.sendall(b'{"method":"open","version":1}\n')
            self._recv_response(receive_fd=True)
        except (OSError, OasaosFrameError):
            self.close()
            raise

    def capture(self) -> np.ndarray:
        """返回自有、连续的 RGB 图像；断连或改尺寸时在同一次调用内重开一次。"""
        # fork 后不能沿用父进程的请求流，也不能持有父进程可能持有的锁。
        if self.pid != os.getpid():
            self.close()
            self.pid = os.getpid()
            self.lock = threading.RLock()
        with self.lock:
            for attempt in range(2):
                try:
                    if self.sock is None:
                        self._connect()
                    self.sock.sendall(b'{"method":"screencap"}\n')
                    response = self._recv_response()
                    width = response.get('width')
                    height = response.get('height')
                    length = response.get('length')
                    if (type(width) is not int or type(height) is not int
                            or width <= 0 or height <= 0 or response.get('channels') != 3
                            or type(length) is not int or length != width * height * 3
                            or length > self.capacity):
                        raise OasaosFrameError('invalid frame geometry')
                    # 复制同时把桥的 BGR 换成 OAS 约定的 RGB，返回值不保留会被覆盖的视图。
                    return np.ndarray((height, width, 3), dtype=np.uint8,
                                      buffer=self.mapping)[..., ::-1].copy()
                except OasaosNoFrame:
                    raise
                except (OSError, ValueError, OasaosFrameError):
                    self.close()
                    if attempt:
                        raise
            raise OasaosFrameError('capture failed')


class Oasaos:
    _oasaos_sock = None
    _oasaos_req_id = 0
    _oasaos_lock = threading.RLock()
    # 最近一帧实际使用的传输通道，便于日志与调试。
    oasaos_capture_transport = 'tcp'
    # 共享内存通道失败后的下一次协商时间（monotonic）。
    _oasaos_frame_retry_at = 0.0

    # ---------------------------------------------------------------- 协议层

    @cached_property
    def oasaos_addr(self) -> str:
        return os.environ.get('OASAOS_BRIDGE_ADDR', OASAOS_DEFAULT_ADDR)

    @cached_property
    def oasaos_shared_frame(self):
        """共享内存帧通道客户端；桥不支持或平台没有 SCM_RIGHTS 时为 None。"""
        if not hasattr(socket, 'SCM_RIGHTS'):
            return None
        if not self.oasaos_capabilities().get('sharedMemoryScreencap'):
            return None
        logger.info('Oasaos capture transport: shared_memory')
        return OasaosSharedFrame()

    def _oasaos_connect(self) -> socket.socket:
        host, _, port = self.oasaos_addr.partition(':')
        sock = socket.create_connection((host, int(port)), timeout=10)
        sock.settimeout(60)
        return sock

    def _oasaos_call(self, payload: dict) -> dict:
        with self._oasaos_lock:
            return self._oasaos_call_locked(payload)

    def _oasaos_call_locked(self, payload: dict) -> dict:
        Oasaos._oasaos_req_id += 1
        payload = dict(payload)
        payload['id'] = Oasaos._oasaos_req_id

        last_error = None
        for _ in range(2):
            try:
                sock = Oasaos._oasaos_sock
                if sock is None:
                    sock = Oasaos._oasaos_sock = self._oasaos_connect()
                line = json.dumps(payload, separators=(',', ':')).encode('utf-8') + b'\n'
                sock.sendall(line)
                # 逐字节读响应行：screencap 元数据行后紧跟原始像素，大块读会吞帧
                buf = b''
                while not buf.endswith(b'\n'):
                    data = sock.recv(1)
                    if not data:
                        raise OasaosBridgeError('proxy closed connection')
                    buf += data
                    if len(buf) > 256 * 1024:
                        raise OasaosBridgeError('response line too long')
                return json.loads(buf.decode('utf-8'))
            except (OSError, OasaosBridgeError, json.JSONDecodeError) as e:
                last_error = e
                logger.warning(f'Oasaos bridge error: {e}, reconnecting')
                self._oasaos_close_sock()
        logger.critical(f'Oasaos bridge unreachable: {last_error}')
        raise RequestHumanTakeover

    @staticmethod
    def _oasaos_close_sock() -> None:
        sock = Oasaos._oasaos_sock
        Oasaos._oasaos_sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _oasaos_call_ok(self, payload: dict) -> dict:
        resp = self._oasaos_call(payload)
        if not resp.get('ok'):
            raise ScriptError(f'Oasaos bridge error: {resp.get("error", "unknown")}')
        return resp

    def _oasaos_read_exact(self, n: int) -> bytes:
        sock = Oasaos._oasaos_sock
        chunks = []
        while n > 0:
            data = sock.recv(min(1048576, n))
            if not data:
                raise OasaosBridgeError('connection closed mid-frame')
            chunks.append(data)
            n -= len(data)
        return b''.join(chunks)

    # ---------------------------------------------------------------- 截图 / 触控

    def screenshot_oasaos(self) -> np.ndarray:
        with self._oasaos_lock:
            client = self.oasaos_shared_frame
            if client is not None and time.monotonic() >= self._oasaos_frame_retry_at:
                try:
                    image = client.capture()
                    self.oasaos_capture_transport = 'shared_memory'
                    return image
                except OasaosNoFrame as e:
                    raise GameNotRunningError(f'Oasaos bridge: {e}')
                except (OasaosFrameError, OSError, ValueError) as e:
                    # 通道不可用就回退 TCP，并冷却一段时间再重新协商，避免每帧多付一次失败开销。
                    self._oasaos_frame_retry_at = time.monotonic() + OASAOS_FRAME_RETRY_SECONDS
                    logger.warning(f'Oasaos 共享内存截图不可用，回退 TCP: {e}')
            self.oasaos_capture_transport = 'tcp'
            resp = self._oasaos_call({'method': 'screencap'})
            if not resp.get('ok'):
                error = str(resp.get('error', 'unknown'))
                if 'no frame available' in error:
                    # 虚拟屏上没有游戏窗口时桥不产帧。按「游戏未运行」上抛，
                    # OAS 才会走 Restart 恢复；当作 ScriptError 会直接停机。
                    raise GameNotRunningError(f'Oasaos bridge: {error}')
                raise ScriptError(f'Oasaos bridge error: {error}')
            try:
                raw = self._oasaos_read_exact(int(resp['length']))
            except (OSError, OasaosBridgeError):
                self._oasaos_close_sock()
                raise
        image = np.frombuffer(raw, dtype=np.uint8).reshape(
            int(resp['height']), int(resp['width']), int(resp['channels']))
        if image.shape[2] >= 3:
            image = image[..., 2::-1]
        return np.ascontiguousarray(image)

    def click_oasaos(self, x, y) -> None:
        # 桥的内建 click 固定 50ms 手势；原地 swipe 表达同一次点击，10ms 已被游戏接受。
        self._oasaos_call_ok({
            'method': 'swipe',
            'x1': int(x), 'y1': int(y), 'x2': int(x), 'y2': int(y),
            'duration': OASAOS_CLICK_DURATION_MS,
        })

    def long_click_oasaos(self, x, y, duration) -> None:
        # 桥没有独立长按端点，等效为原地点击式 swipe；duration 由秒转毫秒
        self._oasaos_call_ok({
            'method': 'swipe',
            'x1': int(x), 'y1': int(y), 'x2': int(x), 'y2': int(y),
            'duration': int(duration * 1000),
        })

    def swipe_oasaos(self, p1, p2, duration=0.1, hold_duration=None) -> None:
        # press_and_drag 需要起点停顿，但桥只暴露一次 swipe；把停顿折进总时长
        total = float(duration) + (float(hold_duration) if hold_duration else 0.0)
        self._oasaos_call_ok({
            'method': 'swipe',
            'x1': int(p1[0]), 'y1': int(p1[1]),
            'x2': int(p2[0]), 'y2': int(p2[1]),
            'duration': int(total * 1000),
        })

    # ---------------------------------------------------------------- shell / 状态

    def oasaos_shell(self, cmd: str, timeout: float = 30) -> dict:
        return self._oasaos_call({'method': 'shell', 'cmd': cmd, 'timeout': timeout})

    def oasaos_shell_output(self, cmd: str, timeout: float = 30) -> str:
        resp = self.oasaos_shell(cmd, timeout)
        if not resp.get('ok') or resp.get('code', 0) != 0:
            raise ScriptError(
                f'Oasaos shell failed: {cmd!r}: {str(resp.get("stderr", ""))[:200]}')
        return resp.get('stdout', '')

    def oasaos_ping(self) -> dict:
        return self._oasaos_call_ok({'method': 'ping'})

    def oasaos_capabilities(self) -> dict:
        return self.oasaos_ping().get('capabilities', {}) or {}

    @property
    def oasaos_display_id(self) -> int:
        display_id = self.oasaos_ping().get('displayId')
        if not isinstance(display_id, int) or display_id < 1:
            raise ScriptError(f'Oasaos virtual display not ready: {display_id!r}')
        return display_id

    # ---------------------------------------------------------------- App 控制

    def oasaos_resolve_activity(self, package: str) -> str:
        """解析 launcher Activity，返回 pkg/activity 形式。"""
        out = self.oasaos_shell_output(
            f'cmd package resolve-activity --brief {shlex.quote(package)}', timeout=15)
        for line in reversed(out.strip().splitlines()):
            line = line.strip()
            if '/' in line and not line.startswith('Error'):
                return line
        out = self.oasaos_shell_output(
            f'dumpsys package {shlex.quote(package)}', timeout=30)
        match = re.search(
            r'android\.intent\.action\.MAIN:\s+\w+\s+([\w.$/]+)\s+filter \w+\s+'
            r'.*?Category: "android\.intent\.category\.LAUNCHER"', out, re.S)
        if match:
            component = match.group(1)
            if '/' not in component:
                component = f'{package}/{component}'
            return component
        raise ScriptError(f'No launcher activity found for {package}')

    def app_start_oasaos(self, package_name=None) -> bool:
        package = package_name or self.package
        display_id = self.oasaos_display_id
        caps = self.oasaos_capabilities()
        if caps.get('nativeGameResolution'):
            self._oasaos_call_ok({
                'method': 'app_prepare', 'package': package, 'displayId': display_id,
            })
        component = self.oasaos_resolve_activity(package)
        # -W 等启动完成再返回。窗口没建好就 app_focus 会回 no ready target window，
        # 而 am start 立即返回时窗口往往还在创建中。
        out = self.oasaos_shell_output(
            f'am start -W --display {display_id} -n {shlex.quote(component)}', timeout=60)
        if 'Error' in out:
            raise ScriptError(f'Oasaos app start failed: {out.strip()[:200]}')
        if caps.get('appFocus'):
            self._oasaos_call_ok({
                'method': 'app_focus', 'package': package, 'displayId': display_id,
            })
        return True

    def app_stop_oasaos(self, package_name=None) -> None:
        package = package_name or self.package
        self.oasaos_shell_output(f'am force-stop {shlex.quote(package)}')

    def app_is_alive_oasaos(self, package_name=None) -> bool:
        package = package_name or self.package
        resp = self.oasaos_shell(f'pidof {shlex.quote(package)}', timeout=10)
        return bool(resp.get('ok') and resp.get('stdout', '').strip())

    def app_current_oasaos(self, timeout: float = 30) -> str:
        out = self.oasaos_shell_output(
            'dumpsys window displays | grep -E "Display|mCurrentFocus|mFocusedApp"',
            timeout=timeout)
        display_id = self.oasaos_display_id
        for block in re.split(r'\n\s*(?=Display)', out):
            if not re.search(r'(?:displayId|mDisplayId)=%d\b' % display_id, block):
                continue
            match = re.search(r'mCurrentFocus=Window\{[^}]*?\s([\w.$]+)/', block)
            if not match:
                match = re.search(
                    r'mFocusedApp=.*?ActivityRecord\{[^}]*?\s([\w.$]+)/', block)
            current = match.group(1) if match else ''
            logger.attr('App current (oasaos)', current)
            return current
        logger.attr('App current (oasaos)', '')
        return ''

    # ---------------------------------------------------------------- 兼容钩子

    def get_orientation(self):
        if getattr(self, 'serial', None) == OASAOS_SERIAL:
            self.orientation = 0
            return 0
        return super().get_orientation()

    def dump_hierarchy_oasaos(self):
        raise ScriptError('Android 虚拟屏不支持 uiautomator 层级树，请使用截图识别')
