#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成魔法卡卡面美术提示词（docs/magic_card_art_prompts.md + .json）。

为什么要用脚本而不是直接手写文档：
  · 卡表是 static/magic_card.json，手写文档迟早会漏卡、会和卡表对不上；
  · 这里在生成前做覆盖率校验：卡表里的每张牌都必须在 CARD_ART 里有条目，
    多出来的条目（卡表里没有的牌名）会被删掉并报告。
  · 输出 JSON 是给批量生成脚本吃的，MD 是给人看的，两者同源不会漂移。

改提示词：改下面的 STYLE_* / SPEED_ACCENT / TYPE_COMPOSITION / CARD_ART，然后重跑
    python tools/gen_card_art_prompts.py
不要手改 docs/magic_card_art_prompts.md —— 它每次都会被整份覆盖。

卡面文字的渲染位置决定构图约束（见 static/game.js updateHandUI 与 static/style.css）：
    .magic-card 里从上到下依次是 .card-name / .card-speed / .card-type，
    也就是顶部 1/4 放标题、底部 1/6 放类型，美术主体只能占中间那条带。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARD_JSON = ROOT / "static" / "magic_card.json"
OUT_MD = ROOT / "docs" / "magic_card_art_prompts.md"
OUT_JSON = ROOT / "docs" / "magic_card_art_prompts.json"
OUT_ART_MAP = ROOT / "static" / "card_art_map.js"

# ---------------------------------------------------------------------------
# 统一风格：这三段拼在每张卡的主体描述前后，保证 41 张卡看起来是一套牌
# ---------------------------------------------------------------------------

STYLE_PREAMBLE = (
    "Painterly digital illustration for a naval tactics card game, cinematic "
    "semi-realistic, deep-sea military aesthetic, dark teal and navy palette, "
    "cold rim light, volumetric god rays through water, subtle film grain, "
    "one strong readable silhouette, restrained fine detail"
)

STYLE_SUFFIX = (
    "vertical 2:3 portrait composition, main subject centered in the middle "
    "band, empty shadowed space at the top and bottom for text overlay, "
    "no text, no letters, no numbers, no watermark, no logo, no signature, "
    "no card frame, no border, no UI elements"
)

NEGATIVE_PROMPT = (
    "text, letters, numbers, watermark, signature, logo, ui, card frame, border, "
    "typography, chinese characters, cluttered detail, multiple focal points, "
    "white background, pastel, kawaii, chibi, cartoon, oversaturated, "
    "blurry, low contrast, jpeg artifacts, extra limbs, deformed hands"
)

# 速阶 = 响应速度（速阶1 只有自己的准备阶段能用 → 慢；速阶3 任何阶段都能用 → 瞬发）。
# 美术上把速度编码成「光的温度与动能」，玩家扫一眼颜色就能读出这张牌多快。
SPEED_ACCENT = {
    1: "warm aged-brass and dim amber glow, slow ceremonial weight, embers drifting, "
       "calm deliberate mood",
    2: "shifting cyan and steel-blue light, mid-tempo motion, sparks and water droplets "
       "hanging in the air",
    3: "blinding cold white-cyan energy, high-speed motion, electric arcs and motion "
       "streaks, instantaneous impact",
}

# 普通卡vs场地卡：场地卡是持续存在的「环境」，所以构图要给环境让位。
TYPE_COMPOSITION = {
    "普通": "single clearly lit focal subject, the surrounding sea only hinted at",
    "场地": "wide panoramic horizon, an environmental aura or persistent field "
            "dominating the whole frame, no single small focal character",
    # 判定卡（2026-09-28 补：上游加的这一类，打出一张就要摇骰子拼点）。
    # 构图上要能一眼看出"结果未定"：骰子/天平/掷出的弧线居中，画面留出两种结局的余地。
    "判定": "a die or balance hanging at the tipping point as the central subject, "
            "motion arc still unresolved, the outcome left visibly undecided",
}

# ---------------------------------------------------------------------------
# 逐卡美术设定
#   motif  : 中文一句话，说明画面里到底画什么（给人审稿用）
#   prompt : 英文主体描述，投喂生成器的主体句
#   zh     : 中文关键词，给中文生成器（即梦/通义万相/豆包）直接用
#   slug   : 落盘文件名用的 ASCII 短名
# ---------------------------------------------------------------------------

