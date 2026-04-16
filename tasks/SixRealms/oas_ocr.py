import functools

import numpy as np


from module.base.utils import load_image
from module.image.operators import highlight_similar_color
# from module.ocr.ocr import Ocr
from module.ocr.base_ocr import BaseCor


class VerticalText(BaseCor):
    @staticmethod
    def rotate_image(image):
        height, width = image.shape[0:2]
        if height * 1.0 / width >= 1.5:
            image = np.rot90(image)
            return image
        return image

    def detect_and_ocr(self, *args, **kwargs):
        if getattr(self.model, "is_proxy", False):
            params = {"drop_score": 0.1, "box_thresh": 0.2, "vertical": True}
            for key in list(params.keys()):
                if key in kwargs:
                    params.pop(key)
            return self.model.detect_and_ocr(*args, **params, **kwargs)
        # Try hard to lower TextSystem.box_thresh
        backup = self.model.text_detector.box_thresh
        # Patch text_recognizer
        text_recognizer = self.model.text_recognizer
        # Lower drop_score
        lower_score = functools.partial(self.model.detect_and_ocr, drop_score=0.1)
        detect_and_ocr = self.model.detect_and_ocr

        def vertical_text_recognizer(img_crop_list):
            img_crop_list = [VerticalText.rotate_image(i) for i in img_crop_list]
            result = text_recognizer(img_crop_list)
            return result

        self.model.text_detector.box_thresh = 0.2
        self.model.text_recognizer = vertical_text_recognizer
        self.model.detect_and_ocr = lower_score

        try:
            result = super().detect_and_ocr(*args, **kwargs)
        finally:
            self.model.text_detector.box_thresh = backup
            self.model.text_recognizer = text_recognizer
            self.model.detect_and_ocr = detect_and_ocr
        return result


class StoneOcr(VerticalText):
    def pre_process(self, image):
        return highlight_similar_color(image, color=(234, 213, 181))


if __name__ == '__main__':
    from tasks.SixRealms.assets import SixRealmsAssets
    file = r'C:\Users\Ryland\Desktop\Desktop\20.png'
    image = load_image(file)
    ocr = StoneOcr(roi=(0,0,1280,720), area=(0,0,1280,720), mode="Full", method="Default", keyword="", name="ocr_map")
    results = ocr.detect_and_ocr(image)
    for r in results:
        print(r.box, r.ocr_text)
