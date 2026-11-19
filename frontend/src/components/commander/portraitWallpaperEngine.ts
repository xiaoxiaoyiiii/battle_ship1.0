import { getPortraitRig, type PortraitRigSpec } from './portraitRigCatalog'

export interface WallpaperStageParams {
  commanderId: string
  variant: string
  faceFocusX: number
  faceFocusY: number
  motionScale: number
  vfxScale: number
  parallaxScale: number
  bloomScale: number
  active: boolean
  muted: boolean
}

export interface WallpaperStageHandle {
  update(params: WallpaperStageParams): void
  setPointer(nx: number, ny: number, hovered: boolean): void
  setVisible(visible: boolean): void
  resize(cssWidth: number, cssHeight: number, dpr: number): void
  dispose(): void
}

export interface WallpaperStats {
  supported: boolean
  contextCount: number
  activeStages: number
  visibleStages: number
  texturesReady: number
  frameCount: number
}

interface TextureRecord {
  url: string
  tex: WebGLTexture | null
  ready: boolean
  loading: boolean
}

interface StageInstance {
  id: number
  canvas: HTMLCanvasElement
  ctx2d: CanvasRenderingContext2D | null
  params: WallpaperStageParams
  rigSpec: PortraitRigSpec
  visible: boolean
  drawnOnce: boolean
  onFirstFrame?: () => void
  width: number
  height: number
  targetPx: number
  targetPy: number
  curPx: number
  curPy: number
  hovered: boolean
  hoverMix: number
  phaseOffset: number
}

const VERT_SRC = `
attribute vec2 aPos;
varying vec2 vScreenUv;
void main() {
  gl_Position = vec4(aPos, 0.0, 1.0);
  vScreenUv = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5);
}
`

const FRAG_SRC = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif

varying vec2 vScreenUv;

uniform sampler2D uArtTex;
uniform sampler2D uRigTex;

uniform float uTime;
uniform vec2 uDstSize;
uniform vec2 uFocus;
uniform vec2 uPointer;
uniform float uHoverMix;

uniform float uMotionScale;
uniform float uVfxScale;
uniform float uParallaxScale;
uniform float uBloomScale;
uniform float uMuted;

uniform vec4 uFace;
uniform vec2 uHeadPivot;
uniform vec2 uChest;
uniform vec4 uLeftEye;
uniform vec4 uRightEye;
uniform vec2 uEyeAngles;
uniform vec4 uVisor;
uniform vec2 uWindDir;

uniform float uThemeId;
uniform vec3 uGlowRgb;
uniform vec3 uRayRgb;
uniform vec3 uParticleRgb;
uniform vec3 uLashRgb;
uniform float uBreathSpeed;
uniform float uBlinkPeriod;
uniform float uMotionGain;

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

mat2 rot2(float a) {
  float c = cos(a);
  float s = sin(a);
  return mat2(c, -s, s, c);
}

vec2 objectCoverUv(vec2 screenUv) {
  float dstAspect = max(0.1, uDstSize.x / max(1.0, uDstSize.y));
  float srcAspect = 0.75;
  vec2 vis = dstAspect > srcAspect
    ? vec2(1.0, srcAspect / dstAspect)
    : vec2(dstAspect / srcAspect, 1.0);
  vec2 off = (1.0 - vis) * uFocus;
  vec2 rawUv = off + screenUv * vis;
  vec2 anchor = clamp(uFocus, vec2(0.18), vec2(0.82));
  // Subtle overscan (4.5%) so depth parallax & wind waves never hit border clamping.
  return anchor + (rawUv - anchor) * 0.955;
}

void sampleRigMaps(vec2 uv, out vec3 rigL, out vec3 rigR) {
  vec2 c = clamp(uv, vec2(0.002), vec2(0.998));
  float uL = 0.002083 + c.x * 0.495834;
  float uR = 0.502083 + c.x * 0.495834;
  rigL = texture2D(uRigTex, vec2(uL, c.y)).rgb;
  rigR = texture2D(uRigTex, vec2(uR, c.y)).rgb;
}

float blinkEnvelope(float t, float period) {
  float cyc = floor(t / period);
  float ph = mod(t, period);
  float b1 = smoothstep(0.0, 0.07, ph) * (1.0 - smoothstep(0.07, 0.17, ph));
  float dbl = step(0.58, hash12(vec2(cyc, 7.13)));
  float b2 = dbl * smoothstep(0.24, 0.30, ph) * (1.0 - smoothstep(0.30, 0.39, ph));
  return clamp(b1 + b2, 0.0, 1.0);
}

