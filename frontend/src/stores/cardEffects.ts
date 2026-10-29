import { defineStore } from 'pinia'
import { ref } from 'vue'
import { CardEffectTimeline } from '../screens/game/cardEffects/timeline'

/** 只管理临时演出，不持有棋盘、手牌或规则状态。 */
export const useCardEffectsStore = defineStore('card-effects', () => {
  const version=ref(0), busy=ref(false), timeline=new CardEffectTimeline()
  let enabled=true, callbacks:Array<()=>void>=[], releasedToken=''
  function release(): void { const pending=callbacks;callbacks=[];pending.forEach(fn=>fn()) }
  function begin(payload: unknown): boolean {
    if(!enabled)return false
    const accepted=timeline.begin(payload,Date.now())
    if(accepted){release();releasedToken='';busy.value=timeline.busy;version.value+=1}
    return accepted
  }
  function whenFinished(callback:()=>void, token?:string): void {
    if(!enabled||!timeline.current||(token&&token!==timeline.current.token)||timeline.stageDone(Date.now()))callback()
    else callbacks.push(callback)
  }
  function finishStage(): void { if(releasedToken===timeline.current?.token)return;releasedToken=timeline.current?.token??'';timeline.finishStage();busy.value=timeline.busy;release();version.value+=1 }
  function reset(forgetHistory=false): void { timeline.clear(forgetHistory);releasedToken='';busy.value=false;release();version.value+=1 }
  function setEnabled(value:boolean): void { enabled=value;if(!value)reset() }
  return {version,busy,begin,whenFinished,finishStage,reset,setEnabled,at:(now:number)=>timeline.at(now),stageDone:(now:number)=>timeline.stageDone(now)}
})
