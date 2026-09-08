# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import numpy as np

from module.base.decorator import cached_property
from module.logger import logger


class RuleClick:

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
        获取坐标，在 roi_front 确定的椭圆内正态随机取点。
        :return:
        """
        return self._ellipse_normal_coord(self.roi_front)

    def coord_more(self) -> tuple:
        """
        在 roi_back 确定的椭圆内正态随机取点。
        :return:
        """
        return self._ellipse_normal_coord(self.roi_back)

    @staticmethod
    def _ellipse_normal_coord(roi: tuple) -> tuple:
        """以矩形中心为圆心，宽高为椭圆直径进行正态采样。"""
        x, y, width, height = roi
        if width <= 0 or height <= 0:
            raise ValueError(f'RuleClick roi must have positive size: {roi}')

        center_x = x + width / 2
        center_y = y + height / 2
        radius_x = width / 2
        radius_y = height / 2
        deviation_x = max(0.01, radius_x / 3)
        deviation_y = max(0.01, radius_y / 3)

        for _ in range(96):
            click_x = int(round(np.random.normal(center_x, deviation_x)))
            click_y = int(round(np.random.normal(center_y, deviation_y)))
            distance = (
                ((click_x - center_x) / radius_x) ** 2
                + ((click_y - center_y) / radius_y) ** 2
            )
            if (
                distance <= 1
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
