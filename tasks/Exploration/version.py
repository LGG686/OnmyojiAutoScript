# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pathlib import Path
from cached_property import cached_property

from module.atom.gif import RuleGif
from module.atom.image import RuleImage
from module.base.utils import load_image, save_image
from module.image.operators import highlight_similar_color

from tasks.base_task import BaseTask
from tasks.Exploration.assets import ExplorationAssets
from dev_tools.assets_test import detect_image


class Version(BaseTask):
    pass
def highlight(image):
    return highlight_similar_color(image, color=(255, 255, 255))


class HighlightGif(RuleGif):
    def pre_process(self, image):
        return highlight(image)


class HighLight(BaseTask, ExplorationAssets):

    @cached_property
    def TEMPLATE_GIF(self) -> RuleGif:
        return HighlightGif(
            targets=[
                self.I_LIGHT1, self.I_LIGHT2, self.I_LIGHT3, self.I_LIGHT4, self.I_LIGHT5,
                self.I_LIGHT6, self.I_LIGHT7, self.I_LIGHT8, self.I_LIGHT9, self.I_LIGHT10,
                self.I_LIGHT11, self.I_LIGHT12, self.I_LIGHT13, self.I_LIGHT14,
            ],
        )


if __name__ == '__main__':
    # image = load_image(r'C:\Users\萌萌哒\Desktop\屏幕截图 2024-08-17 175713.png')
    # image = highlight(image)
    # save_image(image, r'C:\Users\萌萌哒\Desktop\1345.png')
    #
    IMAGE_FILE = r"C:\Users\萌萌哒\Desktop\QQ20240818-163854.png"
    image = load_image(IMAGE_FILE)
    from tasks.Exploration.assets import ExplorationAssets
    targe = ExplorationAssets.I_UP_COIN
    print(targe.test_match(image))

    # from dev_tools.get_images import GetAnimation
    # from module.config.config import Config
    # from module.device.device import Device
    # c = Config('oas1')
    # d = Device(c)
    # t = HighLight(c, d)
    # t.screenshot()
    #
    # t.screenshot()
    # t.appear_then_click(t.TEMPLATE_GIF)

