/** 按实际牌意映射；Freezing 跳过回合与冻结区域、极限增援与召唤分别处理。 */
export const CARD_SOUNDS: Readonly<Record<string, string>> = {
  '失灵！': 'negate', '溅射': 'splash', '雷达子弹': 'electric',
  '越战越勇': 'steel_buff', '余音绕梁': 'steel_buff', '神威！': 'divine_banish',
  '增援': 'summon', '恶魔契约': 'dark_pact', '八方来财': 'card_transfer',
  '平等条约': 'holy_shield', '禁忌果实': 'dark_pact', '硫磺火焰': 'fire',
  '百亿补贴': 'steel_buff', '看破！': 'seal', '冻结': 'freeze',
  '轰炸': 'bombardment', '探测雷达': 'recon', '伊甸园': 'heal',
  '神之宣告': 'gabriel', '五险一金': 'steel_buff', '绝处逢生': 'resurrect',
  '死者苏生': 'resurrect', '疗愈': 'heal', '桃园结义': 'card_transfer',
  '无中生有': 'card_transfer', '饮血': 'dark_pact', '极限增援': 'time_warp',
  '教皇旨意': 'gabriel', '无暇圣心': 'holy_shield', '盗亦有道': 'card_transfer',
  '克苏鲁之眼': 'recon', 'Freezing！': 'time_warp', '回光返照': 'time_warp',
  '明智埋葬': 'discard', '火力全开': 'steel_buff', '加百列之光': 'gabriel',
  '仁王之盾': 'holy_shield', '钢筋铁骨': 'steel_buff', '神机妙算': 'summon',
  '灵气复苏': 'resurrect', '败者食尘': 'time_warp', '命运骰子': 'dice',
  '无忧梦呓': 'time_warp', '兵粮寸断': 'discard', '亡羊补牢': 'card_transfer',
  '守株待兔': 'steel_buff', '卧薪尝胆': 'holy_shield', '滥竽充数': 'summon',
}

export function cardSound(name: string): string | null {
  return Object.prototype.hasOwnProperty.call(CARD_SOUNDS, name) ? CARD_SOUNDS[name] : null
}
