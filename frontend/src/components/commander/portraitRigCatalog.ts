export type CommanderVariantId = 'base' | 'ascended' | 'alt' | 'ultimate'

export interface PortraitEyeRig {
  cx: number
  cy: number
  rx: number
  ry: number
  angle: number
}

export interface PortraitVisorRig {
  cx: number
  cy: number
  rx: number
  ry: number
}

export type PortraitThemeKind = 0 | 1 | 2 | 3

export interface PortraitRigSpec {
  commanderId: string
  variant: CommanderVariantId
  /** Face center + protection radii [cx, cy, rx, ry] */
  face: [number, number, number, number]
  /** Rigid head rotation pivot [cx, cy] */
  headPivot: [number, number]
  /** Chest breathing focus [cx, cy] */
  chest: [number, number]
  leftEye: PortraitEyeRig | null
  rightEye: PortraitEyeRig | null
  visor: PortraitVisorRig | null
  /** Prevailing wind direction vector (normalized) */
  windDir: [number, number]
  /** 0=chichao embers/fire-control, 1=qingtong sonar/ocean, 2=tieanchor storm/shield, 3=guihang stardust/astrolabe */
  themeId: PortraitThemeKind
  glowRgb: [number, number, number]
  rayRgb: [number, number, number]
  particleRgb: [number, number, number]
  lashRgb: [number, number, number]
  breathSpeed: number
  blinkPeriod: number
  /** Base motion gain calibrated to composition density */
  motionGain: number
}

export interface WallpaperRankProfile {
  variantRank: number
  effectiveRank: number
  /** Anatomical breathing, head tilt, hair wave & cloth sway gain */
  motionScale: number
  /** God rays, emissive pulse, thematic energy & particles gain */
  vfxScale: number
  /** 2.5D depth parallax range */
  parallaxScale: number
  /** Glow boost */
  bloomScale: number
}

function makeRig(
  commanderId: string,
  variant: CommanderVariantId,
  base: Omit<PortraitRigSpec, 'commanderId' | 'variant'>,
  override?: Partial<Omit<PortraitRigSpec, 'commanderId' | 'variant'>>,
): PortraitRigSpec {
  return {
    commanderId,
    variant,
    ...base,
    ...override,
  }
}

const CHICHAO_BASE: Omit<PortraitRigSpec, 'commanderId' | 'variant'> = {
  face: [0.53, 0.42, 0.16, 0.15],
  headPivot: [0.54, 0.57],
  chest: [0.55, 0.78],
  leftEye: null,
  rightEye: { cx: 0.615, cy: 0.395, rx: 0.044, ry: 0.019, angle: -0.08 },
  visor: { cx: 0.43, cy: 0.42, rx: 0.085, ry: 0.045 },
  windDir: [-0.88, -0.26],
  themeId: 0,
  glowRgb: [1.0, 0.38, 0.24],
  rayRgb: [1.0, 0.52, 0.32],
  particleRgb: [1.0, 0.68, 0.36],
  lashRgb: [0.16, 0.06, 0.08],
  breathSpeed: 1.12,
  blinkPeriod: 4.3,
  motionGain: 0.96,
}

const QINGTONG_BASE: Omit<PortraitRigSpec, 'commanderId' | 'variant'> = {
  face: [0.52, 0.33, 0.17, 0.15],
  headPivot: [0.5, 0.48],
  chest: [0.48, 0.76],
  leftEye: null,
  rightEye: { cx: 0.64, cy: 0.312, rx: 0.042, ry: 0.018, angle: -0.04 },
  visor: { cx: 0.45, cy: 0.305, rx: 0.075, ry: 0.048 },
  windDir: [0.82, -0.22],
  themeId: 1,
  glowRgb: [0.36, 0.85, 1.0],
  rayRgb: [0.55, 0.92, 1.0],
  particleRgb: [0.68, 0.95, 1.0],
  lashRgb: [0.09, 0.12, 0.2],
  breathSpeed: 1.02,
  blinkPeriod: 4.8,
  motionGain: 0.94,
}

const TIEANCHOR_BASE: Omit<PortraitRigSpec, 'commanderId' | 'variant'> = {
  face: [0.55, 0.31, 0.16, 0.15],
  headPivot: [0.54, 0.46],
  chest: [0.48, 0.72],
  leftEye: { cx: 0.545, cy: 0.285, rx: 0.036, ry: 0.015, angle: 0.08 },
  rightEye: { cx: 0.672, cy: 0.305, rx: 0.033, ry: 0.014, angle: -0.04 },
  visor: null,
  windDir: [-0.76, -0.3],
  themeId: 2,
  glowRgb: [0.38, 0.72, 1.0],
  rayRgb: [0.56, 0.82, 1.0],
  particleRgb: [0.76, 0.9, 1.0],
  lashRgb: [0.1, 0.11, 0.14],
  breathSpeed: 0.94,
  blinkPeriod: 5.2,
  motionGain: 0.9,
}

const GUIHANG_BASE: Omit<PortraitRigSpec, 'commanderId' | 'variant'> = {
  face: [0.52, 0.33, 0.16, 0.145],
  headPivot: [0.48, 0.48],
  chest: [0.45, 0.78],
  leftEye: { cx: 0.465, cy: 0.302, rx: 0.041, ry: 0.016, angle: 0.06 },
  rightEye: { cx: 0.618, cy: 0.332, rx: 0.038, ry: 0.016, angle: 0.08 },
  visor: null,
  windDir: [-0.9, -0.18],
  themeId: 3,
  glowRgb: [1.0, 0.82, 0.36],
  rayRgb: [1.0, 0.9, 0.56],
  particleRgb: [1.0, 0.94, 0.72],
  lashRgb: [0.22, 0.15, 0.1],
  breathSpeed: 1.06,
  blinkPeriod: 4.5,
  motionGain: 1.0,
}

