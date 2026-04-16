# This Python file uses the following encoding: utf-8

from __future__ import annotations

import numpy as np

from module.atom.image import RuleImage
from module.image.rpc import get_image_client


def match_highlight_rule(rule_image: RuleImage, image: np.ndarray, frame_id: str | None = None) -> bool:
    original_roi_front = list(rule_image.roi_front)
    result = get_image_client().match_rule_with_brightness_window(
        rule_data=rule_image.to_service_payload(),
        image=image,
        frame_id=frame_id,
    )
    matched = rule_image._apply_match_result(result)
    if not matched:
        rule_image.roi_front = original_roi_front
    return matched
