# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from module.logger import logger

from tasks.WeeklyPurchase.mall.medal import Medal
from tasks.WeeklyPurchase.mall.charisma import Charisma
from tasks.WeeklyPurchase.mall.consignment import Consignment
from tasks.WeeklyPurchase.mall.scales import Scales
from tasks.WeeklyPurchase.mall.honor import Honor
from tasks.WeeklyPurchase.mall.bondlings import Bondlings
from tasks.GameUi.page import page_main, page_mall, page_mall_recommend


class Mall(Medal, Charisma, Honor, Consignment, Scales, Bondlings):

    def execute_mall(self):
        logger.hr('Mall', 1)
        self.goto_page(page_mall_recommend, confirm_wait=2.5, accepted_pages=(page_mall,))

        # 寄售屋
        self.execute_consignment()
        self.device.click_record_clear()
        # 蛇皮
        self.execute_scales()
        self.device.click_record_clear()
        # 契灵
        self.execute_bondlings()
        self.device.click_record_clear()

        # 杂货铺
        self.execute_special()
        self.device.click_record_clear()
        self.execute_honor()
        self.device.click_record_clear()
        self.execute_friendship()
        self.device.click_record_clear()
        self.execute_medal()
        self.device.click_record_clear()
        self.execute_charisma()
        self.device.click_record_clear()

        # 退出
        self.back_mall()
