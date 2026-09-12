# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import numpy as np
from contextvars import ContextVar
from math import ceil

from module.base.decorator import cached_property
from module.logger import logger


class RuleClick:
    _task_circles = ContextVar('ruleclick_task_circles', default=None)

    @classmethod
    def reset_task_points(cls):
        """每次任务启动清空圆心；资源首次使用时惰性选点。"""
        RuleClick._task_circles.set({})

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
        获取坐标，在任务固定圆与 roi_front 的交集内正态随机取点。
        :return:
        """
        return self._circle_normal_coord(self.roi_front)

    def coord_more(self) -> tuple:
        """
        在任务固定圆与 roi_back 的交集内正态随机取点。
        :return:
        """
        return self._circle_normal_coord(self.roi_back)

    def _circle_normal_coord(self, roi: tuple) -> tuple:
        """随机圆心，十字到边框的最长线段为半径，拒绝圆或框外点。"""
        x, y, width, height = roi
        if width <= 0 or height <= 0:
            raise ValueError(f'RuleClick roi must have positive size: {roi}')

        left, right = ceil(x), ceil(x + width)
        top, bottom = ceil(y), ceil(y + height)
        if left >= right or top >= bottom:
            raise ValueError(f'RuleClick roi contains no integer pixel: {roi}')
        circles = RuleClick._task_circles.get()
        if circles is None:
            self.reset_task_points()
            circles = RuleClick._task_circles.get()
        # 动态创建的同名同区域规则也复用本任务的圆心。
        key = (self.name, tuple(roi))
        if key not in circles:
            center_x = int(np.random.randint(left, right))
            center_y = int(np.random.randint(top, bottom))
            radius = max(center_x - x, x + width - center_x,
                         center_y - y, y + height - center_y)
            circles[key] = (center_x, center_y, radius)
        center_x, center_y, radius = circles[key]
        deviation = max(0.01, radius / 3)

        for _ in range(96):
            click_x = int(round(np.random.normal(center_x, deviation)))
            click_y = int(round(np.random.normal(center_y, deviation)))
            distance = (click_x - center_x) ** 2 + (click_y - center_y) ** 2
            if (
                distance <= radius ** 2
                and x <= click_x < x + width
                and y <= click_y < y + height
            ):
                return click_x, click_y

        return int(round(center_x)), int(round(center_y))

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
