from tasks.Component.ReplaceShikigami.assets import ReplaceShikigamiAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.page import Page, page_guild, random_click
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.KekkaiUtilize.assets import KekkaiUtilizeAssets

page_guild_realm = Page(KekkaiUtilizeAssets.I_REALM_SHIN)
page_guild_realm.connect(page_guild, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_guild_realm->page_guild")
page_guild.connect(page_guild_realm, KekkaiUtilizeAssets.I_GUILD_REALM, key="page_guild->page_guild_realm")

page_guild_card = Page(KekkaiUtilizeAssets.I_CHECK_GUILD_CARD)
page_guild_card.connect(page_guild_realm, GameUiAssets.I_REALM_RAID_GOTO_EXPLORATION, key="page_guild_card->page_guild_realm")
page_guild_realm.connect(page_guild_card, KekkaiUtilizeAssets.O_R_REALM, key="page_guild_realm->page_guild_card")

page_guild_realm_growth = Page(ReplaceShikigamiAssets.I_RS_RECORDS_SHIKI)
page_guild_realm_growth.connect(page_guild_realm, GlobalGameAssets.I_UI_BACK_BLUE, key="page_guild_realm_growth->page_guild_realm")
page_guild_realm.connect(page_guild_realm_growth, KekkaiUtilizeAssets.O_R_SHIKIGAMI, key="page_guild_realm->page_guild_realm_growth")

page_guild_realm_utilize = Page(KekkaiUtilizeAssets.I_U_ENTER_REALM)
page_guild_realm_utilize.connect(page_guild_realm_growth, random_click, key="page_guild_realm_utilize->page_guild_realm_growth")
page_guild_realm_growth.connect(page_guild_realm_utilize, KekkaiUtilizeAssets.I_UTILIZE_ADD, key="page_guild_realm_growth->page_guild_realm_utilize")
