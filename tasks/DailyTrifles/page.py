from tasks.DailyTrifles.assets import DailyTriflesAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.default_pages import page_friends
from tasks.GameUi.page import Page, page_mall
from tasks.GlobalGame.assets import GlobalGameAssets

# 商店礼包屋页面
page_store_gift_room = Page(DailyTriflesAssets.I_GIFT_RECOMMEND)
page_store_gift_room.connect(page_mall, GameUiAssets.I_BACK_Y, key="page_store_gift_room->page_mall")
page_mall.connect(page_store_gift_room, DailyTriflesAssets.I_ROOM_GIFT, key="page_mall->page_store_gift_room")
# 好友吉闻页面
page_friends_luck = Page(DailyTriflesAssets.I_LUCK_TITLE)
page_friends_luck.connect(page_friends, GameUiAssets.I_BACK_FRIENDS, key="page_friends_luck->page_friends")
page_friends.connect(page_friends_luck, DailyTriflesAssets.O_LUCK_MSG, key="page_friends->page_friends_luck")
