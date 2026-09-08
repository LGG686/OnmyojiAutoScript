# This Python file uses the following encoding: utf-8
import math

import numpy as np

from module.atom.click import RuleClick


class RuleScatter(RuleClick):
    """在多边形内按多个随机重心进行正态分布点击。"""

    _SCREEN_HALF_AREA = 1280 * 720 / 2
    _MIN_FOCUSES = 2
    _MAX_FOCUSES = 10
    _MIN_CLICK_RADIUS = 25
    _MAX_CLICK_RADIUS = 150

    def __init__(
        self,
        roi_front: tuple,
        roi_back: tuple,
        polygon: list[tuple[int, int]] | tuple[tuple[int, int], ...],
        name: str = None,
    ) -> None:
        super().__init__(roi_front=roi_front, roi_back=roi_back, name=name)
        self.polygon = self._normalize_polygon(polygon)
        # 规则对象在脚本启动、加载 assets.py 时创建，因此每次重启都会
        # 重新计算一组点击重心。
        self.click_focuses = self._generate_click_focuses()
        self.click_focus_weights = self._generate_focus_weights()

    def coord(self) -> tuple:
        return self._random_normal_point()

    def coord_more(self) -> tuple:
        return self.coord()

    @property
    def center(self) -> tuple:
        center_x, center_y, _ = self.click_focuses[0]
        return int(round(center_x)), int(round(center_y))

    def move(self, x: int, y: int) -> None:
        origin_x, origin_y, width, height = self.roi_front
        target_x = min(1280, max(0, origin_x + x))
        target_y = min(720, max(0, origin_y + y))
        dx, dy = target_x - origin_x, target_y - origin_y
        self.roi_front = target_x, target_y, width, height
        self.polygon = tuple((px + dx, py + dy) for px, py in self.polygon)
        self.click_focuses = tuple(
            (focus_x + dx, focus_y + dy, radius)
            for focus_x, focus_y, radius in self.click_focuses
        )
        self.click_focus_weights = self._generate_focus_weights()

    @staticmethod
    def _normalize_polygon(polygon):
        try:
            points = tuple((int(round(x)), int(round(y))) for x, y in polygon)
        except (TypeError, ValueError) as exc:
            raise ValueError('polygon must contain numeric (x, y) points') from exc
        if len(points) < 3 or len(set(points)) < 3:
            raise ValueError('polygon must contain at least three distinct points')
        return points

    def _polygon_area(self) -> float:
        return abs(sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(
                self.polygon,
                self.polygon[1:] + self.polygon[:1],
            )
        )) / 2

    def _focus_count(self) -> int:
        ratio = min(1.0, self._polygon_area() / self._SCREEN_HALF_AREA)
        count = round(
            self._MIN_FOCUSES
            + ratio * (self._MAX_FOCUSES - self._MIN_FOCUSES)
        )
        return max(self._MIN_FOCUSES, min(self._MAX_FOCUSES, count))

    def _generate_click_focuses(self) -> tuple:
        xs, ys = zip(*self.polygon)
        left, right = float(min(xs)), float(max(xs))
        top, bottom = float(min(ys)), float(max(ys))
        focus_count = self._focus_count()

        candidates = []
        target_candidates = max(160, focus_count * 32)
        for _ in range(target_candidates * 40):
            x = float(np.random.uniform(left, right))
            y = float(np.random.uniform(top, bottom))
            if not self._point_in_polygon(x, y):
                continue
            radius = int(np.random.randint(
                self._MIN_CLICK_RADIUS,
                self._MAX_CLICK_RADIUS + 1,
            ))
            candidates.append((x, y, radius))
            if len(candidates) >= target_candidates:
                break

        if not candidates:
            raise ValueError('RuleScatter polygon contains no sampleable point')

        # 重心只需位于多边形内；点击圆可越过边界，采样时再裁掉
        # 多边形之外的部分。
        np.random.shuffle(candidates)
        selected = list(candidates[:focus_count])
        original = tuple(candidates)
        while len(selected) < focus_count:
            selected.append(original[int(np.random.randint(0, len(original)))])
        return tuple(selected)

    def _generate_focus_weights(self) -> tuple:
        """同一多边形内，越靠右下的重心点击概率越高。"""
        xs, ys = zip(*self.polygon)
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        width = max(1.0, right - left)
        height = max(1.0, bottom - top)
        raw_weights = []
        for x, y, _ in self.click_focuses:
            position = ((x - left) / width + (y - top) / height) / 2
            # 左上权重 0.80，右下权重 1.00，差距保持温和。
            raw_weights.append(0.80 + 0.20 * position)
        total = sum(raw_weights)
        return tuple(weight / total for weight in raw_weights)

    def _random_normal_point(self) -> tuple:
        index = int(np.random.choice(
            len(self.click_focuses),
            p=self.click_focus_weights,
        ))
        center_x, center_y, radius = self.click_focuses[index]
        deviation = max(0.01, radius / 3)
        for _ in range(96):
            x = float(np.random.normal(center_x, deviation))
            y = float(np.random.normal(center_y, deviation))
            if math.hypot(x - center_x, y - center_y) > radius:
                continue
            click_x, click_y = int(round(x)), int(round(y))
            if self._point_in_polygon(click_x, click_y):
                return click_x, click_y

        # 极窄或凹多边形可能连续拒绝随机点，回退时也不允许
        # 把取整后落在边框外的重心直接返回。
        fallback_x = int(round(center_x))
        fallback_y = int(round(center_y))
        if self._point_in_polygon(fallback_x, fallback_y):
            return fallback_x, fallback_y
        for distance in range(1, int(math.ceil(radius)) + 1):
            for offset in range(-distance, distance + 1):
                candidates = (
                    (fallback_x + offset, fallback_y - distance),
                    (fallback_x + offset, fallback_y + distance),
                    (fallback_x - distance, fallback_y + offset),
                    (fallback_x + distance, fallback_y + offset),
                )
                for click_x, click_y in candidates:
                    if math.hypot(
                        click_x - center_x,
                        click_y - center_y,
                    ) > radius:
                        continue
                    if self._point_in_polygon(click_x, click_y):
                        return click_x, click_y
        raise ValueError('RuleScatter clipped circle contains no integer point')

    def _point_in_polygon(self, x: float, y: float) -> bool:
        inside = False
        previous_x, previous_y = self.polygon[-1]
        for current_x, current_y in self.polygon:
            if (current_y > y) != (previous_y > y):
                intersect_x = (
                    (previous_x - current_x) * (y - current_y)
                    / (previous_y - current_y)
                    + current_x
                )
                if x < intersect_x:
                    inside = not inside
            previous_x, previous_y = current_x, current_y
        return inside
