import harborStandby from './tracks/harbor-standby.ogg?url'
import matchStandoff from './tracks/match-standoff.ogg?url'
import endgameTide from './tracks/endgame-tide.ogg?url'

/**
 * 已转好的 Ogg Opus。构建只做内容哈希，不再压缩。
 * 终局是叠在对局曲上的层，不是第三首替换曲。
 */
export const BGM_TRACK_URLS = {
  standby: harborStandby,
  match: matchStandoff,
  endgame: endgameTide,
} as const

export type BgmTrackName = keyof typeof BGM_TRACK_URLS
