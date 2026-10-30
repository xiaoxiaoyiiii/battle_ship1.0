import type { CardEffectKind } from './types'

export interface EffectPosition { x: number; y: number }
export interface EffectDescription {
  id: string; kind: CardEffectKind; card: string; caster: string; target: string
  cells: EffectPosition[]; privateCells: EffectPosition[]; privateTargets: boolean
  origin?: EffectPosition; duration: number; impact: number
}
export interface EffectCue {
  token: string; description: EffectDescription; stage: 'effect_windup' | 'effect_tail'
  started: number; duration: number; success: boolean
}
export interface EffectFrame { cue: EffectCue; progress: number; opacity: number; success: boolean }
const kinds: readonly string[] = ['bomb','vortex','ice','fire','splash','negate','seal','gabriel','revive','heal','last_chance','shield','sanctuary']
const clamp = (n: number, a: number, b: number): number => Math.max(a, Math.min(b, n))
const record = (v: unknown): Record<string, unknown> => v && typeof v === 'object' ? v as Record<string, unknown> : {}
function positions(v: unknown): EffectPosition[] {
  if (!Array.isArray(v)) return []
  return v.flatMap(raw => { const p=record(raw); return Number.isInteger(p.x) && Number.isInteger(p.y) && Number(p.x)>=0 && Number(p.x)<6 && Number(p.y)>=0 && Number(p.y)<6 ? [{x:Number(p.x),y:Number(p.y)}] : [] }).slice(0,36)
}
function description(value: unknown): EffectDescription | null {
  const p=record(value)
  if (typeof p.effect_id !== 'string' || !p.effect_id || !kinds.includes(String(p.kind)) || typeof p.caster !== 'string' || typeof p.target !== 'string') return null
  return {id:p.effect_id, kind:p.kind as CardEffectKind, card:String(p.card??''), caster:p.caster, target:p.target,
    cells:positions(p.cells), privateCells:p.private_targets===true?positions(p.private_cells):[], privateTargets:p.private_targets===true,
    origin:positions([p.origin])[0], duration:clamp(Number(p.duration_ms)||1250,400,1800), impact:clamp(Number(p.impact)||.45,.25,.65)}
}

/** 前导到落点前停住；真实提交由服务端另一个令牌启动尾声。 */
export class CardEffectTimeline {
  current: EffectCue | null = null
  private seen = new Set<string>()
  get busy(): boolean { return this.current !== null }
  begin(value: unknown, now: number): boolean {
    const p=record(value), d=description(p.effect), stage=p.stage, token=p.animation_id
    if (!d || typeof token!=='string' || !token || !['effect_windup','effect_tail'].includes(String(stage)) || this.seen.has(token)) return false
    this.seen.add(token); if(this.seen.size>256)this.seen.delete(this.seen.values().next().value!)
    if(stage==='effect_tail' && this.current?.description.id!==d.id)return false
    const tail=stage==='effect_tail'
    this.current={token,description:d,stage:tail?'effect_tail':'effect_windup',started:now,duration:d.duration*(tail?1-d.impact:d.impact),success:p.success!==false}
    return true
  }
  stageDone(now: number): boolean { return !this.current || now>=this.current.started+this.current.duration }
  at(now: number): EffectFrame | null {
    const cue=this.current;if(!cue)return null
    const p=clamp((now-cue.started)/cue.duration,0,1),impact=cue.description.impact
    const progress=cue.stage==='effect_windup'?Math.min(impact-.001,p*impact):cue.success?impact+(1-impact)*p:(impact-.001)*(1-p)
    return {cue,progress,opacity:cue.success||cue.stage==='effect_windup'?1:1-p,success:cue.success}
  }
  finishStage(): void { if(this.current?.stage==='effect_tail')this.current=null }
  /** 取消可见演出仍保留有界去重记录，避免迟到前导再次锁住界面。 */
  clear(forgetHistory=false): void { this.current=null;if(forgetHistory)this.seen.clear() }
}