CARD_ART = [
    dict(
        name="失灵！", slug="shiling",
        motif="一张刻满符文的牌在半空中生生折断，碎片化作飞散的火星，背后的全息印记裂开",
        prompt="a glowing rune-etched card snapped in half in mid-air, its fragments "
               "dissolving into drifting embers, a cracked holographic sigil shattering "
               "apart behind it",
        zh="漂浮的符文卡牌在半空折断，碎片化为火星，背后全息法阵开裂，失效感",
    ),
    dict(
        name="溅射", slug="jianshe",
        motif="炮弹命中船体，海水与火焰向上下左右四个方向炸成十字形的冲击环",
        prompt="a naval shell striking a steel hull, water and fire bursting outward in "
               "four cardinal directions into a perfect cross of shockwaves",
        zh="炮弹命中战舰船体，火焰与海水向四个正方向炸开成十字冲击环",
    ),
    dict(
        name="雷达子弹", slug="leida-zidan",
        motif="曳光弹贯穿船体，同心声纳环荡开，八艘幽灵船影在环中被点亮",
        prompt="a glowing tracer round punching through a dark hull, concentric sonar "
               "rings expanding outward, eight translucent ghost ship silhouettes "
               "flickering into view around it",
        zh="曳光弹穿透船体，同心声纳波环扩散，八艘半透明幽灵战舰显现",
    ),
    dict(
        name="越战越勇", slug="yuezhan-yueyong",
        motif="站在倾斜甲板上的舰长剪影，身后的燃烧残骸越来越多，金光节节拔高",
        prompt="a defiant captain silhouette standing on a listing deck, burning wrecks "
               "accumulating behind him, rising golden light, momentum building with "
               "every kill",
        zh="倾斜甲板上的舰长剪影，身后燃烧残骸渐次增加，金光攀升，越战越强",
    ),
    dict(
        name="余音绕梁", slug="yuyin-raoliang",
        motif="水下的巨钟荡出可见的同心声波，一发炮声的余响凝在半空，仍在切割海面",
        prompt="a giant bronze bell underwater emitting visible concentric sound ripples, "
               "the lingering echo of a cannon shot frozen mid-air and still cutting "
               "across the sea surface",
        zh="水下青铜巨钟荡出同心音波，炮声余响凝成实体刀刃悬停切割海面",
    ),
    dict(
        name="神威！", slug="shenwei",
        motif="3×3 的海面格子上方悬着一只巨眼，战舰被抽离水面升入现实裂隙",
        prompt="a colossal divine eye above a 3x3 grid of ocean cells, warships "
               "levitating upward out of the water into a tear in reality, awe and "
               "otherworldly light",
        zh="3×3 海面网格上方悬浮巨眼，战舰被从水中抽离升入空间裂隙，神性威严",
    ),
    dict(
        name="增援", slug="zengyuan",
        motif="一艘新战舰带着气泡与探照灯从深海浮起，周围水面干净未被击中过",
        prompt="a fresh warship surfacing from the depths amid rising bubbles and "
               "searchlights, pristine untouched water all around it, hopeful "
               "reinforcement",
        zh="全新战舰从深海浮出，气泡与探照灯环绕，四周水面完好无损，增援",
    ),
    dict(
        name="恶魔契约", slug="emo-qiyue",
        motif="两艘战舰被发光的猩红锁链绑在一起，一只爪状暗影手托着燃烧的契约",
        prompt="two warships bound together by glowing crimson chain runes, a clawed "
               "shadow hand offering a burning floating contract, twin scales in the "
               "background, ominous red and sickly green ambience",
        zh="两艘战舰被猩红符文锁链相连，爪状暗影手托起燃烧契约，背景天平，邪恶",
    ),
    dict(
        name="八方来财", slug="bafang-laicai",
        motif="八道金光从四面八方汇入一只张开的手，财货如雨，卡牌虚影环绕",
        prompt="eight streams of golden light converging from every compass direction "
               "into a single open hand, treasures raining, faint floating card "
               "silhouettes orbiting, opulent",
        zh="八道金色光流自八方汇入掌心，财宝如雨落下，卡牌虚影环绕，富贵",
    ),
    dict(
        name="平等条约", slug="pingdeng-tiaoyue",
        motif="两支舰队隔静海对峙，中间悬着发光的条约印章，天平平衡，一发炮弹绕过印章",
        prompt="two opposing fleets facing each other across a perfectly still sea, a "
               "glowing sealed treaty emblem floating between them, balanced scales, a "
               "single cannonball bypassing the seal",
        zh="两支舰队隔平静海面对峙，中央悬浮发光条约印章与天平，一发炮弹绕开印章",
    ),
    dict(
        name="禁忌果实", slug="jinji-guoshi",
        motif="黑海上枯树挂着一颗发光的禁果，树下所有符文牌化为灰石，寂静禁忌",
        prompt="a single glowing forbidden fruit hanging from a bare dead tree rising "
               "out of a still black sea, all rune cards below turned to grey stone, "
               "heavy silence, taboo glow",
        zh="漆黑海面枯树挂一颗发光禁果，树下符文卡牌全部化为灰石，禁忌寂静",
    ),
    dict(
        name="硫磺火焰", slug="liuhuang-huoyan",
        motif="一条蜿蜒的硫磺火河烧过六个相连格子，钢板熔融，浓烟与火星",
        prompt="a winding river of molten sulfur flame scorching across six linked ocean "
               "grid cells, incandescent yellow-green fire, steel hulls melting, thick "
               "smoke and embers",
        zh="蜿蜒的硫磺熔岩火河席卷六个相连网格，黄绿白炽烈焰熔穿船体，浓烟",
    ),
    dict(
        name="百亿补贴", slug="baiyi-butie",
        motif="沉没的己方战舰化作金光瀑布，转化成炮弹上的发光攻击标记",
        prompt="a sinking allied warship dissolving into a cascade of golden light that "
               "converts into glowing attack markers around a cannon, sacrifice turned "
               "into power",
        zh="沉没的友舰化为金光瀑布汇入炮口，凝成发光的攻击计数，牺牲换力量",
    ),
    dict(
        name="看破！", slug="kanpo",
        motif="一只水晶巨瞳看穿层层幻象，对面一整排符文牌变透明并崩解",
        prompt="a piercing crystalline eye looking through layers of illusion, a row of "
               "enemy rune cards turning transparent and disintegrating, cold X-ray "
               "light, absolute clarity",
        zh="水晶巨瞳穿透层层幻象，一整排敌方符文卡变透明崩解，冷光透视",
    ),
    dict(
        name="冻结", slug="dongjie",
        motif="一片海格瞬间冻成狰狞蓝冰，战舰被封在透明冰里，浪花定格悬空",
        prompt="an ocean grid patch flash-freezing into jagged blue ice crystals, "
               "warships encased in translucent ice, frozen spray hanging motionless in "
               "the air, absolute stillness",
        zh="海面网格瞬间冻结成尖锐蓝冰晶，战舰被封于透明冰中，浪花悬停定格",
    ),
    dict(
        name="轰炸", slug="hongzha",
        motif="轰炸机编队沿着一整行依次投弹，爆炸连成一条笔直的线",
        prompt="a bomber squadron laying a perfectly straight line of explosions down a "
               "single row of an ocean grid, sequential blast chain, black smoke, "
               "high-altitude cinematic view",
        zh="轰炸机编队沿一整行网格依次投弹，爆炸连成笔直一线，黑烟，高空视角",
    ),
    dict(
        name="探测雷达", slug="tance-leida",
        motif="旋转的雷达波扫过 2×2 海格，四艘潜艇剪影在绿磷光下亮起",
        prompt="a rotating radar beam sweeping across a 2x2 patch of dark ocean, four "
               "hidden submarine silhouettes lighting up in green phosphor under the "
               "beam, technical sonar glow",
        zh="旋转雷达波扫过 2×2 海面，四艘隐藏潜艇在绿色磷光中显形，声纳科技感",
    ),
    dict(
        name="伊甸园", slug="yidianyuan",
        motif="镜面平海上浮着一座发光的乐园岛，一座黄铜摆锤随舰数下降而倾斜",
        prompt="a luminous paradise island garden floating over a mirror-calm sea, a "
               "giant brass pendulum counter dipping as warships fade into it, serene "
               "yet uncanny, soft greens and gold",
        zh="镜面般平静海面上悬浮发光天堂岛，黄铜摆锤随战舰消失而下降，宁静诡异",
    ),
    dict(
        name="神之宣告", slug="shenzhi-xuangao",
        motif="两艘己方战舰化作祭品升入神光，一只巨手指出两条分岔的光路",
        prompt="two allied warships dissolving as an offering into two beams of divine "
               "light, a colossal pointing hand above, the beams forking into two "
               "different outcomes, solemn judgment",
        zh="两艘友舰化为祭品升入神光，巨大手指向下，光柱分岔出两种结局，庄严裁决",
    ),
    dict(
        name="五险一金", slug="wuxian-yijin",
        motif="五枚发光护盾代币与一把金锁悬在未被触碰的棋盘上方，空弹匣重新装填",
        prompt="five glowing shield tokens and one golden key arranged above an "
               "untouched ocean grid, an unharmed fleet, an empty cannon magazine "
               "refilling with light, protective brass and teal tones",
        zh="五枚发光护盾代币与金锁悬于完好的海面网格上方，空弹匣重新填装光弹",
    ),
    dict(
        name="绝处逢生", slug="juechu-fengsheng",
        motif="一片沉船残骸之间唯一一艘孤舰升起，绯金胜利光轮破云",
        prompt="a single lone warship rising from a graveyard of dozens of sunken hulls, "
               "one survivor against the abyss, a triumphant crimson and gold halo "
               "breaking through, desperate last stand",
        zh="数十艘沉船残骸之间仅剩一艘孤舰升起，绯金胜利光轮穿透阴云，背水一战",
    ),
    dict(
        name="死者苏生", slug="sizhe-susheng",
        motif="沉船从海床重新抬升，幽蓝魂光重组断裂的船体，锁链崩断",
        prompt="a sunken warship lifting back up out of the seabed, ghostly blue "
               "soul-light reassembling its broken hull, binding chains snapping, "
               "ethereal resurrection glow",
        zh="沉船自海床缓缓抬升，幽蓝魂光重组断裂船体，束缚锁链崩断，亡者归来",
    ),
    dict(
        name="疗愈", slug="liaoyu",
        motif="两艘破裂的船体在原地愈合，暖金光线把撕裂的钢板缝回去，修复符文",
        prompt="two shattered hulls healing in place, warm golden light stitching torn "
               "steel back together, glowing repair runes on the water, gentle "
               "restorative glow, hope",
        zh="两艘残破战舰在原地愈合，暖金色光丝缝合钢板，水面浮起修复符文，治愈",
    ),
    dict(
        name="桃园结义", slug="taoyuan-jieyi",
        motif="桃花庭院悬于海上，两只手从缓慢旋转的空白卡扇中各取一张",
        prompt="a peach-blossom garden over calm water, two hands reaching into a slowly "
               "rotating fan of glowing blank cards, one card drawn to each side, "
               "oath-taking ceremony, warm pink and jade",
        zh="桃花庭院浮于平海之上，两只手从旋转的空白发光卡扇中各抽一张，结义",
    ),
    dict(
        name="无中生有", slug="wuzhongshengyou",
        motif="两张华丽卡牌从旋转的虚空中凝结成型，虚空在其后封上一道石门",
        prompt="two ornate cards condensing out of a swirling void in mid-air, the void "
               "sealing shut behind them with a heavy stone seal, cold silver light",
        zh="两张华丽卡牌从旋转虚空中凝结而成，虚空随后被沉重石门封死，冷银光",
    ),
    dict(
        name="饮血", slug="yinxue",
        motif="舰首刀刃从沉船中饮下猩红之光，抽出的能量在浪尖上凝成一张卡",
        prompt="a warship prow blade drinking crimson light from a sinking hull, the "
               "drained energy coalescing into a floating card above the waves, "
               "violent sanguine glow",
        zh="战舰舰首刀刃从沉船中吸取猩红之光，能量在浪尖凝聚成一张浮空卡牌",
    ),
    dict(
        name="极限增援", slug="jixian-zengyuan",
        motif="两座倒计时光柱夹住棋盘，天平向更残破、更少船的一方倾斜",
        prompt="two towering countdown pillars flanking an ocean grid, a scale tipping "
               "toward the smaller and more battered fleet, glowing numerals made of "
               "light, tense countdown",
        zh="两座巨大倒计时光柱夹着海面网格，天平向船更少更破的一方倾斜，光数字",
    ),
    dict(
        name="教皇旨意", slug="jiaohuang-zhiyi",
        motif="披礼袍的教皇剪影立于海上，炮管被清空，卡牌被弃置后如炮弹般掷出",
        prompt="a towering pontiff silhouette in ceremonial robes over the sea, floating "
               "cards being discarded and hurled like missiles from emptied cannon "
               "barrels, cathedral light, holy decree",
        zh="礼袍教皇剪影立于海面，空炮管掷出弃置的卡牌如导弹，教堂圣光，敕令",
    ),
    dict(
        name="无暇圣心", slug="wuxia-shengxin",
        motif="一枚无瑕的透明水晶之心悬在完全未受伤的海面上，无烟无残骸",
        prompt="an immaculate translucent crystal heart hovering over a completely "
               "untouched calm ocean, no smoke and no wreckage anywhere, pristine "
               "stillness, patient pale-gold glow",
        zh="无瑕透明水晶之心悬浮于毫无伤痕的平静海面上，无烟无残骸，纯净静穆",
    ),
    dict(
        name="盗亦有道", slug="daoyi-youdao",
        motif="戴手套的盗手从阴影里伸出，从对手牌架中抽走一张发光卡牌",
        prompt="a gloved thief's hand emerging from shadow, lifting a single glowing card "
               "out of an opponent's card rack, stealth and honor-among-thieves mood, "
               "dim amber spotlight",
        zh="戴手套的盗贼之手自阴影中伸出，从对手牌架抽走一张发光卡牌，暗金光",
    ),
    dict(
        name="克苏鲁之眼", slug="kesulu-zhiyan",
        motif="波浪下张开的巨型触手之眼，两艘战舰在诡异绿光中互相暴露位置",
        prompt="a colossal tentacled eye opening beneath the waves, two warship "
               "silhouettes illuminated in mutual eldritch green light, cosmic horror, "
               "swirling abyss",
        zh="海面下张开的巨眼与触手，两艘战舰在诡异绿光中同时暴露位置，克苏鲁",
    ),
    dict(
        name="Freezing！", slug="freezing",
        motif="一只冰之巨手捏碎悬浮的黄铜沙漏，对手的整个回合结晶成冰屑",
        prompt="a giant hand of ice crushing a floating brass hourglass, time itself "
               "freezing, an opponent's whole turn crystallizing into ice shards, "
               "brutal cold white",
        zh="冰之巨手捏碎悬浮黄铜沙漏，整个回合结晶碎裂为冰屑，酷寒骤然静止",
    ),
    dict(
        name="回光返照", slug="huiguang-fanzhao",
        motif="旧舰队化作最后一次光爆消散，六艘崭新战舰在同片海面成型，旧阵型裂成镜面碎片",
        prompt="an old fleet dissolving into a final flare of light while six pristine "
               "new warships materialize over the same waters, a cracked mirror image "
               "of the old formation, bittersweet golden blaze",
        zh="旧舰队化作最后光爆消散，六艘崭新战舰在同一海面成型，旧阵型如镜面碎裂",
    ),
    dict(
        name="明智埋葬", slug="mingzhi-maizang",
        motif="一把光铸之铲把一张发光卡牌压入海床下的黑暗坟坑，另一张新牌升起交换",
        prompt="a ceremonial spade of light pushing a single glowing card down into a "
               "dark burial pit in the seafloor, a fresh card rising in exchange, "
               "solemn funeral rites, cold teal and bone white",
        zh="光铸之铲将发光卡牌压入海床黑暗坟坑，一张新卡作为交换升起，冷青骨白",
    ),
    dict(
        name="火力全开", slug="huoli-quankai",
        motif="战舰全炮塔齐射，炮口焰重叠成一片，硝烟里浮出整支舰队的重影",
        prompt="a battleship broadside with every turret firing simultaneously, "
               "overlapping muzzle flashes, a doubled ghost image of the same fleet in "
               "the smoke, overwhelming firepower",
        zh="战舰全炮塔同时齐射，炮口焰层层重叠，硝烟中浮现整支舰队的重影，火力全开",
    ),
    dict(
        name="加百列之光", slug="jiabailie-zhiguang",
        motif="天使的号角喷出一道白金光柱，击碎一张黑卡并蒸散一层场地光环",
        prompt="an archangel's trumpet unleashing a pillar of blinding white-gold light, "
               "a dark card shattering and a field aura dissolving inside the beam, "
               "sacred judgment, cathedral of clouds",
        zh="天使号角喷出白金光柱，光柱内黑卡碎裂、场地光环消散，云中大教堂，圣裁",
    ),
    dict(
        name="仁王之盾", slug="renwang-zhidun",
        motif="三艘战舰被半透明六边形护盾环住，上方浮着柔和的光之王冠徽记",
        prompt="three warships encircled by translucent hexagonal energy shields, a "
               "gentle crowned emblem of light above them, shimmering protective "
               "barrier, calm blue-green glow",
        zh="三艘战舰被半透明六边形能量护盾环绕，上方悬浮光之王冠徽记，守护，平和",
    ),
    dict(
        name="钢筋铁骨", slug="gangjin-tiegu",
        motif="一艘战舰自毁崩解成发光钢肋骨架，骨架铺展覆盖全舰队，把每艘船包进铁光里",
        prompt="a single warship disintegrating into a lattice of glowing steel ribs that "
               "spreads over the whole fleet, armoring every hull in iron light, "
               "self-sacrifice, molten metal and cyan",
        zh="一艘战舰自毁为发光钢骨网格，网格铺满全舰队为每艘船披上铁光，自我牺牲",
    ),
    dict(
        name="神机妙算", slug="shenji-miaosuan",
        motif="发光算盘与围棋盘叠在海面网格上，幽灵标记预演损失，被预言的船即刻归位",
        prompt="a giant glowing abacus and a Go board overlaid on an ocean grid, ghost "
               "markers predicting losses, those exact ships snapping back into place, "
               "divination and foresight, precise golden geometry",
        zh="发光算盘与围棋盘叠加于海面网格，幽灵标记预演损失，被预言的舰船瞬间归位",
    ),
    dict(
        name="灵气复苏", slug="lingqi-fusu",
        motif="灵光潮水漫上海面，双方舰队同时增删到同一规模，舰船在灵液中凝成或溶解",
        prompt="a rising tide of luminous spirit aura flooding the sea, fleets on both "
               "sides reshaping to an equal size, ships condensing out of and "
               "dissolving into mana, equilibrium, jade green and silver",
        zh="灵光潮水漫过海面，双方舰队重塑为同等规模，舰船在灵液中凝结或溶解，均衡",
    ),
    dict(
        name="败者食尘", slug="baizhe-shichen",
        motif="巨型时钟指针倒转，整片战场海面重置回开局状态，双方手牌却依然发光未被触碰",
        prompt="an immense clock's hands spinning backwards, the entire battle sea "
               "resetting to its pristine opening state, both players' hands of cards "
               "left glowing and untouched, time reversal, dust and embers, pale blue",
        zh="巨钟指针倒转，整片战场重置回开局状态，双方手牌仍发光未被影响，时间倒流",
    ),
    # ---- 2026-09-28 补：上游合并带进来的 7 张卡（判定魔法卡 3 张 + 普通 4 张）。
    # 之前本脚本只覆盖 41 张，card_art_wiring_check 的「映射覆盖卡表里每一张唯一卡」
    # 当场红了 —— 卡表是 static/magic_card.json，这里少一条就是少一张底图。
    dict(
        name="命运骰子", slug="mingyun-shaizi",
        motif="一枚骨白色巨骰在半空翻滚，六个面各映出一种命运幻影，骰影投向海面",
        prompt="a colossal bone-white die tumbling in mid-air above dark water, each of "
               "its faces reflecting a different vision of fate, its long shadow falling "
               "across the waves",
        zh="半空翻滚的巨骰，六面各映出一种命运，骰影投向海面",
    ),
    dict(
        name="无忧梦呓", slug="wuyou-mengyi",
        motif="沉睡的水兵口中飘出半透明梦呓气泡，气泡里两口钟在隔空拼点",
        prompt="translucent dream bubbles drifting from the mouth of a sleeping sailor, "
               "two spectral bells clashing point against point inside them",
        zh="沉睡者吐出的梦呓气泡里，两口钟隔空拼点",
    ),
    dict(
        name="兵粮寸断", slug="bingliang-cunduan",
        motif="补给缆绳被斩断、粮袋翻落海面，断口处浮着三枚骰子等判定",
        prompt="a supply cable severed in mid-air over the sea, ration sacks spilling "
               "into the waves, three dice floating where the cut was made",
        zh="补给缆绳被斩断、粮袋落海，断口浮着三枚骰子待判定",
    ),
    dict(
        name="亡羊补牢", slug="wangyang-bulao",
        motif="破损的船坞栅栏正被补上木板，落潮里翻出的旧牌被一只手捞回",
        prompt="a breached harbor fence being patched with fresh planks, an old card "
               "surfacing from the ebb tide and lifted back by a hand",
        zh="补好船坞栅栏的同时，落潮里捞回一张旧牌",
    ),
    dict(
        name="守株待兔", slug="shouzhu-daitu",
        motif="自家战舰桅杆挂起伪装成礁石的陷阱网，水下伏着一排尖锐锚钩",
        prompt="a trap net disguised as a reef hanging from a warship's mast, a row of "
               "barbed anchors waiting below the waterline",
        zh="桅杆上挂着伪装成礁石的陷阱网，水下埋伏尖锐锚钩",
    ),
    dict(
        name="卧薪尝胆", slug="woxin-changdan",
        motif="残破舰队列成一线，船身裹着绷带般的护盾光膜，船艏抵着苦胆形铁砧",
        prompt="a battered fleet in line ahead, hulls wrapped in bandage-like shields of "
               "light, each bow resting against a bitter-gourd-shaped iron anvil",
        zh="残破舰队裹上绷带般的护盾光膜，船艏抵着苦胆铁砧",
    ),
    dict(
        name="滥竽充数", slug="lanyu-chongshu",
        motif="真舰之间插进几艘纸糊假船，海风把假船吹得鼓如竽，边角露出临时铆钉",
        prompt="a line of real warships interleaved with paper decoys, the fakes "
               "billowing like flutes in the sea wind, temporary rivets showing at "
               "their edges",
        zh="真舰之间插进纸糊假船，海风吹得鼓如竽，边角露出临时铆钉",
    ),
]

# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------


def load_deck():
    """"按 static/magic_card.json 得到去重后的卡表（顺序即 JSON 顺序）。"""
    with CARD_JSON.open(encoding="utf-8") as fh:
        deck = json.load(fh)
    unique = {}
    for card in deck:
        unique.setdefault(card["name"], card)
    return deck, unique


def check_coverage(unique):
    art_names = [c["name"] for c in CARD_ART]
    dupes = {n for n in art_names if art_names.count(n) > 1}
    missing = [n for n in unique if n not in set(art_names)]
    extra = [n for n in art_names if n not in unique]
    slugs = [c["slug"] for c in CARD_ART]
    slug_dupes = {s for s in slugs if slugs.count(s) > 1}
    problems = []
    if dupes:
        problems.append("CARD_ART 里有重复卡名：%s" % "、".join(sorted(dupes)))
    if missing:
        problems.append("卡表里有牌但 CARD_ART 缺条目：%s" % "、".join(missing))
    if extra:
        problems.append("CARD_ART 里有牌但卡表里没有：%s" % "、".join(extra))
    if slug_dupes:
        problems.append("文件名短名重复：%s" % "、".join(sorted(slug_dupes)))
    if problems:
        for line in problems:
            print("[x] " + line, file=sys.stderr)
        return False
    return True


