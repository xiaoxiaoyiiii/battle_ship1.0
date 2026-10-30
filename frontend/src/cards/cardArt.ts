/**
 * Card-face art (ticket #33, moved in #30).
 *
 * The faces are the game's art, so they now live with the frontend:
 * `frontend/public/card_faces/<slug>.webp`. Vite still imports them at build
 * time through the glob below (content-hashed assets in `dist/assets`), which
 * keeps the SPA offline-capable and keeps the missing-face fallback honest:
 * a face that is not in the build resolves to `null` and the card renders
 * without an art layer. `build.copyPublicDir` is off, so the art is not copied
 * into `dist` a second time.
 *
 * The name -> slug table is the 48 unique card names of the frozen card pool.
 * The browser gate asserts coverage, so a missing entry fails loudly instead
 * of silently rendering a blank card.
 */

const ART_MODULES = import.meta.glob('/public/card_faces/*.webp', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

const CARD_ART_SLUGS: Record<string, string> = {
  '亡羊补牢': 'wangyang-bulao',
  '仁王之盾': 'renwang-zhidun',
  '余音绕梁': 'yuyin-raoliang',
  '卧薪尝胆': 'woxin-changdan',
  '回光返照': 'huiguang-fanzhao',
  '守株待兔': 'shouzhu-daitu',
  '无中生有': 'wuzhongshengyou',
  '无暇圣心': 'wuxia-shengxin',
  '极限增援': 'jixian-zengyuan',
  '桃园结义': 'taoyuan-jieyi',
  '火力全开': 'huoli-quankai',
  '灵气复苏': 'lingqi-fusu',
  '败者食尘': 'baizhe-shichen',
  '伊甸园': 'yidianyuan',
  '兵粮寸断': 'bingliang-cunduan',
  '命运骰子': 'mingyun-shaizi',
  '教皇旨意': 'jiaohuang-zhiyi',
  '无忧梦呓': 'wuyou-mengyi',
  '禁忌果实': 'jinji-guoshi',
  'Freezing！': 'freezing',
  '五险一金': 'wuxian-yijin',
  '克苏鲁之眼': 'kesulu-zhiyan',
  '冻结': 'dongjie',
  '探测雷达': 'tance-leida',
  '明智埋葬': 'mingzhi-maizang',
  '溅射': 'jianshe',
  '看破！': 'kanpo',
  '硫磺火焰': 'liuhuang-huoyan',
  '神威！': 'shenwei',
  '越战越勇': 'yuezhan-yueyong',
  '轰炸': 'hongzha',
  '雷达子弹': 'leida-zidan',
  '饮血': 'yinxue',
  '恶魔契约': 'emo-qiyue',
  '八方来财': 'bafang-laicai',
  '加百列之光': 'jiabailie-zhiguang',
  '增援': 'zengyuan',
  '失灵！': 'shiling',
  '平等条约': 'pingdeng-tiaoyue',
  '死者苏生': 'sizhe-susheng',
  '滥竽充数': 'lanyu-chongshu',
  '疗愈': 'liaoyu',
  '百亿补贴': 'baiyi-butie',
  '盗亦有道': 'daoyi-youdao',
  '神之宣告': 'shenzhi-xuangao',
  '神机妙算': 'shenji-miaosuan',
  '绝处逢生': 'juechu-fengsheng',
  '钢筋铁骨': 'gangjin-tiegu',
}

export const CARD_ART_NAMES: readonly string[] = Object.keys(CARD_ART_SLUGS)

function moduleKey(slug: string): string {
  return '/public/card_faces/' + slug + '.webp'
}

/** Bundled URL for one card name, or null when the card has no face entry. */
export function cardArtUrl(name: string): string | null {
  const slug = CARD_ART_SLUGS[name]
  if (!slug) return null
  return ART_MODULES[moduleKey(slug)] ?? null
}

/** Card names the build knows about but whose webp did not make it into the bundle. */
export function missingCardArt(): string[] {
  return CARD_ART_NAMES.filter((name) => cardArtUrl(name) === null)
}

export const CARD_ART_COUNT = CARD_ART_NAMES.length