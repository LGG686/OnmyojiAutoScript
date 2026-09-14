# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import numpy as np
from contextvars import ContextVar
from math import ceil, hypot

from module.base.decorator import cached_property
from module.logger import logger


class RuleClick:
    _task_click_state = ContextVar('ruleclick_task_click_state', default=None)
    _recent_limit = 6

    @classmethod
    def reset_task_points(cls):
        """每次任务启动清空各规则的近期落点和全局上一落点。"""
        RuleClick._task_click_state.set({'rules': {}, 'previous_point': None})

    def __init__(self, roi_front: tuple, roi_back: tuple, name: str = None) -> None:
        """
        初始化
        :param roi_front:
        :param roi_back:
        """
        self.roi_front = roi_front
        self.roi_back = roi_back
        if name:
            self.name = name
        else:
            self.name = 'click'

    def coord(self) -> tuple:
        """
        获取坐标，在 roi_front 内按近期落点自适应采样。
        :return:
        """
        return self._circle_normal_coord(self.roi_front)

    def coord_more(self) -> tuple:
        """
        在 roi_back 内按近期落点自适应采样。
        :return:
        """
        return self._circle_normal_coord(self.roi_back)

    def _circle_normal_coord(self, roi: tuple) -> tuple:
        """以近期落点收缩中心，沿运动方向执行椭圆正态采样。"""
        x, y, width, height = roi
        if width <= 0 or height <= 0:
            raise ValueError(f'RuleClick roi must have positive size: {roi}')

        left, right = ceil(x), ceil(x + width)
        top, bottom = ceil(y), ceil(y + height)
        if left >= right or top >= bottom:
            raise ValueError(f'RuleClick roi contains no integer pixel: {roi}')
        task_state = RuleClick._task_click_state.get()
        if task_state is None:
            self.reset_task_points()
            task_state = RuleClick._task_click_state.get()
        rules = task_state['rules']
        # 动态创建的同名同区域规则也复用本任务的点击状态。
        key = (self.name, tuple(roi))
        if key not in rules:
            rules[key] = {
                'anchor': (
                    float(np.random.uniform(left, right)),
                    float(np.random.uniform(top, bottom)),
                ),
                'recent': [],
                'count': 0,
            }
        rule_state = rules[key]
        anchor_x, anchor_y = rule_state['anchor']
        recent = rule_state['recent']

        if recent:
            weights = np.arange(1, len(recent) + 1, dtype=float)
            recent_x = float(np.average([point[0] for point in recent], weights=weights))
            recent_y = float(np.average([point[1] for point in recent], weights=weights))
            # 保留初始习惯区域的约束，避免落点均值无界漂移。
            center_x = anchor_x * 0.35 + recent_x * 0.65
            center_y = anchor_y * 0.35 + recent_y * 0.65
        else:
            center_x, center_y = anchor_x, anchor_y

        previous = task_state['previous_point']
        if previous is None:
            direction_x, direction_y = 1.0, 0.0
            movement = hypot(width, height)
        else:
            direction_x = center_x - previous[0]
            direction_y = center_y - previous[1]
            movement = hypot(direction_x, direction_y)
        if movement < 1e-6:
            direction_x, direction_y = 1.0, 0.0
            movement = 0.0
        else:
            direction_x /= movement
            direction_y /= movement
        perpendicular_x, perpendicular_y = -direction_y, direction_x

        scale = max(1.0, min(width, height))
        # 点击次数越多越集中，但始终保留约6%目标尺度的离散度。
        shrink = max(0.45, 1.0 / np.sqrt(1.0 + 0.22 * rule_state['count']))
        movement_scale = min(movement, hypot(width, height) * 3)
        sigma_parallel = max(scale * 0.06, (scale * 0.24 + movement_scale * 0.035) * shrink)
        sigma_perpendicular = max(scale * 0.045, (scale * 0.14 + movement_scale * 0.018) * shrink)

        for _ in range(96):
            parallel_error = float(np.random.normal(0, sigma_parallel))
            perpendicular_error = float(np.random.normal(0, sigma_perpendicular))
            click_x = int(round(
                center_x + direction_x * parallel_error
                + perpendicular_x * perpendicular_error
            ))
            click_y = int(round(
                center_y + direction_y * parallel_error
                + perpendicular_y * perpendicular_error
            ))
            if x <= click_x < x + width and y <= click_y < y + height:
                recent.append((click_x, click_y))
                del recent[:-self._recent_limit]
                rule_state['count'] += 1
                task_state['previous_point'] = (click_x, click_y)
                return click_x, click_y

        # 极窄区域拒绝采样耗尽时，回退到框内最近的整数点。
        click_x = min(right - 1, max(left, int(round(center_x))))
        click_y = min(bottom - 1, max(top, int(round(center_y))))
        recent.append((click_x, click_y))
        del recent[:-self._recent_limit]
        rule_state['count'] += 1
        task_state['previous_point'] = (click_x, click_y)
        return click_x, click_y

    @property
    def center(self) -> tuple:
        """
        返回roi_front的中心坐标
        :return:
        """
        x, y, w, h = self.roi_front
        return x + w // 2, y + h // 2

    def move(self, x: int, y: int) -> None:
        """
        移动roi_front, 需要限幅x是0-1280, y是0-720
        :param x:
        :param y:
        :return:
        """
        x, y, w, h = self.roi_front
        x += x
        y += y
        if x <= 0:
            x = 0
        elif x >= 1280:
            x = 1280

        if y <= 0:
            y = 0
        elif y >= 720:
            y = 720

        self.roi_front = x, y, w, h

    def __repr__(self):
        return self.name