def compose(card, art):
    speed = int(card["speed"])
    ctype = card["type"]
    body = "%s, %s, %s" % (
        art["prompt"],
        SPEED_ACCENT[speed],
        TYPE_COMPOSITION[ctype],
    )
    return "%s, %s, %s" % (STYLE_PREAMBLE, body, STYLE_SUFFIX)


def build_records(unique, raw_deck):
    records = []
    for art in CARD_ART:
        card = unique[art["name"]]
        records.append({
            "name": card["name"],
            "slug": art["slug"],
            "speed": int(card["speed"]),
            "type": card["type"],
            "copiesInDeck": sum(1 for c in raw_deck if c["name"] == card["name"]),
            "effect": card["description"],
            "motif": art["motif"],
            "promptKeywordsZh": art["zh"],
            "promptEn": compose(card, art),
            "promptBodyEn": art["prompt"],
            "negativePrompt": NEGATIVE_PROMPT,
            "outputFile": "static/cards/%s.webp" % art["slug"],
        })
    # 按「速阶 → 类型 → 卡名」排：同速阶的卡是同一套光效，挨着才能横向比对
    # （验收清单第 4 条要求把同速阶的图排开看色系是否统一）。
    records.sort(key=lambda r: (r["speed"], 0 if r["type"] == "普通" else 1, r["name"]))
    return records


