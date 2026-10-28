import bombardment from './assets/bombardment.wav?url'
import gabriel from './assets/gabriel.wav?url'
import darkPact from './assets/dark_pact.wav?url'
import freeze from './assets/freeze.wav?url'
import divineBanish from './assets/divine_banish.wav?url'
import resurrect from './assets/resurrect.wav?url'
import heal from './assets/heal.wav?url'
import holyShield from './assets/holy_shield.wav?url'
import steelBuff from './assets/steel_buff.wav?url'
import recon from './assets/recon.wav?url'
import summon from './assets/summon.wav?url'
import cardTransfer from './assets/card_transfer.wav?url'
import draw from './assets/draw.wav?url'
import discard from './assets/discard.wav?url'
import timeWarp from './assets/time_warp.wav?url'
import dice from './assets/dice.wav?url'
import fire from './assets/fire.wav?url'
import electric from './assets/electric.wav?url'
import victory from './assets/victory.wav?url'
import defeat from './assets/defeat.wav?url'

/** 本地素材由 Vite 内容哈希打包，不依赖第三方音频服务。 */
export const SAMPLE_URLS: Record<string, string> = {
  bombardment, gabriel, dark_pact: darkPact, freeze, divine_banish: divineBanish,
  resurrect, heal, holy_shield: holyShield, steel_buff: steelBuff, recon, summon,
  card_transfer: cardTransfer, draw, discard, time_warp: timeWarp, dice, fire,
  electric, victory, defeat,
}

/** 相对混音：纸牌、治疗和探测轻一些，攻击与仪式保留落点。 */
export const SAMPLE_GAINS: Readonly<Record<string, number>> = {
  bombardment: 0.82, gabriel: 0.85, dark_pact: 0.82, freeze: 0.73,
  divine_banish: 0.83, resurrect: 0.8, heal: 0.52, holy_shield: 0.66,
  steel_buff: 0.75, recon: 0.48, summon: 0.74, card_transfer: 0.52,
  draw: 0.42, discard: 0.46, time_warp: 0.75, dice: 0.58,
  fire: 0.79, electric: 0.68, victory: 0.72, defeat: 0.65,
}
