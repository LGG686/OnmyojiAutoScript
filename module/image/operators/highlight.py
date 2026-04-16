# This Python file uses the following encoding: utf-8

import cv2
import numpy as np

from module.base.utils import color_similarity_2d


def apply_mask(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    image16 = image.astype(np.uint16)
    mask16 = mask.astype(np.uint16)
    mask16 = cv2.merge([mask16, mask16, mask16])
    image16 = cv2.multiply(image16, mask16)
    image16 = cv2.convertScaleAbs(image16, alpha=1 / 255)
    return image16.astype(np.uint8)


def highlight_similar_color(image: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    yuv = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    _, u, _ = cv2.split(yuv)
    cv2.subtract(128, u, dst=u)
    cv2.multiply(u, 8, dst=u)

    color_mask = color_similarity_2d(image, color=color)
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    _, _, v = cv2.split(hsv)
    image = apply_mask(image, u)
    image = apply_mask(image, color_mask)
    image = apply_mask(image, v)

    cv2.convertScaleAbs(image, alpha=3, dst=image)
    cv2.subtract((255, 255, 255, 0), image, dst=image)
    return image
