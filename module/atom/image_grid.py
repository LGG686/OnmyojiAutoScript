# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import numpy as np

from module.atom.image import RuleImage
from module.image.rpc import get_image_client



class ImageGrid:

    def __init__(self, images: list[RuleImage]):
        self.images = images


    def find_anyone(self, img: np.array, frame_id: str = None) -> RuleImage or None:
        """
        在这些图片中找到其中一个
        :param img:
        :return: 如果没有找到返回None
        """
        results = get_image_client().match_many(
            rules_data=[image.to_service_payload() for image in self.images],
            image=img,
            frame_id=frame_id,
        )
        for image, result in zip(self.images, results):
            if image._apply_match_result(result):
                return image
        return None

    def find_everyone(self, img: np.array, frame_id: str = None) -> list or None:
        """
        自下而上查找所有匹配项，返回带对应image对象的排序结果
        :param img: 待匹配图像
        :return: 排序后的列表，每个元素为(image对象, (x, y, w, h))，无匹配返回None
        """
        matched = []
        results = get_image_client().match_all_any_many(
            rules_data=[image.to_service_payload() for image in self.images],
            image=img,
            frame_id=frame_id,
            threshold=0.8,
            nms_threshold=0.3,
        )
        # 收集匹配结果时保留来源image
        for image, result in zip(self.images, results):
            matches = [tuple(item) for item in result.get("matches", [])]
            for (score, x, y, w, h) in matches:
                matched.append( (image, score, (x, y, w, h)) )

        # 按y坐标升序排列（屏幕坐标系从上到下）
        sorted_results = sorted(
            matched,
            key=lambda item: item[2][1]  # item[1]是坐标元组，取y值
        )

        return sorted_results if sorted_results else None