void applyEyeRig(
  vec4 eye,
  float angle,
  float blink,
  inout vec2 texUv,
  out float lashWeight,
  out float irisSparkle
) {
  lashWeight = 0.0;
  irisSparkle = 0.0;
  if (eye.z <= 0.001 || eye.w <= 0.001) return;
  vec2 d = texUv - eye.xy;
  vec2 p = rot2(-angle) * vec2(d.x * 0.75, d.y);
  vec2 e = p / vec2(eye.z * 0.75, eye.w);
  float r = length(e);
  if (r > 1.45) return;

  float zone = smoothstep(1.35, 0.25, r);
  float lidBias = smoothstep(0.65, -0.75, e.y);
  texUv.y -= blink * zone * lidBias * eye.w * 0.78;

  // Curved dark eyelash crease traveling down when blinking
  float lidArcY = -0.35 + blink * 0.85 - 0.18 * (e.x * e.x);
  float crease = exp(-pow((e.y - lidArcY) * 4.2, 2.0)) * smoothstep(1.08, 0.35, abs(e.x));
  lashWeight = clamp(crease * blink * 0.85, 0.0, 0.85);

  // Living iris catchlight that glints subtly with idle motion & pointer angle
  vec2 glintPos = vec2(-0.22 + uPointer.x * 0.16, -0.25 + uPointer.y * 0.12);
  float glintDist = length(e - glintPos);
  float glintPulse = 0.75 + 0.25 * sin(uTime * 2.4 + eye.x * 9.0);
  irisSparkle = smoothstep(0.55, 0.05, glintDist) * (1.0 - blink) * glintPulse * 0.22;
}

float fourPointStar(vec2 p, float size) {
  vec2 q = abs(p) / max(1e-4, size);
  float diag = max(q.x * 0.22 + q.y, q.y * 0.22 + q.x);
  float core = smoothstep(1.0, 0.15, length(q) * 1.4);
  float spikes = smoothstep(1.0, 0.08, diag);
  return clamp(core * 0.6 + spikes * 0.85, 0.0, 1.0);
}

