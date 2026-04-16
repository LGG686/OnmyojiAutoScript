# This Python file uses the following encoding: utf-8

import cv2
import numpy as np


def threshold_bgr_to_inverted_rgb(image: np.ndarray, threshold: int = 100) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    inverted = np.abs(255 - binary)
    return cv2.cvtColor(inverted, cv2.COLOR_GRAY2RGB)
