"""指挥官角色目录：首批四名原创海战指挥官、技能规格与 2～20 级逐级奖励。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


UNLOCK_COST_TIDE_ASH = 500
MAX_LEVEL = 20
XP_PER_LEVEL = 200
MAX_XP = (MAX_LEVEL - 1) * XP_PER_LEVEL  # 3800


@dataclass(frozen=True)
class SkillSpec:
    id: str
    name: str
    commander_id: str
    kind: str  # 'limited' | 'cooldown' | 'per_chain'
    enters_chain: bool
    speed: int | None
    max_uses: int | None
    cooldown_rounds: int
    requires_own_ship: bool
    timing_label: str
    limit_label: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "commander_id": self.commander_id,
            "kind": self.kind,
            "enters_chain": self.enters_chain,
            "speed": self.speed,
            "max_uses": self.max_uses,
            "cooldown_rounds": self.cooldown_rounds,
            "requires_own_ship": self.requires_own_ship,
            "timing_label": self.timing_label,
            "limit_label": self.limit_label,
            "description": self.description,
        }


@dataclass(frozen=True)
class CommanderSpec:
    id: str
    name: str
    gender: str
    title_tagline: str
    outfit: str
    personality: str
    palette: dict[str, str]
    skill: SkillSpec
    voice_lines: dict[str, str]
    rewards: dict[int, dict[str, Any]]
    profile_cosmetics: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender,
            "title_tagline": self.title_tagline,
            "outfit": self.outfit,
            "personality": self.personality,
            "palette": dict(self.palette),
            "skill": self.skill.to_dict(),
            "voice_lines": dict(self.voice_lines),
            "rewards": {
                str(lvl): dict(info) for lvl, info in sorted(self.rewards.items())
            },
            "profile_cosmetics": dict(self.profile_cosmetics),
            "assets": {
                "portraits": {
                    "base": f"/commanders/{self.id}/portrait_base.svg",
                    "ascended": f"/commanders/{self.id}/portrait_ascended.svg",
                    "alt": f"/commanders/{self.id}/portrait_alt.svg",
                    "ultimate": f"/commanders/{self.id}/portrait_ultimate.svg",
                },
                "avatar": f"/commanders/{self.id}/avatar.svg",
                "emojis": {
                    "emoji_1": f"/commanders/{self.id}/emoji_1.svg",
                    "emoji_2": f"/commanders/{self.id}/emoji_2.svg",
                    "emoji_3": f"/commanders/{self.id}/emoji_3.svg",
                    "emoji_dynamic": f"/commanders/{self.id}/emoji_dynamic.svg",
                },
                "voices": {
                    key: f"/commanders/{self.id}/{key}.ogg"
                    for key in (
                        "voice_greet",
                        "voice_sortie",
                        "voice_skill_1",
                        "voice_victory",
                        "voice_interact",
                        "voice_skill_2",
                        "voice_mastery",
                    )
                },
            },
        }


def _build_rewards(
    cid: str,
    cname: str,
    names: dict[str, str],
) -> tuple[dict[int, dict[str, Any]], dict[str, str]]:
    frame_1 = f"cmd_{cid}_frame_1"
    frame_2 = f"cmd_{cid}_frame_2"
    bg_1 = f"cmd_{cid}_bg_1"
    bg_2 = f"cmd_{cid}_bg_2"
    title_20 = f"cmd_{cid}_title_20"

    rewards: dict[int, dict[str, Any]] = {
        2: {
            "level": 2,
            "label": f"{cname}·问候语音",
            "category": "voice",
            "summary": "2 级解锁问候语音，可在指挥官页试听并在对局中发送问候。",
            "items": [{"kind": "voice", "id": "voice_greet", "name": f"{cname}问候语音"}],
        },
        3: {
            "level": 3,
            "label": f"表情①「{names['e1']}」",
            "category": "emoji",
            "summary": "3 级解锁角色专属表情①，可在对局快捷发送。",
            "items": [{"kind": "emoji", "id": "emoji_1", "name": f"表情①「{names['e1']}」"}],
        },
        4: {
            "level": 4,
            "label": f"{cname}·出击语音",
            "category": "voice",
            "summary": "4 级解锁出击语音，匹配成功亮牌登场时可触发。",
            "items": [{"kind": "voice", "id": "voice_sortie", "name": f"{cname}出击语音"}],
        },
        5: {
            "level": 5,
            "label": f"专属头像+基础头像框「{names['f1']}」",
            "category": "tier_milestone",
            "milestone_tier": 1,
            "summary": "5 级里程碑：解锁角色专属头像，以及可装备至个人名片的专属基础头像框。",
            "items": [
                {"kind": "avatar", "id": f"cmd_{cid}_avatar", "name": f"{cname}专属头像"},
                {"kind": "frame", "id": frame_1, "name": f"基础头像框「{names['f1']}」"},
            ],
        },
        6: {
            "level": 6,
            "label": f"{cname}·技能语音",
            "category": "voice",
            "summary": "6 级解锁招牌技能发动语音，主动释放技能时伴随播报。",
            "items": [{"kind": "voice", "id": "voice_skill_1", "name": f"{cname}技能语音"}],
        },
        7: {
            "level": 7,
            "label": f"表情②「{names['e2']}」",
            "category": "emoji",
            "summary": "7 级解锁角色专属表情②。",
            "items": [{"kind": "emoji", "id": "emoji_2", "name": f"表情②「{names['e2']}」"}],
        },
        8: {
            "level": 8,
            "label": f"{cname}·胜利语音",
            "category": "voice",
            "summary": "8 级解锁胜利语音，对局获胜结算界面自动响起。",
            "items": [{"kind": "voice", "id": "voice_victory", "name": f"{cname}胜利语音"}],
        },
        9: {
            "level": 9,
            "label": f"角色资料卡背景「{names['bg1']}」",
            "category": "profile_bg",
            "summary": "9 级解锁角色主题个人资料卡背景。",
            "items": [{"kind": "card_bg", "id": bg_1, "name": f"资料卡背景「{names['bg1']}」"}],
        },
        10: {
            "level": 10,
            "label": f"进阶立绘+动态头像框「{names['f2']}」",
            "category": "tier_milestone",
            "milestone_tier": 2,
            "summary": "10 级里程碑：解锁高阶战术武装立绘与动态流光头像框，局内外形象全面升级。",
            "items": [
                {"kind": "portrait", "id": "ascended", "name": f"{cname}·进阶立绘"},
                {"kind": "frame", "id": frame_2, "name": f"动态头像框「{names['f2']}」"},
            ],
        },
        11: {
            "level": 11,
            "label": f"{cname}·对局互动语音",
            "category": "voice",
            "summary": "11 级解锁对局互动语音，战局胶着时向对手或队友致意。",
            "items": [{"kind": "voice", "id": "voice_interact", "name": f"{cname}对局互动语音"}],
        },
        12: {
            "level": 12,
            "label": f"表情③「{names['e3']}」",
            "category": "emoji",
            "summary": "12 级解锁角色专属表情③。",
            "items": [{"kind": "emoji", "id": "emoji_3", "name": f"表情③「{names['e3']}」"}],
        },
        13: {
            "level": 13,
            "label": f"专属胜利展示动作「{names['vm']}」",
            "category": "victory_motion",
            "summary": "13 级解锁终局结算专属胜利动态展示动作。",
            "items": [{"kind": "victory_motion", "id": "exclusive", "name": f"胜利动作「{names['vm']}」"}],
        },
        14: {
            "level": 14,
            "label": f"{cname}·新增技能语音组",
            "category": "voice",
            "summary": "14 级解锁新增技能语音组，与基础技能语音可自由装配切换或轮播。",
            "items": [{"kind": "voice", "id": "voice_skill_2", "name": f"{cname}新增技能语音组"}],
        },
        15: {
            "level": 15,
            "label": f"强化登场动画+专属技能视觉特效「{names['vfx']}」",
            "category": "tier_milestone",
            "milestone_tier": 3,
            "summary": "15 级里程碑：强化匹配亮牌登场动画与局内专属技能视觉特效。",
            "items": [
                {"kind": "intro", "id": "enhanced", "name": f"{cname}·强化登场动画"},
                {"kind": "skill_vfx", "id": "exclusive", "name": f"技能视觉特效「{names['vfx']}」"},
            ],
        },
        16: {
            "level": 16,
            "label": f"动态表情「{names['ed']}」",
            "category": "emoji",
            "summary": "16 级解锁带动态光影的舰桥专属动态表情。",
            "items": [{"kind": "emoji", "id": "emoji_dynamic", "name": f"动态表情「{names['ed']}」"}],
        },
        17: {
            "level": 17,
            "label": f"进阶立绘配色款「{names['alt']}」",
            "category": "portrait",
            "summary": "17 级解锁进阶立绘特别战术配色款。",
            "items": [{"kind": "portrait", "id": "alt", "name": f"进阶立绘配色款「{names['alt']}」"}],
        },
        18: {
            "level": 18,
            "label": f"动态资料卡背景「{names['bg2']}」",
            "category": "profile_bg",
            "summary": "18 级解锁带动态海况光纹的个人资料卡背景。",
            "items": [{"kind": "card_bg", "id": bg_2, "name": f"动态资料卡背景「{names['bg2']}」"}],
        },
        19: {
            "level": 19,
            "label": f"{cname}·精通语音组",
            "category": "voice",
            "summary": "19 级解锁精通语音组，展现身经百战的巅峰统帅台词。",
            "items": [{"kind": "voice", "id": "voice_mastery", "name": f"{cname}精通语音组"}],
        },
        20: {
            "level": 20,
            "label": f"终阶动态立绘+最高档登场特效+专属动态称号「{names['t20']}」",
            "category": "tier_milestone",
            "milestone_tier": 4,
            "summary": "20 级满级巅峰里程碑：解锁终阶动态立绘、最高档登场特效及全服展示的专属动态称号。",
            "items": [
                {"kind": "portrait", "id": "ultimate", "name": f"{cname}·终阶动态立绘"},
                {"kind": "intro", "id": "ultimate", "name": f"{cname}·最高档登场特效"},
                {"kind": "title", "id": title_20, "name": f"专属动态称号「{names['t20']}」"},
            ],
        },
    }
    cosmetics = {
        "frame_1": frame_1,
        "frame_1_name": names["f1"],
        "frame_2": frame_2,
        "frame_2_name": names["f2"],
        "bg_1": bg_1,
        "bg_1_name": names["bg1"],
        "bg_2": bg_2,
        "bg_2_name": names["bg2"],
        "title_20": title_20,
        "title_20_name": names["t20"],
    }
    return rewards, cosmetics


_CHICHAO_REWARDS, _CHICHAO_COSMETICS = _build_rewards(
    "chichao",
    "赤潮",
    {
        "e1": "校准完成",
        "e2": "全弹齐发",
        "e3": "胜券在握",
        "ed": "红莲警报",
        "f1": "赤环火控",
        "f2": "炽潮烈环",
        "bg1": "红黑战列舱",
        "bg2": "赤潮奔涌",
        "vm": "凌空收剑敬礼",
        "vfx": "绯红火控弹幕",
        "alt": "夜袭黑红涂装",
        "t20": "赤潮统制者",
    },
)

_QINGTONG_REWARDS, _QINGTONG_COSMETICS = _build_rewards(
    "qingtong",
    "青瞳",
    {
        "e1": "声呐就绪",
        "e2": "静观其变",
        "e3": "尽在掌握",
        "ed": "青瞳深扫",
        "f1": "海雾棱环",
        "f2": "深渊观测环",
        "bg1": "海图推演室",
        "bg2": "潮汐星轨",
        "vm": "单手合拢怀表",
        "vfx": "蔚蓝延迟准星",
        "alt": "霜月银灰风衣",
        "t20": "深海凝视者",
    },
)

_TIEANCHOR_REWARDS, _TIEANCHOR_COSMETICS = _build_rewards(
    "tieanchor",
    "铁锚",
    {
        "e1": "阵型稳固",
        "e2": "正面迎敌",
        "e3": "纹丝不动",
        "ed": "重甲共振",
        "f1": "镇海铁环",
        "f2": "无畏重盾环",
        "bg1": "深蓝装甲甲板",
        "bg2": "铁锚怒涛",
        "vm": "重锚砸地立誓",
        "vfx": "玄青铁壁护幕",
        "alt": "玄铁白金礼服",
        "t20": "无畏镇海使",
    },
)

_GUIHANG_REWARDS, _GUIHANG_COSMETICS = _build_rewards(
    "guihang",
    "归航",
    {
        "e1": "请先出招",
        "e2": "深思熟虑",
        "e3": "优雅落子",
        "ed": "星辉算筹",
        "f1": "白金航标",
        "f2": "星锚流金环",
        "bg1": "白金提督沙龙",
        "bg2": "金浪归帆",
        "vm": "提督披风回身",
        "vfx": "曜金算阵换牌",
        "alt": "深空靛蓝礼装",
        "t20": "白金掌棋人",
    },
)


COMMANDERS: tuple[CommanderSpec, ...] = (
    CommanderSpec(
        id="chichao",
        name="赤潮",
        gender="女",
        title_tagline="高烈度齐射火控官",
        outfit="红黑短军装 · 配战术臂铠与火控目镜",
        personality="凌厉干练、果断迅猛",
        palette={
            "primary": "#e84855",
            "secondary": "#1d141b",
            "accent": "#ff9e7d",
            "glow": "rgba(232, 72, 85, 0.42)",
        },
        skill=SkillSpec(
            id="firepower_control",
            name="火力统制",
            commander_id="chichao",
            kind="limited",
            enters_chain=False,
            speed=None,
            max_uses=1,
            cooldown_rounds=0,
            requires_own_ship=False,
            timing_label="己方准备或战斗阶段（无连锁时，不入链）",
            limit_label="限定技 · 整局 1 次",
            description=(
                "本大回合内将己方总开火额度固定为 6 次，并扣除本大回合已经消耗的开火次数；"
                "生效期间魔法卡、每周异变与神秘科技均无法再增减该总开火额度（若已开火满 6 次则剩余为 0）。"
                "过载反应的额外攻击次数将被压制，但击沉摸牌效果照常触发。"
            ),
        ),
        voice_lines={
            "voice_greet": "舰桥已就位。赤潮号全炮门待命，指示目标吧，指挥官。",
            "voice_sortie": "红黑旗帜升起！第一轮齐射，绝不留情！",
            "voice_skill_1": "全舰听令——火力统制开启，六轮压制射击准备！",
            "voice_victory": "海面已肃清。干脆利落的胜仗，正合我意！",
            "voice_interact": "别犹豫，瞄准敌舰轮廓最清晰的那一格！",
            "voice_skill_2": "算力重新分配——所有炮位锁定最大齐射序列！",
            "voice_mastery": "不需要花哨的变数，六发炮火足以定鼎战局！",
        },
        rewards=_CHICHAO_REWARDS,
        profile_cosmetics=_CHICHAO_COSMETICS,
    ),
    CommanderSpec(
        id="qingtong",
        name="青瞳",
        gender="男",
        title_tagline="深海声呐侦测参谋",
        outfit="蓝灰长外套 · 佩声呐单镜与潮汐罗盘",
        personality="冷静克制、算无遗策",
        palette={
            "primary": "#4ea8de",
            "secondary": "#14202e",
            "accent": "#9be7ff",
            "glow": "rgba(78, 168, 222, 0.42)",
        },
        skill=SkillSpec(
            id="delayed_lock",
            name="延迟锁定",
            commander_id="qingtong",
            kind="cooldown",
            enters_chain=False,
            speed=None,
            max_uses=None,
            cooldown_rounds=4,
            requires_own_ship=False,
            timing_label="己方准备或战斗阶段（无连锁时，不入链）",
            limit_label="冷却技 · 间隔 4 个完整大回合",
            description=(
                "随机选中敌方 1 艘存活舰船（包含已显形目标）挂上「暴露」标记。"
                "在发动当回合与下一大回合全部结束、且所有大回合结束效果结算完毕后，按常规显形规则揭示该舰位置（无额外持续回合限制）。"
                "揭晓前仅船主可见具体被标记船只，青瞳方与观战方无法提前获知目标；若目标在揭晓前死亡，标记立即消失且复活后不恢复。"
            ),
        ),
        voice_lines={
            "voice_greet": "潮汐与风向都已校准。请保持冷静，局势尽在视线之内。",
            "voice_sortie": "航迹已记录。不必急于出手，先看清对手的破绽。",
            "voice_skill_1": "声呐相位偏移……延迟锁定已完成，静待海雾散去。",
            "voice_victory": "推演与结果分毫不差。胜负早已在锁定那一刻注定。",
            "voice_interact": "再等一回合，隐藏在暗处的舰影就会自己浮出水面。",
            "voice_skill_2": "光学校准重构——即便身处迷雾，也无处可遁。",
            "voice_mastery": "青瞳观测之下，没有永远沉默的坐标。倒计时开始了。",
        },
        rewards=_QINGTONG_REWARDS,
        profile_cosmetics=_QINGTONG_COSMETICS,
    ),
    CommanderSpec(
        id="tieanchor",
        name="铁锚",
        gender="男",
        title_tagline="重装防线舰队司令",
        outfit="深蓝重型军装 · 负重甲肩章与铁锚徽章",
        personality="沉稳厚重、坚不可摧",
        palette={
            "primary": "#3b76f6",
            "secondary": "#0f172a",
            "accent": "#7dd3fc",
            "glow": "rgba(59, 118, 246, 0.42)",
        },
        skill=SkillSpec(
            id="dauntless_fleet",
            name="无畏舰队",
            commander_id="tieanchor",
            kind="limited",
            enters_chain=True,
            speed=3,
            max_uses=1,
            cooldown_rounds=0,
            requires_own_ship=False,
            timing_label="任意合法出牌及连锁响应窗口（速阶三，入链）",
            limit_label="限定技 · 整局 1 次（发动即消耗）",
            description=(
                "速阶三入链（可被「失灵！」无效化，发动即消耗整局次数，被无效也不返还）。"
                "成功结算后，本大回合内己方所有舰船持续获得「无畏」（含后续新增或复活的己方舰船），大回合结束时统一失效。"
                "「无畏」仅抵消普通炮击击沉：被普通炮击命中仍消耗 1 次攻击并使隐藏船显形，但不损毁击沉；魔法卡与神秘科技伤害不受「无畏」抵消。"
            ),
        ),
        voice_lines={
            "voice_greet": "装甲舱室巡检完毕。只要铁锚还在舰队前方，防线就不会崩塌。",
            "voice_sortie": "锚链收起，全舰保持阵型！风浪再大，我们也稳如磐石！",
            "voice_skill_1": "全舰提升装甲隔舱——无畏舰队，正面迎击炮火！",
            "voice_victory": "钢铁与信念都没有辜负我们。安全返航！",
            "voice_interact": "普通的炮弹击不沉真正的铁舰。稳住节奏。",
            "voice_skill_2": "损管全面接管！就算暴露位置，也休想击沉任何一艘！",
            "voice_mastery": "以此身铸就海上长城——全舰进入无畏态势，不可动摇！",
        },
        rewards=_TIEANCHOR_REWARDS,
        profile_cosmetics=_TIEANCHOR_COSMETICS,
    ),
    CommanderSpec(
        id="guihang",
        name="归航",
        gender="女",
        title_tagline="远洋舰队策略统帅",
        outfit="白金军官服 · 佩星芒披风与指挥怀表",
        personality="从容优雅、以退为进",
        palette={
            "primary": "#eab354",
            "secondary": "#191f2c",
            "accent": "#fef08a",
            "glow": "rgba(234, 179, 84, 0.42)",
        },
        skill=SkillSpec(
            id="sacrifice_gambit",
            name="弃舰筹谋",
            commander_id="guihang",
            kind="per_chain",
            enters_chain=True,
            speed=3,
            max_uses=None,
            cooldown_rounds=0,
            requires_own_ship=True,
            timing_label="任意合法出牌及连锁响应窗口（速阶三，入链）",
            limit_label="每条连锁至多 1 次 · 需己方存活舰船 > 1",
            description=(
                "速阶三入链（可被「失灵！」无效化）。发动前提为己方存活舰船数 > 1；"
                "发动时当场主动暴露并牺牲 1 艘己方自选存活舰船作为代价（留下残骸，触发既有牺牲规则，被无效化也不退还），"
                "连锁结算生效后摸 2 张魔法卡。每大回合不限发动次数，但同一条连锁内至多发动 1 次。"
            ),
        ),
        voice_lines={
            "voice_greet": "海图已经展开，每一枚棋子都有它的去处。欢迎登舰，指挥官。",
            "voice_sortie": "风平浪静适合谋篇布局。让我们优雅地赢下这一局。",
            "voice_skill_1": "舍弃一隅，方能换得全局胜机——弃舰筹谋！",
            "voice_victory": "从容落子，满盘皆归航。干得漂亮。",
            "voice_interact": "一艘护卫舰的退场，有时能换回决定胜负的手牌。",
            "voice_skill_2": "计算已然清晰，付出这份代价——两枚胜手归位。",
            "voice_mastery": "真正的掌棋人从不畏惧暂时的损耗。请收下这手逆转之牌。",
        },
        rewards=_GUIHANG_REWARDS,
        profile_cosmetics=_GUIHANG_COSMETICS,
    ),
)

COMMANDER_BY_ID: dict[str, CommanderSpec] = {c.id: c for c in COMMANDERS}
COMMANDER_IDS: tuple[str, ...] = tuple(c.id for c in COMMANDERS)
DEFAULT_COMMANDER_ID = "chichao"

DEFAULT_EQUIPPED: dict[str, str] = {
    "portrait": "base",
    "voice_pack": "base",
    "intro": "base",
    "skill_vfx": "base",
    "victory_motion": "base",
    "avatar": "default",
    "emoji_slot": "emoji_1",
}


def get_commander(commander_id: str | None) -> CommanderSpec | None:
    if not isinstance(commander_id, str):
        return None
    return COMMANDER_BY_ID.get(commander_id.strip())


def commander_chain_identity(
    item_kind: str | None, commander_id: str | None, skill_id: str | None,
) -> dict[str, str]:
    if item_kind != "commander_skill":
        return {}
    commander = get_commander(commander_id)
    if commander is None or not commander.skill.enters_chain or skill_id != commander.skill.id:
        return {}
    return {"item_kind": "commander_skill", "commander_id": commander.id, "skill_id": commander.skill.id}


def profile_cosmetics_entries() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """供 `profile_spec.py` 注入称号、头像框、资料卡背景池子的单源清单。"""
    titles: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    card_bgs: list[dict[str, Any]] = []
    for cmd in COMMANDERS:
        cos = cmd.profile_cosmetics
        frames.append({
            "id": cos["frame_1"],
            "name": cos["frame_1_name"],
            "desc": f"指挥官「{cmd.name}」5 级专属基础头像框",
            "requirement": f"指挥官「{cmd.name}」达到 5 级并领取奖励",
        })
        frames.append({
            "id": cos["frame_2"],
            "name": cos["frame_2_name"],
            "desc": f"指挥官「{cmd.name}」10 级专属动态头像框",
            "requirement": f"指挥官「{cmd.name}」达到 10 级并领取奖励",
        })
        card_bgs.append({
            "id": cos["bg_1"],
            "name": cos["bg_1_name"],
            "desc": f"指挥官「{cmd.name}」9 级专属资料卡背景",
            "requirement": f"指挥官「{cmd.name}」达到 9 级并领取奖励",
        })
        card_bgs.append({
            "id": cos["bg_2"],
            "name": cos["bg_2_name"],
            "desc": f"指挥官「{cmd.name}」18 级专属动态资料卡背景",
            "requirement": f"指挥官「{cmd.name}」达到 18 级并领取奖励",
        })
        titles.append({
            "id": cos["title_20"],
            "name": cos["title_20_name"],
            "desc": f"指挥官「{cmd.name}」20 级满级专属动态称号",
            "requirement": f"指挥官「{cmd.name}」达到 20 级并领取奖励",
        })
    return titles, frames, card_bgs


__all__ = [
    "COMMANDERS",
    "COMMANDER_BY_ID",
    "COMMANDER_IDS",
    "DEFAULT_COMMANDER_ID",
    "DEFAULT_EQUIPPED",
    "MAX_LEVEL",
    "MAX_XP",
    "UNLOCK_COST_TIDE_ASH",
    "XP_PER_LEVEL",
    "CommanderSpec",
    "SkillSpec",
    "get_commander",
    "profile_cosmetics_entries",
]