void main() {
  vec2 baseUv = objectCoverUv(vScreenUv);
  float mScale = uMotionScale * uMotionGain;
  float vScale = uVfxScale;

  // Gentle organic idle camera float blended with spring-damped mouse 2.5D parallax
  vec2 idleCam = vec2(
    sin(uTime * 0.48) * 0.32 + sin(uTime * 0.91 + 1.4) * 0.12,
    cos(uTime * 0.39 + 0.7) * 0.26
  );
  vec2 camInput = uPointer * (0.85 + 0.35 * uHoverMix) + idleCam * (0.42 - 0.12 * uHoverMix);
  float pxStrength = 0.0145 * uParallaxScale;

  // Coarse rig sample for 4-step depth parallax (zero seam tearing)
  vec3 rigL0, rigR0;
  sampleRigMaps(baseUv, rigL0, rigR0);
  float roughDepth = rigL0.r;
  vec2 step1Uv = baseUv - camInput * ((roughDepth - 0.52) * pxStrength * 0.45);
  vec3 rigL1, rigR1;
  sampleRigMaps(step1Uv, rigL1, rigR1);
  float dSample = mix(roughDepth, rigL1.r, 0.65);

  vec2 charUv = baseUv - camInput * ((dSample - 0.52) * pxStrength);
  vec3 rigL, rigR;
  sampleRigMaps(charUv, rigL, rigR);

  float depthVal = rigL.r;
  float hairMask = rigL.g;
  float clothMask = rigL.b;
  float glowMask = rigR.r;
  float waterMask = rigR.g;
  float headMask = rigR.b;

  // Face protection ellipse in character UV space
  vec2 fNorm = (charUv - uFace.xy) / max(vec2(0.01), uFace.zw);
  float faceProtect = smoothstep(1.12, 0.62, length(fNorm));

  // Anatomical breathing + delayed rigid head micro-tilt/bob
  float breathPhase = uTime * uBreathSpeed;
  float breath = sin(breathPhase) * 0.5 + 0.5 * sin(breathPhase * 0.5 + 0.4);
  float headLag = sin(breathPhase - 0.65);

  vec2 chestVec = charUv - uChest;
  float torsoZone = smoothstep(0.45, 0.04, length(vec2(chestVec.x * 0.75, chestVec.y * 0.92)));
  vec2 breathShift = vec2(
    -chestVec.x * breath * 0.0085 * torsoZone,
    +(0.0075 * breath * torsoZone)
  ) * mScale;

  vec2 headVec = charUv - uHeadPivot;
  float tiltAngle = (headLag * 0.011 + camInput.x * 0.008 * uParallaxScale) * mScale * headMask;
  vec2 headRot = (rot2(-tiltAngle) * headVec - headVec);
  vec2 headShift = (headRot + vec2(0.0, +headLag * 0.0042 * mScale * headMask));

  // Inverse warp into character texture space (so eyes track rigid head motion!)
  vec2 texUv = charUv + breathShift + headShift;

  // Multi-octave directional wind flow for flowing hair, ribbons, capes & floating gear
  float waveGuard = (1.0 - faceProtect);
  vec2 wDir = normalize(uWindDir);
  vec2 wPerp = vec2(-wDir.y, wDir.x);
  float projAlong = dot(texUv - uHeadPivot, wDir);
  float projCross = dot(texUv - uHeadPivot, wPerp);

  float w1 = sin(projAlong * 17.5 - uTime * 2.55 + projCross * 5.0);
  float w2 = sin(projAlong * 31.0 - uTime * 3.85 - projCross * 8.5 + 1.2);
  float hairDisp = (w1 * 0.68 + w2 * 0.32) * hairMask * waveGuard * 0.0125 * mScale;
  float hoverGust = (0.0028 * uHoverMix * sin(uTime * 3.2 - projAlong * 12.0)) * hairMask * waveGuard;
  texUv -= (wDir * (hairDisp * 0.55 + hoverGust) + wPerp * (hairDisp * 0.85));

  float c1 = sin(texUv.y * 12.5 - uTime * 1.95 + texUv.x * 5.5);
  float c2 = cos(texUv.x * 16.0 - uTime * 2.45 + texUv.y * 7.0);
  vec2 clothDelta = vec2(c1 * 0.75 + c2 * 0.35, c2 * 0.85) * clothMask * waveGuard * 0.0092 * mScale;
  texUv -= clothDelta;

  // Dedicated sea horizon capillary ripple (horizontal shimmer + slight vertical reflection sway)
  float seaWave1 = sin(texUv.y * 62.0 - uTime * 3.1 + texUv.x * 18.0);
  float seaWave2 = cos(texUv.x * 38.0 + uTime * 2.2 - texUv.y * 24.0);
  texUv -= vec2(seaWave1 * 0.0068, seaWave2 * 0.0024) * waterMask * (0.72 + 0.28 * mScale);

  // Natural irregular blinking & iris sparkle
  float blink = blinkEnvelope(uTime + uChest.x * 1.7, uBlinkPeriod) * (0.88 + 0.12 * clamp(mScale, 0.5, 1.5));
  float lashL = 0.0;
  float sparkL = 0.0;
  float lashR = 0.0;
  float sparkR = 0.0;
  applyEyeRig(uLeftEye, uEyeAngles.x, blink, texUv, lashL, sparkL);
  applyEyeRig(uRightEye, uEyeAngles.y, blink, texUv, lashR, sparkR);

  vec2 clampedTexUv = clamp(texUv, vec2(0.002), vec2(0.998));
  vec3 col = texture2D(uArtTex, clampedTexUv).rgb;

  // Blend eyelid crease & iris highlight
  float lashTotal = clamp(lashL + lashR, 0.0, 0.9);
  col = mix(col, uLashRgb, lashTotal);
  col += vec3(1.0, 0.97, 0.92) * clamp(sparkL + sparkR, 0.0, 0.28);

  // Subtle sea water caustic sparkle on ocean horizon pixels
  if (waterMask > 0.04) {
    float seaGlint = pow(max(0.0, sin(clampedTexUv.x * 52.0 + uTime * 2.8 + sin(clampedTexUv.y * 90.0 - uTime * 2.2))), 6.0);
    col += mix(uGlowRgb, vec3(0.92, 0.97, 1.0), 0.55) * waterMask * seaGlint * (0.14 + 0.14 * vScale);
  }

  // Tactical visor optical scanline & hover sheen (ChiChao red visor, QingTong cyan monocle)
  if (uVisor.z > 0.001) {
    vec2 vDist = (clampedTexUv - uVisor.xy) / vec2(uVisor.z, uVisor.w);
    float visorZone = smoothstep(1.15, 0.25, length(vDist));
    float scanY = fract(vDist.y * 0.5 - uTime * 0.65);
    float scanLine = exp(-pow((scanY - 0.5) * 9.0, 2.0));
    float sheen = exp(-pow((vDist.x - sin(uTime * 1.1) * 0.6 - uPointer.x * 0.4) * 2.5, 2.0));
    col += uGlowRgb * visorZone * (0.08 + 0.22 * scanLine + 0.14 * sheen) * (0.55 + 0.35 * vScale);
  }

  // Dynamic emissive breathing glow & soft interactive rim
  float pulse = 0.65 + 0.35 * sin(uTime * 2.35 + clampedTexUv.y * 3.0);
  float glowBoost = glowMask * pulse * (0.18 + 0.24 * uBloomScale + 0.14 * uHoverMix);
  col += uGlowRgb * glowBoost * 0.72;
  col += col * glowMask * pulse * 0.18 * uBloomScale;

  // Volumetric diagonal God Rays sweeping upper frame
  vec2 rayUv = vScreenUv - camInput * 0.025;
  float rayCoord = rayUv.x * 0.78 + rayUv.y * 0.48;
  float rayA = pow(max(0.0, sin(rayCoord * 7.5 - uTime * 0.42)), 3.0);
  float rayB = pow(max(0.0, sin(rayCoord * 13.0 + uTime * 0.28 + 1.7)), 4.0);
  float upperFade = smoothstep(0.95, 0.04, vScreenUv.y) * smoothstep(-0.1, 0.85, 1.0 - abs(vScreenUv.x - 0.5));
  float bgBias = mix(1.0, 0.35, depthVal);
  col += uRayRgb * (rayA * 0.65 + rayB * 0.45) * upperFade * bgBias * (0.065 + 0.085 * vScale);

  // Theme-specific gorgeous ambient effects + dual-depth parallax particles
  if (uThemeId < 0.5) {
    // 0: ChiChao — Warm fire-control ember sparks rising across sunset horizon
    for (int i = 0; i < 12; i++) {
      float fi = float(i);
      float layerD = mix(0.25, 1.15, hash12(vec2(fi, 2.1)));
      float spd = mix(0.11, 0.28, hash12(vec2(fi, 4.7)));
      float rx = hash12(vec2(fi, 8.3));
      float ry = hash12(vec2(fi, 11.9));
      float life = fract(ry - uTime * spd);
      float sway = sin(uTime * 2.1 + fi * 1.9 + life * 6.28) * 0.045;
      vec2 p = vec2(fract(rx + sway - uTime * 0.03 * layerD), life);
      p -= camInput * (layerD * 0.032 * uParallaxScale);
      vec2 d = (vScreenUv - p) * vec2(max(0.25, uDstSize.x / max(1.0, uDstSize.y)), 1.0);
      float sz = mix(0.008, 0.022, layerD) * (0.75 + 0.25 * vScale);
      float ember = exp(-dot(d, d) / (sz * sz));
      float fadeEnv = sin(life * 3.1415926);
      col += mix(uGlowRgb, uParticleRgb, hash12(vec2(fi, 5.5))) * ember * fadeEnv * (0.28 + 0.36 * vScale) * layerD;
    }
  } else if (uThemeId < 1.5) {
    // 1: QingTong — Expanding sonar pulse + rising cyan acoustic motes
    vec2 center = vec2(0.46, 0.35) - camInput * 0.018 * uParallaxScale;
    vec2 sc = (vScreenUv - center) * vec2(max(0.25, uDstSize.x / max(1.0, uDstSize.y)), 1.0);
    float dist = length(sc);
    float ping = fract(uTime * 0.26);
    float ring = exp(-pow((dist - ping * 0.85) * 28.0, 2.0)) * (1.0 - ping) * (0.4 + 0.6 * bgBias);
    col += uGlowRgb * ring * (0.14 + 0.22 * vScale);
    for (int i = 0; i < 10; i++) {
      float fi = float(i);
      float layerD = mix(0.3, 1.1, hash12(vec2(fi, 3.2)));
      float spd = mix(0.07, 0.18, hash12(vec2(fi, 6.4)));
      float rx = hash12(vec2(fi, 9.1));
      float ry = hash12(vec2(fi, 14.3));
      float life = fract(ry - uTime * spd);
      vec2 p = vec2(fract(rx + sin(uTime * 1.4 + fi) * 0.03), life) - camInput * (layerD * 0.028 * uParallaxScale);
      vec2 d = (vScreenUv - p) * vec2(max(0.25, uDstSize.x / max(1.0, uDstSize.y)), 1.0);
      float sz = mix(0.010, 0.024, layerD);
      float orb = smoothstep(sz, 0.0, length(d));
      col += uParticleRgb * orb * sin(life * 3.1415926) * (0.22 + 0.30 * vScale) * layerD;
    }
  } else if (uThemeId < 2.5) {
    // 2: TieAnchor — Storm rain streaks + sea mist + intermittent shield arc flash
    float stormFlash = pow(max(0.0, sin(uTime * 1.35 + sin(uTime * 3.7))), 14.0);
    col += uGlowRgb * glowMask * stormFlash * 0.42 * vScale;
    float mist = (0.5 + 0.5 * sin(vScreenUv.x * 5.0 - uTime * 0.55 + sin(vScreenUv.y * 4.0))) * smoothstep(0.35, 1.0, vScreenUv.y);
    col += uParticleRgb * mist * 0.085 * vScale;
    for (int i = 0; i < 12; i++) {
      float fi = float(i);
      float layerD = mix(0.35, 1.05, hash12(vec2(fi, 1.7)));
      float spd = mix(0.55, 0.95, hash12(vec2(fi, 5.1)));
      float life = fract(hash12(vec2(fi, 9.7)) + uTime * spd);
      float px = fract(hash12(vec2(fi, 13.4)) - life * 0.16);
      vec2 p = vec2(px, life) - camInput * (layerD * 0.026 * uParallaxScale);
      vec2 d = (vScreenUv - p) * vec2(max(0.25, uDstSize.x / max(1.0, uDstSize.y)), 1.0);
      vec2 dr = rot2(0.18) * d;
      float streak = exp(-pow(dr.x * 160.0, 2.0)) * exp(-pow(dr.y * 18.0, 2.0));
      col += uParticleRgb * streak * (0.18 + 0.22 * vScale) * layerD;
    }
  } else {
    // 3: GuiHang — Golden stardust bokeh & twinkling 4-point celestial stars
    for (int i = 0; i < 12; i++) {
      float fi = float(i);
      float layerD = mix(0.3, 1.15, hash12(vec2(fi, 2.8)));
      float spd = mix(0.06, 0.16, hash12(vec2(fi, 6.2)));
      float life = fract(hash12(vec2(fi, 10.5)) - uTime * spd);
      float px = fract(hash12(vec2(fi, 15.1)) + sin(uTime * 1.1 + fi * 1.7) * 0.035);
      vec2 p = vec2(px, life) - camInput * (layerD * 0.030 * uParallaxScale);
      vec2 d = (vScreenUv - p) * vec2(max(0.25, uDstSize.x / max(1.0, uDstSize.y)), 1.0);
      float twinkle = 0.55 + 0.45 * sin(uTime * 3.4 + fi * 2.3);
      float fadeEnv = sin(life * 3.1415926) * twinkle;
      float shape = i < 6 ? fourPointStar(d, 0.022 * layerD) : smoothstep(0.024 * layerD, 0.004, length(d));
      col += mix(uGlowRgb, uParticleRgb, 0.55) * shape * fadeEnv * (0.28 + 0.34 * vScale) * layerD;
    }
  }

  // Subtle tier edge aura on active portraits + locked muting
  if (uMuted > 0.5) {
    float g = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(g), 0.34) * 0.84;
  }

  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
