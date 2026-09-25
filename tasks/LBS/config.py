# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import BaseModel, Field
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.SwitchSoul.switch_soul_config import SwitchSoulConfig


class LBSConfig(BaseModel):
    # 限制时间
    limit_time: Time = Field(default=Time(minute=30), description='limit_time_help')
    # 限制次数（想打的次数，与活动剩余次数无关）
    limit_count: int = Field(default=30, description='limit_count_help')
    # 组队模式：寻找队伍+自动匹配；关闭则创建不公开房间
    team_match: bool = Field(default=False, description='team_match_help')


class LBS(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    lbs_config: LBSConfig = Field(default_factory=LBSConfig)
    switch_soul: SwitchSoulConfig = Field(default_factory=SwitchSoulConfig)
    general_battle_config: GeneralBattleConfig = Field(default_factory=GeneralBattleConfig)