const CATALOG: Record<string, PortraitRigSpec> = {
  'chichao:base': makeRig('chichao', 'base', CHICHAO_BASE),
  'chichao:ascended': makeRig('chichao', 'ascended', CHICHAO_BASE, { motionGain: 1.0 }),
  'chichao:alt': makeRig('chichao', 'alt', CHICHAO_BASE, {
    glowRgb: [1.0, 0.45, 0.25],
    motionGain: 1.02,
  }),
  'chichao:ultimate': makeRig('chichao', 'ultimate', CHICHAO_BASE, {
    face: [0.54, 0.675, 0.165, 0.16],
    headPivot: [0.53, 0.83],
    chest: [0.5, 0.92],
    rightEye: { cx: 0.618, cy: 0.635, rx: 0.044, ry: 0.019, angle: -0.08 },
    visor: { cx: 0.41, cy: 0.66, rx: 0.085, ry: 0.05 },
    motionGain: 1.04,
  }),

  'qingtong:base': makeRig('qingtong', 'base', QINGTONG_BASE),
  'qingtong:ascended': makeRig('qingtong', 'ascended', QINGTONG_BASE, { motionGain: 0.96 }),
  'qingtong:alt': makeRig('qingtong', 'alt', QINGTONG_BASE, {
    rayRgb: [0.68, 0.88, 1.0],
    motionGain: 1.0,
  }),
  'qingtong:ultimate': makeRig('qingtong', 'ultimate', QINGTONG_BASE, { motionGain: 1.02 }),

  'tieanchor:base': makeRig('tieanchor', 'base', TIEANCHOR_BASE),
  'tieanchor:ascended': makeRig('tieanchor', 'ascended', TIEANCHOR_BASE, { motionGain: 0.92 }),
  'tieanchor:alt': makeRig('tieanchor', 'alt', TIEANCHOR_BASE, {
    glowRgb: [0.56, 0.82, 1.0],
    motionGain: 0.94,
  }),
  'tieanchor:ultimate': makeRig('tieanchor', 'ultimate', TIEANCHOR_BASE, {
    glowRgb: [0.52, 0.88, 1.0],
    rayRgb: [0.72, 0.94, 1.0],
    motionGain: 0.96,
  }),

  'guihang:base': makeRig('guihang', 'base', GUIHANG_BASE),
  'guihang:ascended': makeRig('guihang', 'ascended', GUIHANG_BASE, { motionGain: 1.02 }),
  'guihang:alt': makeRig('guihang', 'alt', GUIHANG_BASE, {
    rayRgb: [0.98, 0.86, 0.55],
    motionGain: 1.04,
  }),
  'guihang:ultimate': makeRig('guihang', 'ultimate', GUIHANG_BASE, { motionGain: 1.06 }),
}

export function getPortraitRig(commanderId: string, variant: string): PortraitRigSpec {
  const safeId = commanderId in { chichao: 1, qingtong: 1, tieanchor: 1, guihang: 1 } ? commanderId : 'chichao'
  const safeVar: CommanderVariantId =
    variant === 'ascended' || variant === 'alt' || variant === 'ultimate' ? variant : 'base'
  return CATALOG[`${safeId}:${safeVar}`]
}

const VARIANT_ORDER: Record<CommanderVariantId, number> = {
  base: 0,
  ascended: 1,
  alt: 2,
  ultimate: 3,
}

export function resolveWallpaperRank(
  variant: CommanderVariantId,
  effectiveTier: number,
  mode: 'strip' | 'bust' | 'full',
): WallpaperRankProfile {
  const vRank = VARIANT_ORDER[variant] ?? 0
  const tierNorm = Math.max(0, Math.min(4, effectiveTier))
  // Blend variant identity with commander tier so base is already clearly alive
  // and each form/tier steps up visibly through ascended -> alt -> ultimate.
  const combined = Math.max(vRank * 1.15, vRank * 0.72 + tierNorm * 0.34)
  const effectiveRank = Math.max(0, Math.min(4, combined))

  const modeMotion = mode === 'strip' ? 0.74 : mode === 'bust' ? 0.92 : 1.0
  const modeVfx = mode === 'strip' ? 0.82 : mode === 'bust' ? 0.92 : 1.0
  const modeParallax = mode === 'strip' ? 0.7 : mode === 'bust' ? 0.88 : 1.0

  // Decouple calm physical poise (motionScale/parallaxScale) from escalating optical spectacle (vfxScale/bloomScale)
  const stepMotion = 0.85 + effectiveRank * 0.08
  const stepVfx = 0.55 + effectiveRank * 0.44
  const stepParallax = 0.75 + effectiveRank * 0.09
  const stepBloom = 0.45 + effectiveRank * 0.30

  return {
    variantRank: vRank,
    effectiveRank,
    motionScale: stepMotion * modeMotion,
    vfxScale: stepVfx * modeVfx,
    parallaxScale: stepParallax * modeParallax,
    bloomScale: stepBloom * modeVfx,
  }
}
