"""竖屏应用 UI 操作混入（Mixin）。

OAS 默认横屏 1280x720：minitouch 的 convert()（module/device/method/minitouch.py）
与 nemu_ipc 的 convert_xy() 都按横屏缩放坐标。操作原生竖屏应用（720x1280,
orientation=0，如网易大神 com.netease.gl）时，必须绕开 minitouch 改用 adb input tap
直传原始坐标，并跳过会反复调 dumpsys 的 check_screen_size。

用法：任务类继承 PortraitUIMixin（继承 BaseTask，复用 appear/device/screenshot 等），
进入竖屏应用前调用 _init_portrait()，之后用 _appear_then_click / _screenshot_safe /
_launch_app_foreground。
"""
from typing import TYPE_CHECKING

import time

from module.logger import logger
from module.base.timer import Timer
from tasks.base_task import BaseTask

GL_PACKAGE = "com.netease.gl"


class PortraitUIMixin(BaseTask):
    """竖屏 UI 操作混入类。继承 BaseTask 复用 appear/device/screenshot，宿主需提供 _adb_shell。"""

    if TYPE_CHECKING:
        def _adb_shell(self, cmd, timeout=15): ...

    def _is_oasaos(self):
        """与 ScriptTask / 核心设备层同一判据，让 mixin 单独使用也成立。"""
        device = getattr(self, 'device', None)
        if device is None:
            return False
        serial = getattr(device, 'serial', None)
        if serial == 'oasaos':
            return True
        config = getattr(self, 'config', None)
        script = getattr(config, 'script', None) if config is not None else None
        section = getattr(script, 'device', None) if script is not None else None
        return section is not None and getattr(section, 'screenshot_method', '') == 'oasaos'

    def _init_portrait(self):
        """进入竖屏应用前调用：关闭横屏假设的屏幕检查，锁定 orientation=0。"""
        # 720x1280+orientation=0：check_screen_size 会反复调 dumpsys 且无法旋正，直接跳过
        self.device._screen_size_checked = True
        self.device._screen_black_checked = True
        self.device.orientation = 0

    def _appear_then_click(self, target, interval=None, threshold=None):
        """竖屏版 appear_then_click：appear+interval防抖，点击走 adb tap 绕开 minitouch 横屏缩放。
        签名与 base_task.appear_then_click 对齐。"""
        appear = self.appear(target, interval=interval, threshold=threshold)
        if appear:
            x, y = target.coord()
            self._tap(x, y, name=target.name)
        return appear

    def _tap(self, x, y, name=None):
        """竖屏点击：adb input tap 直传原始坐标，与 control_method 无关。
        Oasaos 下走桥触控（绑定当前虚拟屏），input tap 只会落在主屏。"""
        logger.info(f'点击 {name} @ ({x},{y})')
        if self._is_oasaos():
            self.device.click_oasaos(x, y)
            return
        self._adb_shell(['input', 'tap', str(x), str(y)])

    def _swipe(self, x1, y1, x2, y2, duration=400):
        """竖屏滑动：adb input swipe 直传原始坐标，与 control_method 无关。
        duration 为按下到抬起的时间(ms)，调大可减少松手后的惯性滚动。
        Oasaos 下走桥触控（绑定当前虚拟屏）。"""
        logger.info(f'滑动 ({x1},{y1}) -> ({x2},{y2}) ({duration}ms)')
        if self._is_oasaos():
            self.device.swipe_oasaos((x1, y1), (x2, y2), duration=duration / 1000.0)
            return
        self._adb_shell(['input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(duration)])

    def _screenshot_safe(self):
        """竖屏截图：优先配置方法（self.screenshot），失败回退 OAS 自带 adb 截图。"""
        try:
            self.screenshot()
            return
        except Exception as e:
            logger.warning(f'截图方法 {self.config.script.device.screenshot_method} 失败: {e}')
        fallback = getattr(self.device, 'screenshot_adb', None)
        if callable(fallback):
            try:
                self.device.image = fallback()
                return
            except Exception as e:
                logger.warning(f'adb 截图回退失败: {e}')
        # 两条路都没拿到新帧：旧 image_frame_id 已被服务端替换或过期（默认 TTL 3s），
        # 继续用它匹配只会 KeyError: Unknown frame id 崩掉任务。清掉引用让本轮按
        # 本地旧图匹配，下一轮循环重新截图，而不是带着失效帧引用退出。
        self.device.image_frame_id = None
        self.device.invalidate_image_batch_cache()

    def _launch_app_foreground(self, package, timeout=30):
        """前台启动指定包名 app（UI导航需要app可见）。低性能设备可调大 timeout。
        优先 am start（monkey 在部分安卓虚拟机会卡住不返回）。

        Oasaos 通道：虚拟屏临时切竖屏 720x1280，把 app 投进虚拟屏，截图/点击/模板
        三者落在同一块屏、同一套坐标；桌面/Redroid 保持原来的主屏启动不变。"""
        device = getattr(self, 'device', None)
        if device is not None and callable(getattr(device, 'oasaos_set_display_size', None)) \
                and self._is_oasaos():
            logger.info('Oasaos 虚拟屏切竖屏 720x1280')
            # set_display_size 会重建虚拟屏（displayId 变化，旧屏内容销毁）。若目标 app
            # 已在旧屏上运行，am start --display 只会把它拉回前台，窗口仍留在已销毁的旧屏，
            # 新屏全程黑屏：截图有帧但全是黑的，识别永远匹配不到。先强停让下一次启动在新屏
            # 重建窗口，这是竖屏临时屏用完后必须付出的代价（该 app 本就是本次签到的工具）。
            device.app_stop_oasaos(package)
            stop_timer = Timer(3, count=3).start()
            while self._pidof(package) and not stop_timer.reached():
                time.sleep(0.2)
            display_id = device.oasaos_set_display_size(720, 1280)
            device.app_start_portrait_oasaos(package, display_id=display_id)
            confirm = Timer(timeout, count=2).start()
            while 1:
                if self._pidof(package):
                    logger.info(f'{package} 已在虚拟屏运行')
                    return True
                if confirm.reached():
                    logger.warning(f'等待 {package} 启动超时（{timeout}s）')
                    return False
        # 优先 am start（动态获取主 activity，避免硬编码版本漂移）
        component = self._resolve_main_activity(package)
        if component:
            try:
                logger.info(f'am start {component}...')
                self._adb_shell(['am', 'start', '-n', component])
            except Exception as e:
                logger.warning(f'am start 失败: {e}, 回退 monkey')
                component = None
        if not component:
            try:
                logger.info(f'monkey 启动 {package}...')
                self._adb_shell(['monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1'])
            except Exception as e:
                logger.warning(f'启动APP失败: {e}')
                return False
        confirm = Timer(timeout, count=2).start()
        while 1:
            pid = self._pidof(package)
            if pid:
                logger.info(f'{package} 运行中 (PID: {pid})')
                return True
            if confirm.reached():
                logger.warning(f'等待 {package} 启动超时（{timeout}s）')
                return False

    def _resolve_main_activity(self, package):
        """通过 cmd package resolve-activity 获取主 activity component，失败返回 None。
        返回形如 'com.netease.gl/.ui.activity.welcome.WelcomeInitActivity'。"""
        try:
            out = self._adb_shell(['cmd', 'package', 'resolve-activity', '--brief', package])
            for line in out.splitlines():
                if '/' in line and package in line:
                    return line.strip()
        except Exception as e:
            logger.warning(f'获取主activity失败: {e}')
        return None

    def _pidof(self, package):
        """获取进程 PID，不存在返回 None。兼容 pidof 不可用的设备（安卓虚拟机等）。
        优先 pidof，回退 ps -A | grep。"""
        # 优先 pidof（多数 Android 可用，输出纯 PID）
        try:
            out = self._adb_shell(['pidof', package])
            if out:
                return int(out.split()[0])
        except Exception as e:
            logger.warning(f'pidof 失败: {e}')
        # 回退 ps -A（pidof 不可用或进程名带冒号子进程时）
        try:
            out = self._adb_shell(['ps', '-A'])
            for line in out.splitlines():
                # 匹配包名（含 :remote 等子进程）
                if package in line:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        return int(parts[1])
        except Exception as e:
            logger.warning(f'ps 检测失败: {e}')
        return None

    def _cleanup_portrait(self):
        """竖屏任务清理：杀死大神APP进程，把阴阳师游戏重新拉到前台，并还原横屏状态。"""
        try:
            logger.info(f'杀死大神APP进程: {GL_PACKAGE}')
            self._adb_shell(['am', 'force-stop', GL_PACKAGE])
        except Exception as e:
            logger.warning(f'杀死大神APP失败: {e}')
        # 把阴阳师游戏重新拉到前台（竖屏app已杀死，恢复游戏界面）
        pkg = self.config.script.device.package_name
        component = self._resolve_main_activity(pkg)
        if self._is_oasaos():
            # 大神从虚拟屏退出：先把屏切回 1280x720 横屏，再用 app_start_oasaos 恢复
            # 游戏原生渲染与焦点；裸 am start 不带 --display 会落回主屏。
            logger.info('Oasaos 虚拟屏切回横屏 1280x720')
            self.device.oasaos_set_display_size(1280, 720)
            try:
                logger.info('恢复阴阳师到虚拟屏')
                self.device.app_start_oasaos(pkg)
                self.device.wait_app_start_ready(timeout=30)
                logger.info('阴阳师已进入虚拟屏，清理完成')
            except Exception as e:
                logger.warning(f'恢复阴阳师到虚拟屏失败: {e}')
        elif component:
            try:
                logger.info(f'恢复阴阳师前台: {component}')
                self._adb_shell(['am', 'start', '-n', component])
                # 冷启动要几秒才真正切到前台；等到 app_is_running() 为 True 再撒手，
                # 否则下一个任务的前置检查(app_is_running)会扑空、误判"游戏未运行"，
                # 继而派发 Restart 把刚拉起的游戏又杀掉重开一次（13:14 日志实测：
                # 恢复前台后 0.75s 即被 Restart 的 full restart 重新拉起）
                self.device.wait_app_start_ready(timeout=30)
                logger.info('阴阳师已进入前台，清理完成')
            except Exception as e:
                logger.warning(f'恢复阴阳师前台失败: {e}')
        # 还原 _init_portrait 改掉的横屏状态：屏幕已切回横屏而 device.orientation 仍为 0 时，
        # minitouch convert() 不做坐标变换、把横屏坐标当竖屏面板坐标直传，后续任务点击会
        # 整体错位（10-07/10-08 实测：TalismanPass 全部点击落空、反复点同一按钮）。
        # 游戏刚回到前台时屏幕可能还在竖屏旋转中，此处取到的仍是 0，须轮询等到它真正转回
        # 横屏再取值；取到 0 就撒手等于没还原。
        self.device._screen_size_checked = False
        self.device._screen_black_checked = False
        timeout = Timer(15, count=15).start()
        while 1:
            if self.device.get_orientation() != 0:
                break
            if timeout.reached():
                logger.warning('等待屏幕转回横屏超时，orientation 仍为 0')
                break
            self.device.sleep(0.5)