`

interface GlPool {
  canvas: HTMLCanvasElement
  gl: WebGLRenderingContext
  program: WebGLProgram
  textures: Map<string, TextureRecord>
  uniforms: Record<string, WebGLUniformLocation | null>
  lost: boolean
}

let pool: GlPool | null = null
let glUnsupported = false
let nextInstanceId = 1
const instances = new Map<number, StageInstance>()
let rafId = 0
let lastTickMs = 0
let frameCount = 0
let lifecycleBound = false

function updateDebugStats(): void {
  if (typeof window === 'undefined') return
  let visibleStages = 0
  for (const inst of instances.values()) {
    if (inst.visible && inst.width > 0 && inst.height > 0) visibleStages += 1
  }
  let texturesReady = 0
  if (pool) {
    for (const rec of pool.textures.values()) {
      if (rec.ready) texturesReady += 1
    }
  }
  const w = window as unknown as { __cmdWallpaperStats?: WallpaperStats }
  w.__cmdWallpaperStats = {
    supported: isWallpaperSupported(),
    contextCount: pool && !pool.lost ? 1 : 0,
    activeStages: instances.size,
    visibleStages,
    texturesReady,
    frameCount,
  }
}

function compileShader(gl: WebGLRenderingContext, type: number, src: string): WebGLShader | null {
  const sh = gl.createShader(type)
  if (!sh) return null
  gl.shaderSource(sh, src)
  gl.compileShader(sh)
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    gl.deleteShader(sh)
    return null
  }
  return sh
}

function ensurePool(): GlPool | null {
  if (glUnsupported) return null
  if (pool && !pool.lost) return pool
  if (typeof document === 'undefined') return null

  const canvas = document.createElement('canvas')
  canvas.width = 480
  canvas.height = 640
  const opts: WebGLContextAttributes = {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    preserveDrawingBuffer: false,
    powerPreference: 'high-performance',
  }
  const gl =
    (canvas.getContext('webgl', opts) as WebGLRenderingContext | null) ||
    (canvas.getContext('experimental-webgl', opts) as WebGLRenderingContext | null)
  if (!gl) {
    glUnsupported = true
    return null
  }

  const vs = compileShader(gl, gl.VERTEX_SHADER, VERT_SRC)
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAG_SRC)
  if (!vs || !fs) {
    glUnsupported = true
    return null
  }
  const program = gl.createProgram()
  if (!program) {
    glUnsupported = true
    return null
  }
  gl.attachShader(program, vs)
  gl.attachShader(program, fs)
  gl.linkProgram(program)
  gl.deleteShader(vs)
  gl.deleteShader(fs)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program)
    glUnsupported = true
    return null
  }

  const buf = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, buf)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
  const loc = gl.getAttribLocation(program, 'aPos')
  gl.enableVertexAttribArray(loc)
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, 0)

  const uniformNames = [
    'uArtTex',
    'uRigTex',
    'uTime',
    'uDstSize',
    'uFocus',
    'uPointer',
    'uHoverMix',
    'uMotionScale',
    'uVfxScale',
    'uParallaxScale',
    'uBloomScale',
    'uMuted',
    'uFace',
    'uHeadPivot',
    'uChest',
    'uLeftEye',
    'uRightEye',
    'uEyeAngles',
    'uVisor',
    'uWindDir',
    'uThemeId',
    'uGlowRgb',
    'uRayRgb',
    'uParticleRgb',
    'uLashRgb',
    'uBreathSpeed',
    'uBlinkPeriod',
    'uMotionGain',
  ]
  const uniforms: Record<string, WebGLUniformLocation | null> = {}
  for (const name of uniformNames) {
    uniforms[name] = gl.getUniformLocation(program, name)
  }

  const created: GlPool = {
    canvas,
    gl,
    program,
    textures: new Map(),
    uniforms,
    lost: false,
  }

  canvas.addEventListener('webglcontextlost', (e) => {
    e.preventDefault()
    created.lost = true
    stopLoop()
    updateDebugStats()
  })
  canvas.addEventListener('webglcontextrestored', () => {
    pool = null
    scheduleLoop()
  })

  pool = created
  return pool
}

function getOrLoadTexture(p: GlPool, url: string): TextureRecord {
  const existing = p.textures.get(url)
  if (existing) return existing
  const rec: TextureRecord = { url, tex: null, ready: false, loading: true }
  p.textures.set(url, rec)
  const img = new Image()
  img.decoding = 'async'
  img.onload = () => {
    if (p.lost) return
    const tex = p.gl.createTexture()
    if (!tex) return
    p.gl.bindTexture(p.gl.TEXTURE_2D, tex)
    p.gl.texParameteri(p.gl.TEXTURE_2D, p.gl.TEXTURE_WRAP_S, p.gl.CLAMP_TO_EDGE)
    p.gl.texParameteri(p.gl.TEXTURE_2D, p.gl.TEXTURE_WRAP_T, p.gl.CLAMP_TO_EDGE)
    p.gl.texParameteri(p.gl.TEXTURE_2D, p.gl.TEXTURE_MIN_FILTER, p.gl.LINEAR)
    p.gl.texParameteri(p.gl.TEXTURE_2D, p.gl.TEXTURE_MAG_FILTER, p.gl.LINEAR)
    p.gl.texImage2D(p.gl.TEXTURE_2D, 0, p.gl.RGBA, p.gl.RGBA, p.gl.UNSIGNED_BYTE, img)
    rec.tex = tex
    rec.ready = true
    rec.loading = false
    updateDebugStats()
    scheduleLoop()
  }
  img.onerror = () => {
    rec.loading = false
  }
  img.src = url
  return rec
}

function bindLifecycle(): void {
  if (lifecycleBound || typeof document === 'undefined') return
  lifecycleBound = true
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopLoop()
    } else {
      lastTickMs = performance.now()
      scheduleLoop()
    }
  })
}

function stopLoop(): void {
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = 0
  }
}

function hasDrawableInstances(): boolean {
  if (typeof document !== 'undefined' && document.hidden) return false
  for (const inst of instances.values()) {
    if (inst.visible && inst.width > 0 && inst.height > 0) return true
  }
  return false
}

function scheduleLoop(): void {
  if (rafId || !hasDrawableInstances()) return
  lastTickMs = performance.now()
  rafId = requestAnimationFrame(tick)
}

function renderInstance(p: GlPool, inst: StageInstance, nowSec: number, dt: number, resolveArt: (cid: string, v: string) => string, resolveRig: (cid: string, v: string) => string): boolean {
  const { params, rigSpec } = inst
  const artRec = getOrLoadTexture(p, resolveArt(params.commanderId, params.variant))
  const rigRec = getOrLoadTexture(p, resolveRig(params.commanderId, params.variant))
  if (!artRec.ready || !rigRec.ready || !artRec.tex || !rigRec.tex) return false

  const spring = Math.min(1, dt * 8.5)
  inst.curPx += (inst.targetPx - inst.curPx) * spring
  inst.curPy += (inst.targetPy - inst.curPy) * spring
  const targetHover = inst.hovered ? 1 : 0
  inst.hoverMix += (targetHover - inst.hoverMix) * spring

  const w = Math.max(2, Math.min(720, Math.round(inst.width)))
  const h = Math.max(2, Math.min(960, Math.round(inst.height)))
  if (p.canvas.width < w || p.canvas.height < h) {
    p.canvas.width = Math.max(p.canvas.width, w)
    p.canvas.height = Math.max(p.canvas.height, h)
  }
  if (inst.canvas.width !== w || inst.canvas.height !== h) {
    inst.canvas.width = w
    inst.canvas.height = h
  }
  const gl = p.gl
  const u = p.uniforms
  gl.useProgram(p.program)
  gl.viewport(0, 0, w, h)

  gl.activeTexture(gl.TEXTURE0)
  gl.bindTexture(gl.TEXTURE_2D, artRec.tex)
  gl.uniform1i(u.uArtTex, 0)

  gl.activeTexture(gl.TEXTURE1)
  gl.bindTexture(gl.TEXTURE_2D, rigRec.tex)
  gl.uniform1i(u.uRigTex, 1)

  gl.uniform1f(u.uTime, nowSec + inst.phaseOffset)
  gl.uniform2f(u.uDstSize, w, h)
  gl.uniform2f(u.uFocus, params.faceFocusX, params.faceFocusY)
  gl.uniform2f(u.uPointer, inst.curPx, inst.curPy)
  gl.uniform1f(u.uHoverMix, inst.hoverMix)

  gl.uniform1f(u.uMotionScale, params.motionScale)
  gl.uniform1f(u.uVfxScale, params.vfxScale)
  gl.uniform1f(u.uParallaxScale, params.parallaxScale)
  gl.uniform1f(u.uBloomScale, params.bloomScale)
  gl.uniform1f(u.uMuted, params.muted ? 1 : 0)

  gl.uniform4f(u.uFace, rigSpec.face[0], rigSpec.face[1], rigSpec.face[2], rigSpec.face[3])
  gl.uniform2f(u.uHeadPivot, rigSpec.headPivot[0], rigSpec.headPivot[1])
  gl.uniform2f(u.uChest, rigSpec.chest[0], rigSpec.chest[1])

  const le = rigSpec.leftEye
  const re = rigSpec.rightEye
  gl.uniform4f(u.uLeftEye, le ? le.cx : 0, le ? le.cy : 0, le ? le.rx : 0, le ? le.ry : 0)
  gl.uniform4f(u.uRightEye, re ? re.cx : 0, re ? re.cy : 0, re ? re.rx : 0, re ? re.ry : 0)
  gl.uniform2f(u.uEyeAngles, le ? le.angle : 0, re ? re.angle : 0)

  const vs = rigSpec.visor
  gl.uniform4f(u.uVisor, vs ? vs.cx : 0, vs ? vs.cy : 0, vs ? vs.rx : 0, vs ? vs.ry : 0)
  gl.uniform2f(u.uWindDir, rigSpec.windDir[0], rigSpec.windDir[1])

  gl.uniform1f(u.uThemeId, rigSpec.themeId)
  gl.uniform3f(u.uGlowRgb, rigSpec.glowRgb[0], rigSpec.glowRgb[1], rigSpec.glowRgb[2])
  gl.uniform3f(u.uRayRgb, rigSpec.rayRgb[0], rigSpec.rayRgb[1], rigSpec.rayRgb[2])
  gl.uniform3f(u.uParticleRgb, rigSpec.particleRgb[0], rigSpec.particleRgb[1], rigSpec.particleRgb[2])
  gl.uniform3f(u.uLashRgb, rigSpec.lashRgb[0], rigSpec.lashRgb[1], rigSpec.lashRgb[2])
  gl.uniform1f(u.uBreathSpeed, rigSpec.breathSpeed)
  gl.uniform1f(u.uBlinkPeriod, rigSpec.blinkPeriod)
  gl.uniform1f(u.uMotionGain, rigSpec.motionGain)

  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)

  if (inst.ctx2d) {
    const sy = p.canvas.height - h
    inst.ctx2d.drawImage(p.canvas, 0, sy, w, h, 0, 0, w, h)
    if (!inst.drawnOnce) {
      inst.drawnOnce = true
      inst.onFirstFrame?.()
    }
  }
  return true
}

let urlResolver: { art: (c: string, v: string) => string; rig: (c: string, v: string) => string } = {
  art: (c, v) => `/commanders/${c}/art_${v}.webp`,
  rig: (c, v) => `/commanders/${c}/rig_${v}.png`,
}

export function setWallpaperUrlResolvers(
  art: (c: string, v: string) => string,
  rig: (c: string, v: string) => string,
): void {
  urlResolver = { art, rig }
}

function tick(nowMs: number): void {
  rafId = 0
  if (!hasDrawableInstances()) return
  const p = ensurePool()
  if (!p || p.lost) {
    updateDebugStats()
    return
  }

  const dt = Math.max(0.001, Math.min(0.08, (nowMs - lastTickMs) / 1000))
  lastTickMs = nowMs
  const nowSec = nowMs / 1000
  let drew = false

  for (const inst of instances.values()) {
    if (!inst.visible || inst.width <= 0 || inst.height <= 0) continue
    if (renderInstance(p, inst, nowSec, dt, urlResolver.art, urlResolver.rig)) {
      drew = true
    }
  }
  if (drew) {
    frameCount += 1
    updateDebugStats()
  }
  rafId = requestAnimationFrame(tick)
}

export function isWallpaperSupported(): boolean {
  if (glUnsupported) return false
  if (typeof window === 'undefined') return false
  return ensurePool() !== null
}

export function registerWallpaperStage(
  canvas: HTMLCanvasElement,
  initial: WallpaperStageParams,
  onReady?: () => void,
): WallpaperStageHandle | null {
  const p = ensurePool()
  if (!p) return null
  const ctx2d = canvas.getContext('2d', { alpha: false })
  if (!ctx2d) return null
  bindLifecycle()

  const id = nextInstanceId++
  const inst: StageInstance = {
    id,
    canvas,
    ctx2d,
    params: { ...initial },
    rigSpec: getPortraitRig(initial.commanderId, initial.variant),
    visible: true,
    drawnOnce: false,
    onFirstFrame: onReady,
    width: Math.max(2, Math.round(canvas.clientWidth || 120)),
    height: Math.max(2, Math.round(canvas.clientHeight || 160)),
    targetPx: 0,
    targetPy: 0,
    curPx: 0,
    curPy: 0,
    hovered: false,
    hoverMix: 0,
    phaseOffset: (id * 1.37) % 5.0,
  }
  instances.set(id, inst)

  // Eagerly warm art & rig textures; first rendered frame triggers onFirstFrame cleanly.
  getOrLoadTexture(p, urlResolver.art(initial.commanderId, initial.variant))
  getOrLoadTexture(p, urlResolver.rig(initial.commanderId, initial.variant))

  updateDebugStats()
  scheduleLoop()

  return {
    update(next: WallpaperStageParams) {
      inst.params = { ...next }
      inst.rigSpec = getPortraitRig(next.commanderId, next.variant)
      getOrLoadTexture(p, urlResolver.art(next.commanderId, next.variant))
      getOrLoadTexture(p, urlResolver.rig(next.commanderId, next.variant))
    },
    setPointer(nx: number, ny: number, hovered: boolean) {
      inst.targetPx = Math.max(-1, Math.min(1, nx))
      inst.targetPy = Math.max(-1, Math.min(1, ny))
      inst.hovered = hovered
    },
    setVisible(vis: boolean) {
      inst.visible = vis
      updateDebugStats()
      if (vis) scheduleLoop()
    },
    resize(cssWidth: number, cssHeight: number, dpr: number) {
      const scale = Math.min(2, Math.max(1, dpr))
      inst.width = Math.max(2, Math.min(720, Math.round(cssWidth * scale)))
      inst.height = Math.max(2, Math.min(960, Math.round(cssHeight * scale)))
    },
    dispose() {
      instances.delete(id)
      updateDebugStats()
      if (!hasDrawableInstances()) stopLoop()
    },
  }
}
