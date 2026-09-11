from tasks.DailyTrifles.assets import DailyTriflesAssets
from tasks.GameUi.default_pages import page_friends, page_guild
from tasks.GameUi.page import Page, page_mall, page_mall_recommend
from tasks.GlobalGame.assets import GlobalGameAssets

# 商店礼包屋页面
page_store_gift_room = Page(DailyTriflesAssets.I_GIFT_RECOMMEND)
page_store_gift_room.connect(page_mall, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_store_gift_room->page_mall")
page_mall.connect(page_store_gift_room, DailyTriflesAssets.I_ROOM_GIFT, key="page_mall->page_store_gift_room")
page_mall_recommend.connect(page_store_gift_room, DailyTriflesAssets.I_ROOM_GIFT,
                            key="page_mall_recommend->page_store_gift_room")
# 好友吉闻页面
page_friends_luck = Page(DailyTriflesAssets.I_LUCK_TITLE, priority=75)
page_friends_luck.connect(page_friends, DailyTriflesAssets.I_CLOSE_LUCK_RED, key="page_friends_luck->page_friends")
page_friends.connect(page_friends_luck, DailyTriflesAssets.O_LUCK_MSG, key="page_friends->page_friends_luck")
page_friends_luck.add_enter_failure_hooks(DailyTriflesAssets.I_FRIENDSHIP_UP)
# 寮祈愿页面
page_guild_wish = Page(DailyTriflesAssets.I_DT_CHECK_GUILD_WISH)
page_guild_wish.connect(page_guild, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_guild_wish->page_guild")
page_guild.connect(page_guild_wish, DailyTriflesAssets.I_GUILD_TO_WISH, key="page_guild->page_guild_wish")
