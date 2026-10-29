<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useCardEffectsStore } from '../../stores/cardEffects'
import { useGameStore } from '../../stores/game'
import { useUiStore } from '../../stores/ui'
import { drawCardEffect, drawCounterEffect, warmCardEffectCaches, clearCardEffectCaches } from './cardEffects/canvas'
import type { EffectCell, EffectRect } from './cardEffects/types'
import type { EffectFrame, EffectPosition } from './cardEffects/timeline'

const effects=useCardEffectsStore(),game=useGameStore(),ui=useUiStore(),canvas=ref<HTMLCanvasElement|null>(null),frame=shallowRef<EffectFrame|null>(null)
let raf=0,mounted=false,media:MediaQueryList|null=null,shaken:HTMLElement|null=null
function rect(selector:string): EffectRect|null {const r=document.querySelector(selector)?.getBoundingClientRect();return r&&r.width>0&&r.height>0?{x:r.x,y:r.y,w:r.width,h:r.height}:null}
function board(side:string):EffectRect|null{return rect(`[data-board="${side}"] .board__grid`)}
function cells(points:EffectPosition[],side:string):EffectCell[]{return points.flatMap(p=>{const r=rect(`[data-testid="game-cell-${side}-${p.x}-${p.y}"]`);return r?[{...r,cx:r.x+r.w/2,cy:r.y+r.h/2,gx:p.x,gy:p.y}]:[]})}
function clearShake():void{if(shaken){shaken.style.removeProperty('translate');shaken=null}}
function draw(next:EffectFrame):void{
 clearShake()
 const c=canvas.value;if(!c)return
 const width=innerWidth,height=innerHeight,ratio=Math.min(2,devicePixelRatio||1)
 if(c.width!==Math.round(width*ratio)||c.height!==Math.round(height*ratio)){c.width=Math.round(width*ratio);c.height=Math.round(height*ratio)}
 const ctx=c.getContext('2d');if(!ctx)return
 ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height)
 const d=next.cue.description,visibleSelf=board('self'),visibleOther=board('opponent'),self=visibleSelf??visibleOther,other=visibleOther??visibleSelf;if(!self||!other)return
 const mine=d.target===game.state.player_id,side=mine?'self':'opponent',visible=mine?visibleSelf:visibleOther
 const target=d.target==='field'?rect('[data-testid="game-field-magic"]')??other:visible??rect(`[data-testid="game-${side}-avatar"]`)??other,source=d.caster===game.state.player_id?self:other
 const union={x:Math.min(self.x,other.x),y:Math.min(self.y,other.y),w:Math.max(self.x+self.w,other.x+other.w)-Math.min(self.x,other.x),h:Math.max(self.y+self.h,other.y+other.h)-Math.min(self.y,other.y)}
 const privateTargets=Boolean(visible)&&d.privateTargets&&d.caster===game.state.player_id
 const origin=d.origin&&visible?cells([d.origin],side)[0]:null
 ctx.save();ctx.globalAlpha=next.opacity
 if(d.kind==='negate'||d.kind==='gabriel')drawCounterEffect(ctx,d.kind,next.progress,target)
 else drawCardEffect(ctx,{kind:d.kind,progress:next.progress,privateTargets,seed:42},{sourceBoard:source,targetBoard:target,boardsUnion:union,cells:visible?cells(d.cells,side):[],privateCells:privateTargets?cells(d.privateCells,side):[],origin:origin?[origin.cx,origin.cy]:undefined})
 ctx.restore();clearShake()
 if(next.success&&next.cue.stage==='effect_tail'){
  const age=(next.progress-d.impact)*d.duration,raw=d.kind==='bomb'?8:d.kind==='fire'?6:d.kind==='ice'?4:d.kind==='splash'?5:d.kind==='vortex'?3:0,base=raw*(ui.battleShake==='off'?0:ui.battleShake==='light'?.35:1)
  if(base&&age<220){const element=document.querySelector<HTMLElement>(d.kind==='vortex'?'.boards-container':`[data-board="${side}"] .board__grid`);if(element){const power=base*(1-age/220)**2;element.style.translate=`${Math.sin(age*.16)*power}px ${Math.cos(age*.18)*power*.5}px`;shaken=element}}
 }
}
function tick():void{raf=0;if(!mounted)return;const next=effects.at(Date.now());frame.value=next;if(!next){clearShake();return}draw(next);if(effects.stageDone(Date.now())){void nextTick(()=>effects.finishStage());clearShake()}else raf=requestAnimationFrame(tick)}
function start():void{if(mounted&&!raf)raf=requestAnimationFrame(tick)}
function syncMotion():void{effects.setEnabled(!document.hidden&&ui.motion!=='reduced'&&!media?.matches&&ui.connection==='online');if(!effects.busy){frame.value=null;clearShake()}}
watch(()=>effects.version,start);watch(()=>[ui.motion,ui.connection],syncMotion)
watch(()=>game.state.room_id,()=>{effects.reset();clearShake()})
onMounted(()=>{mounted=true;media=matchMedia('(prefers-reduced-motion: reduce)');syncMotion();warmCardEffectCaches();document.addEventListener('visibilitychange',syncMotion);media.addEventListener('change',syncMotion);start()})
onBeforeUnmount(()=>{mounted=false;cancelAnimationFrame(raf);effects.reset();clearShake();clearCardEffectCaches();document.removeEventListener('visibilitychange',syncMotion);media?.removeEventListener('change',syncMotion)})
</script>
<template><Teleport to="body"><div v-if="frame" class="card-effect-overlay" data-testid="card-effect-animation" :data-kind="frame.cue.description.kind" :data-stage="frame.cue.stage" :data-effect="frame.cue.description.id" :data-private-targets="frame.cue.description.privateTargets && frame.cue.description.caster === game.state.player_id ? 'true' : 'false'" aria-hidden="true"><canvas ref="canvas"></canvas></div></Teleport></template>
<style scoped>.card-effect-overlay{position:fixed;inset:0;z-index:32;pointer-events:none;overflow:hidden;contain:strict}.card-effect-overlay canvas{display:block;width:100%;height:100%}</style>
