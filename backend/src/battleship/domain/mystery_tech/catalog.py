"""已定稿的十八条科技，文案与 SPEC 一致。"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Technology:
    id: str
    name: str
    tier: str
    timing: str
    description: str

    def payload(self):
        return asdict(self)


TECHNOLOGIES = (
    Technology('emergency_repair', '应急维修', 'quality', 'instant', '复活自己 1 艘，放在对方没打过的格子。'),
    Technology('extra_supply', '额外补给', 'quality', 'instant', '摸 2 张。'),
    Technology('sonar_pulse', '声呐脉冲', 'quality', 'instant', '选定对方 2×2 显形。'),
    Technology('steady_defense', '稳固防线', 'quality', 'persistent', '本局自己所有船 1 层盾牌。'),
    Technology('accelerated_loading', '加速装填', 'quality', 'persistent', '本局自己每个攻击阶段攻击次数 +1。'),
    Technology('efficient_dispatch', '高效抽调', 'quality', 'persistent', '本局自己准备阶段额外摸 1 张。'),
    Technology('battlefield_recall', '战场回撤', 'legendary', 'instant', '复活自己最多 2 艘。'),
    Technology('firepower_overload', '火力过载', 'legendary', 'instant', '本大回合自己攻击次数翻倍。'),
    Technology('global_scan', '全域扫描', 'legendary', 'instant', '随机让对方 1 艘未显形的船显形。'),
    Technology('chain_amplifier', '连锁增幅', 'legendary', 'persistent', '本局自己连锁每多 1 层，结算后摸 1 张。'),
    Technology('armor_plating', '装甲镀层', 'legendary', 'persistent', '本局自己的船第一次被击中不沉，会显形。'),
    Technology('exclusion_zone', '禁航区', 'legendary', 'persistent', '本局对方准备阶段少摸 1 张。'),
    Technology('fleet_rebirth', '舰队重生', 'mythic', 'instant', '在对方没打过的格子把己方船补到最多 6 艘，格子不够就停。'),
    Technology('silent_domain', '寂静领域', 'mythic', 'instant', '对方接下来 2 个大回合无法打出魔法卡。'),
    Technology('double_command', '双重指令', 'mythic', 'persistent', '本局自己的卡不受速阶限制，任意时段可打出任意速阶，也可直接加入连锁。'),
    Technology('spacetime_fold', '时空折叠', 'mythic', 'instant', '立即让对方 1 艘船死亡，非永久击沉，可用疗愈复活。'),
    Technology('tidal_rewrite', '潮汐改写', 'mythic', 'instant', '弃掉全部手牌再摸 4 张。'),
    Technology('overload_reaction', '过载反应', 'mythic', 'persistent', '本局每击沉对方 1 艘，立即摸 1 张并获得 1 次额外攻击。'),
)
BY_ID = {tech.id: tech for tech in TECHNOLOGIES}


def catalog():
    return [tech.payload() for tech in TECHNOLOGIES]
