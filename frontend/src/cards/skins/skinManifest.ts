import shiling from '../../assets/skins/neon-shiling.webp'
import emoQiyue from '../../assets/skins/neon-emo-qiyue.webp'
import juechuFengsheng from '../../assets/skins/neon-juechu-fengsheng.webp'
import hongzha from '../../assets/skins/neon-hongzha.webp'
import kanpo from '../../assets/skins/neon-kanpo.webp'
import jixianZengyuan from '../../assets/skins/neon-jixian-zengyuan.webp'
import shenwei from '../../assets/skins/neon-shenwei.webp'
import mingyunShaizi from '../../assets/skins/neon-mingyun-shaizi.webp'
import jiabailieZhiguang from '../../assets/skins/neon-jiabailie-zhiguang.webp'
import jiaohuangZhiyi from '../../assets/skins/neon-jiaohuang-zhiyi.webp'
import huoliQuankai from '../../assets/skins/neon-huoli-quankai.webp'
import kesuluZhiyan from '../../assets/skins/neon-kesulu-zhiyan.webp'

export type SkinTier = 'legendary' | 'limited'

export interface SkinDefinition {
  readonly skinId: string
  /** 与 cardArt.ts 的既有 slug、CONTRACT v1.0 的 card_key 一致。 */
  readonly cardKey: string
  /** 后端卡牌身份，保留全角叹号。 */
  readonly cardName: string
  readonly tier: SkinTier
  readonly imageUrl: string
  /** 挂在公开卡面容器；不要挂在对手手牌背面。 */
  readonly effectClass: string
}

function skin(cardKey: string, cardName: string, tier: SkinTier, imageUrl: string): SkinDefinition {
  return Object.freeze({
    skinId: `neon-${cardKey}`, cardKey, cardName, tier, imageUrl,
    effectClass: `skin-neon skin-neon--${tier}`,
  })
}

/** 按 CONTRACT v1.0 的稳定 skin_id 索引；顺序同卡池服务端清单。 */
export const SKIN_MANIFEST = Object.freeze({
  'neon-shiling': skin('shiling', '失灵！', 'limited', shiling),
  'neon-emo-qiyue': skin('emo-qiyue', '恶魔契约', 'limited', emoQiyue),
  'neon-juechu-fengsheng': skin('juechu-fengsheng', '绝处逢生', 'limited', juechuFengsheng),
  'neon-hongzha': skin('hongzha', '轰炸', 'legendary', hongzha),
  'neon-kanpo': skin('kanpo', '看破！', 'legendary', kanpo),
  'neon-jixian-zengyuan': skin('jixian-zengyuan', '极限增援', 'legendary', jixianZengyuan),
  'neon-shenwei': skin('shenwei', '神威！', 'legendary', shenwei),
  'neon-mingyun-shaizi': skin('mingyun-shaizi', '命运骰子', 'legendary', mingyunShaizi),
  'neon-jiabailie-zhiguang': skin('jiabailie-zhiguang', '加百列之光', 'legendary', jiabailieZhiguang),
  'neon-jiaohuang-zhiyi': skin('jiaohuang-zhiyi', '教皇旨意', 'legendary', jiaohuangZhiyi),
  'neon-huoli-quankai': skin('huoli-quankai', '火力全开', 'legendary', huoliQuankai),
  'neon-kesulu-zhiyan': skin('kesulu-zhiyan', '克苏鲁之眼', 'legendary', kesuluZhiyan),
} satisfies Record<string, SkinDefinition>)

export type SkinId = keyof typeof SKIN_MANIFEST
export const SKINS: readonly SkinDefinition[] = Object.freeze(Object.values(SKIN_MANIFEST))

export function getSkin(skinId: string | null | undefined): SkinDefinition | undefined {
  if (!skinId || !Object.hasOwn(SKIN_MANIFEST, skinId)) return undefined
  return SKIN_MANIFEST[skinId as SkinId]
}

export function getSkinForCard(cardKey: string): SkinDefinition | undefined {
  return SKINS.find((entry) => entry.cardKey === cardKey)
}

export function skinArtUrl(skinId: string | null | undefined): string | null {
  return getSkin(skinId)?.imageUrl ?? null
}

/** 公开载荷只在皮肤与卡名匹配时替换；null 表示沿用现有默认卡面。 */
export function skinArtForCard(cardName: string, skinId: string | null | undefined): string | null {
  const entry = getSkin(skinId)
  return entry?.cardName === cardName ? entry.imageUrl : null
}