def write_json(records):
    payload = {
        "note": "由 tools/gen_card_art_prompts.py 生成，勿手改；改提示词请改脚本再重跑",
        "style": {
            "preamble": STYLE_PREAMBLE,
            "suffix": STYLE_SUFFIX,
            "negative": NEGATIVE_PROMPT,
            "speedAccent": {str(k): v for k, v in SPEED_ACCENT.items()},
            "typeComposition": TYPE_COMPOSITION,
        },
        "spec": {
            "aspect": "2:3",
            "resolution": "1024x1536",
            "deliverFormat": "webp (回退 png)",
            "safeArea": {"top": 0.25, "bottom": 0.17, "middle": 0.58},
            "outputDir": "static/cards/",
        },
        "cards": records,
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def md_index(records):
    """按速阶/类型分组的名录，方便按卡名找编号。"""
    groups = [
        ("速阶 3（任何阶段可用）", lambda r: r["speed"] == 3 and r["type"] == "普通"),
        ("速阶 2（准备 + 战斗阶段）", lambda r: r["speed"] == 2 and r["type"] == "普通"),
        ("速阶 1（仅自己的准备阶段）", lambda r: r["speed"] == 1 and r["type"] == "普通"),
        ("场地卡", lambda r: r["type"] == "场地"),
    ]
    lines = ["| 分组 | 卡（编号） |", "| --- | --- |"]
    for label, pred in groups:
        names = ["`%02d` %s" % (i, r["name"])
                 for i, r in enumerate(records, 1) if pred(r)]
        lines.append("| %s | %s |" % (label, "、".join(names)))
    return "\n".join(lines)


def md_card_section(records):
    out = []
    for i, r in enumerate(records, 1):
        copies = "" if r["copiesInDeck"] == 1 else "（牌堆里 %d 张）" % r["copiesInDeck"]
        out.append("### %02d. %s · 速阶 %d · %s%s" % (
            i, r["name"], r["speed"], r["type"], copies))
        out.append("")
        out.append("- **画面**：%s" % r["motif"])
        out.append("- **英文提示词**：")
        out.append("")
        out.append("  ```text")
        out.append("  " + r["promptEn"])
        out.append("  ```")
        out.append("")
        out.append("- **中文关键词**：%s" % r["promptKeywordsZh"])
        out.append("- **落盘**：`%s`" % r["outputFile"])
        out.append("")
    return "\n".join(out)


MD_PROLOGUE = """# 魔法卡卡面美术提示词（{count} 张）

> 由 `tools/gen_card_art_prompts.py` 生成，**不要手改本文件**。
> 改提示词请改脚本里的 `STYLE_*` / `SPEED_ACCENT` / `TYPE_COMPOSITION` / `CARD_ART`，
> 然后重跑 `python tools/gen_card_art_prompts.py`。
> 卡名、速阶、类型、效果文本全部取自 `static/magic_card.json`，脚本会校验覆盖率，
> 卡表里出现新牌而这里没有条目时直接报错退出。

## 一、这份东西怎么用

给每张魔法卡生成一张竖版插画，作为卡面底图。**不生成文字、不生成卡框** ——
卡名 / 速阶 / 类型是 `static/game.js` 的 `updateHandUI()` 用 DOM 叠上去的
（`.card-name` / `.card-speed` / `.card-type`），美术层只负责背景，
所以任何模型画出来的字母、汉字、边框都是废笔，必须靠提示词和负面词压住。

## 二、统一风格块

{count} 张卡共用同一套风格，这是它们看起来像「一套牌」而不是「一堆图」的唯一原因。
每张卡的完整提示词已经按下面的公式拼好了，**直接整段复制即可**，
需要自己改的时候按这个公式拼：

```text
{{统一前缀}}, {{该卡画面主体}}, {{速阶光效}}, {{类型构图}}, {{统一后缀}}
```

**统一前缀**（所有卡一样）：

```text
{preamble}
```

**统一后缀**（所有卡一样，负责构图留白 + 禁止文字）：

```text
{suffix}
```

**负面提示词**（SD / ComfyUI 的 negative 字段，或 MJ 的 `--no`）：

```text
{negative}
```

## 三、画幅与落盘

| 项 | 值 | 依据 |
| --- | --- | --- |
| 比例 | 2:3 竖版 | `.magic-card` 基准尺寸 100×150（`static/style.css`） |
| 生成分辨率 | 1024×1536 | 缩到 46×62（`layout-dense`）仍要能认出主体，所以细节不能细 |
| 交付格式 | webp，质量 85（回退 png） | 41 张卡面，png 体积压不住 |
| 落盘目录 | `static/cards/<slug>.webp` | 与 `static/avatars/` 同级 |
| 文件名 | 见每张卡的「落盘」一行 | ASCII slug，避免中文文件名在不同系统上炸编码 |

**文字安全区**（很关键，模型很容易把主体画到标题带上）：

```text
┌──────────────────────┐
│   ① 标题带 25%        │  ← .card-name 会盖在这里，必须是暗部/空部
│──────────────────────│
│                      │
│   ② 视觉中心 58%      │  ← 主体只画在这一条里，居中，单一剪影
│                      │
│──────────────────────│
│   ③ 类型带 17%        │  ← .card-speed + .card-type 盖在这里，同样留暗
└──────────────────────┘
```

留白不能只靠模型自觉。可选的兜底是入库前压暗上下两条带，
但**这条路本机走不通**：`magick` 没装，项目 venv 里也没有 Pillow
（见 `requirements.txt`），为一步图像处理引依赖不划算。所以留白由两处兜底：

1. **提示词**（已经写进统一后缀）：`empty shadowed space at the top and bottom
   for text overlay` —— 模型自带暗角，多数情况下够用；
2. **接图时的 CSS 渐变**（下面这段只是给接图的人参考，本次不改 CSS）。
   两个坑：`background` 简写会把 `background-image` 重置成 `none`，所以
   `background-image` 必须写在 `background` **之后**；渐变比插画本身暗一档，
   不用统一压到纯黑，不然整套牌会发闷。

```css
/* 仅示意：加在 .magic-card 现有声明之后 */
.magic-card {{
    background-image:
        linear-gradient(180deg,
            rgba(5, 12, 24, 0.86) 0%,
            rgba(5, 12, 24, 0.24) 26%,
            rgba(5, 12, 24, 0.34) 72%,
            rgba(5, 12, 24, 0.88) 100%),
        var(--card-art);
    background-size: cover, cover;
    background-position: center, center;
}}
```

## 四、速阶与类型的视觉编码

**速阶 = 响应速度**（规则见 `static/game.js` 的 `canPlayMagicCard`：
速阶 1 只有自己准备阶段能用、速阶 2 准备+战斗、速阶 3 任何阶段都能用）。
美术上把它编码成「光的温度 + 动能」，玩家扫一眼就知道这张牌来不来得及用：

| 速阶 | 光效 | 感觉 |
| --- | --- | --- |
| 1 | {speed1} | 慢、仪式感、重型 |
| 2 | {speed2} | 中速、粒子悬浮 |
| 3 | {speed3} | 瞬发、高速、电弧拖影 |

**类型决定构图**：

| 类型 | 张数 | 构图 |
| --- | --- | --- |
| 普通 | {normal_count} | 单一明确主体，海面只作背景暗示 |
| 场地 | {field_count} | 广角地平线，环境光环占据整幅画面，不设小主体 |

场地卡是持续存在的环境（`恶魔契约`/`禁忌果实`/`伊甸园`/`教皇旨意`），
所以它们之间应当自成一组：同样偏广角地平线、同样的整幅环境光。

## 五、各生成器的收尾参数

| 生成器 | 追加 |
| --- | --- |
| Midjourney | `--ar 2:3 --style raw --stylize 150 --no text,letters,watermark,signature` |
| SD / ComfyUI | 832×1216 或 768×1152，CFG 6~7，步数 28~35，DPM++ 2M Karras，负面词填上面的 |
| 即梦 / 通义万相 / 豆包 | 直接用每张卡下面的「中文关键词」那一行，比例选 2:3 |
| GPT-Image / Nano Banana 类 | 整段英文提示词 + 追加 `Do not render any text or typography.` |

⚠️ 这几种模型里只有后两类默认会往图里塞字，前两类偶尔也会在招牌、船体舷号上
凭空造字。**每张成品都要过一遍第七节的验收清单**。

## 六、逐卡提示词

共 {count} 张。编号按「速阶 → 类型 → 卡名」排，**同速阶的卡挨在一起**，
方便横向比对同一组的光效是否统一；按卡名找编号看下面的名录。

{index}

{cards}
## 七、成品验收清单

每张图入库前过一遍，有一条不过就重生成：

1. **没有文字**：放大到 100% 扫一遍，船体舷号、招牌、旗帜、天空云形都不能出现可读字符。
2. **缩到 46×62 还能认**：这是 `layout-dense` 下的实际显示尺寸，认不出主体就重画。
3. **上下两条带是暗部**：标题带 25% / 类型带 17% 不能有高亮细节，白字压上去要能读。
4. **同速阶同色系**：把 41 张按速阶排开，1/2/3 三组应该一眼分得开，组内色调统一。
5. **四张场地卡自成一族**：都是广角地平线 + 整幅环境光，不出现小主体。
6. **主体居中**：x 方向居中、y 方向落在中间那 58% 里，不要贴边。
7. **不含 UI**：没有卡框、没有边框、没有四角装饰、没有进度条。

## 八、落盘之后

图放进 `static/cards/` 之后，前端要接的话是在 `.magic-card` 上加背景层
（`background-image` + 上层 `linear-gradient` 压暗），**不要**改
`.card-name` / `.card-speed` / `.card-type` 的 DOM 结构 ——
`tools/ui_layout_check.mjs` 和 `tests/test_mobile_adaptive_layout.py`
都依赖现在的卡面结构。这一步是独立改动，本次只交付提示词。
"""


def write_md(records):
    normal = sum(1 for r in records if r["type"] == "普通")
    field = sum(1 for r in records if r["type"] == "场地")
    md = MD_PROLOGUE.format(
        count=len(records),
        preamble=STYLE_PREAMBLE,
        suffix=STYLE_SUFFIX,
        negative=NEGATIVE_PROMPT,
        speed1=SPEED_ACCENT[1],
        speed2=SPEED_ACCENT[2],
        speed3=SPEED_ACCENT[3],
        normal_count=normal,
        field_count=field,
        index=md_index(records),
        cards=md_card_section(records),
    )
    OUT_MD.write_text(md, encoding="utf-8")


def write_art_map(records):
    """写 static/card_art_map.js —— 卡名 → 卡面文件路径（Phase 7 接图用）。

    为什么要脚本生成、而不是前端手写一份映射：
    卡表（static/magic_card.json）是唯一事实来源，手写的映射迟早会漏卡、会和卡表对不上；
    出图时只要把文件按 slug 放进 static/cards/，前端**不用改一行代码**就能接上。
    ⚠️ 前端只做「有就显示」：文件不存在时浏览器不画那一层，CSS 的渐变占位照旧
       （不写存在性检查，也就不需要额外请求去探测）。
    """
    lines = [
        "// 由 tools/gen_card_art_prompts.py 生成，勿手改；改卡表或提示词请改脚本再重跑。",
        "// 卡名 → 卡面图相对路径。出图后把文件按 slug 放进 static/cards/ 即生效；",
        "// 未出图的卡没有条目 → 前端退回 CSS 渐变占位（.card-art 的底层）。",
        "window.CARD_ART_MAP = {",
    ]
    # 最后一条**不留尾逗号**：合法 JS 但不合法 JSON，而检查工具要能直接 JSON.parse 这段
    entries = [
        "    %s: %s" % (json.dumps(r["name"], ensure_ascii=False),
                      json.dumps("cards/%s.webp" % r["slug"], ensure_ascii=False))
        for r in records
    ]
    lines.append(",\n".join(entries))
    lines.append("};")
    OUT_ART_MAP.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raw_deck, unique = load_deck()
    if not check_coverage(unique):
        sys.exit(1)
    recs = build_records(unique, raw_deck)
    write_json(recs)
    write_md(recs)
    write_art_map(recs)
    print("卡表 %d 张（去重后 %d 张），已生成：" % (len(raw_deck), len(unique)))
    print("  " + str(OUT_MD.relative_to(ROOT)))
    print("  " + str(OUT_JSON.relative_to(ROOT)))
    print("  " + str(OUT_ART_MAP.relative_to(ROOT)))
