<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useCollectionStore } from '../../stores/collection'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import { CARDS } from '../../cards/cardData'
import { cardArtUrl } from '../../cards/cardArt'
import { filteredCards, masteryClass, MASTERY_NAMES, type CollectionCard } from './model'
import './collection.css'

const store = useCollectionStore(), auth = useAuthStore(), ui = useUiStore()
const tab = ref('cards'), selected = ref(''), detail = ref<HTMLElement | null>(null)
const filter = reactive({ query:'', status:'all', speed:'all', type:'all', sort:'default' })
const guests = CARDS.filter((c,i)=>CARDS.findIndex(row=>row.name===c.name)===i).map(c=>({...c,lit:false,uses:0,wins:0,selected_tier:0,unlocked_tier:0,next_target:10,
  remaining:10,chain_description:`速阶 ${c.speed}，连锁响应仍按当前时段与速阶规则判定。`})) as CollectionCard[]
const cards = computed(()=>store.data?.cards ?? guests)
const visible = computed(()=>filteredCards(cards.value,filter))
const current = computed(()=>cards.value.find(c=>c.name===selected.value) ?? null)
const types = computed(()=>[...new Set(cards.value.map(c=>c.type))])
const unlocked = computed(()=>store.data?.achievements.filter(a=>a.unlocked).length ?? 0)
async function pick(name:string):Promise<void> {
  selected.value = name
  if (window.matchMedia('(max-width: 760px)').matches) {
    await nextTick(); detail.value?.scrollIntoView({block:'start',behavior:ui.motion==='reduced'?'auto':'smooth'})
  }
}
async function choose(tier:number):Promise<void> {
  if (!current.value) return
  const ok = await store.select(current.value.name,tier)
  if (ok) ui.notify({code:'collection-mastery-saved',message:'光效已保存，下一次出牌展示时生效。',tone:'success',ttl:2400})
}
function load():void { if (!auth.isGuest) void store.load() }
onMounted(load)
</script>

<template>
  <section class="archive" data-testid="screen-collection" aria-labelledby="archive-title">
    <header class="archive__mast">
      <div><h1 id="archive-title">航海图鉴</h1><p>每一张亲手打出的卡，都有自己的航迹。</p></div>
      <div class="archive__totals"><span><b>{{ store.data?.lit_count ?? 0 }}</b> / 48 张点亮</span><span><b>{{ unlocked }}</b> / 12 项成就</span></div>
    </header>
    <section class="archive__rewards" aria-label="点亮奖励进度" data-testid="collection-rewards">
      <div><strong>点亮一张 · 徽记 +10</strong><p>点亮可计入匹配、排位、人机与每日挑战，自定义房不计。</p></div>
      <ol><li v-for="m in store.data?.milestones ?? [{target:12,tide:50,claimed:false},{target:24,tide:100,claimed:false},{target:36,tide:150,claimed:false},{target:48,tide:300,claimed:false}]" :key="m.target" :class="{'is-claimed':m.claimed}"><b>{{ m.target }} 张</b><span>+{{ m.tide }} 徽记</span><small>{{ m.claimed ? '已到账' : m.target===48 ? '另送「全图鉴」称号' : '达到后自动到账' }}</small></li></ol>
    </section>
    <p v-if="auth.isGuest" class="archive__notice">登录后即可记录点亮、熟练和成就。现在可以浏览全部卡牌。</p>
    <p v-if="store.loading" role="status">正在读取你的航迹…</p>
    <div v-if="store.error" class="archive__notice" role="alert">{{ store.error }} <button v-if="!auth.isGuest" type="button" @click="load">重新读取</button></div>
    <nav class="archive__tabs" aria-label="图鉴内容"><button :aria-pressed="tab==='cards'" @click="tab='cards'">卡牌图鉴</button><button :aria-pressed="tab==='achievements'" @click="tab='achievements'">航海成就 <small>{{ unlocked }}/12</small></button></nav>
    <template v-if="tab==='cards'">
      <div class="archive__filters"><label class="archive__search">查找卡牌<input v-model="filter.query" placeholder="卡名或效果文案" data-testid="collection-search" /></label>
        <label>点亮<select v-model="filter.status"><option value="all">全部状态</option><option value="lit">已点亮</option><option value="unlit">未点亮</option></select></label>
        <label>速阶<select v-model="filter.speed"><option value="all">全部速阶</option><option v-for="n in [1,2,3]" :key="n" :value="String(n)">速阶 {{ n }}</option></select></label>
        <label>类型<select v-model="filter.type"><option value="all">全部类型</option><option v-for="t in types" :key="t">{{ t }}</option></select></label>
        <label>排序<select v-model="filter.sort"><option value="default">卡表顺序</option><option value="uses">熟练次数</option><option value="name">卡牌名称</option></select></label>
      </div>
      <div class="archive__body" :class="{'has-selection':current}">
        <div><p class="archive__count">{{ visible.length }} 张卡牌 · 熟练与胜场仅计有效匹配和排位</p>
          <p v-if="!visible.length" class="archive__notice">没有找到卡牌，试试更换关键词或筛选条件。</p>
          <ul class="archive__grid"><li v-for="c in visible" :key="c.name"><button class="archive-card" :class="[masteryClass(c.selected_tier),{'is-unlit':!c.lit,'is-selected':current?.name===c.name}]" :aria-pressed="current?.name===c.name" :aria-label="c.name+'，'+(c.lit?'已点亮':'未点亮')" data-testid="collection-card" :data-card="c.name" @click="pick(c.name)">
            <div class="archive-card__art"><img :src="cardArtUrl(c.name) || ''" :alt="c.name+' 卡面'" loading="lazy" /><span>{{ c.lit ? '已点亮' : '未点亮' }}</span></div>
            <div class="archive-card__caption"><strong>{{ c.name }}</strong><span>速阶 {{ c.speed }} · {{ c.type }}</span><small>{{ c.uses }} 次出牌 · {{ c.wins }} 胜</small></div>
          </button></li></ul>
        </div>
        <aside v-if="current" ref="detail" class="archive__detail" data-testid="collection-card-detail" tabindex="-1" :aria-label="current.name+' 详情'">
          <button class="archive__detail-close" aria-label="关闭卡牌详情" @click="selected=''">×</button>
          <div class="archive__detail-art" :class="masteryClass(current.selected_tier)"><img :src="cardArtUrl(current.name) || ''" :alt="current.name+' 卡面预览'" /></div>
          <h2>{{ current.name }}</h2><p class="archive__card-kind">速阶 {{ current.speed }} · {{ current.type }} · {{ current.lit?'已点亮':'尚未点亮' }}</p>
          <p class="archive__description">{{ current.description }}</p><p class="archive__chain">{{ current.chain_description }}</p>
          <dl class="archive__card-stats"><div><dt>打出次数</dt><dd>{{ current.uses }}</dd></div><div><dt>胜场</dt><dd>{{ current.wins }}</dd></div></dl>
          <section class="archive__mastery"><h3>卡牌光效 <span>{{ MASTERY_NAMES[current.selected_tier] }}</span></h3>
            <p v-if="current.next_target">距下一档还需 {{ current.remaining }} 次出牌 · {{ current.uses }}/{{ current.next_target }}</p><p v-else>已达最高档 · 已获得该卡专属称号</p>
            <progress :value="current.uses" :max="current.next_target || 500" :aria-label="current.name+' 熟练进度'" />
            <div class="archive__tiers"><button v-for="(name,tier) in MASTERY_NAMES" :key="tier" :disabled="auth.isGuest || tier>current.unlocked_tier || !!store.saving" :aria-pressed="current.selected_tier===tier" :data-testid="'collection-tier-'+tier" @click="choose(tier)"><b>{{ name }}</b><small>{{ tier===0?'不显示':[10,50,100,500][tier-1]+' 次' }}</small></button></div>
            <p>光效只改变外观。已选档位会在所有模式的公开出牌和连锁中显示，关闭不会清空熟练记录。</p>
          </section>
        </aside>
      </div>
    </template>
    <section v-else class="archive__achievements" aria-label="十二项航海成就" data-testid="collection-achievements">
      <p class="archive__notice">仅计有效休闲匹配和排位。奖励自动到账、每项一次，不占对局徽记日帽。</p>
      <p v-if="auth.isGuest">登录后可查看十二项成就进度。</p>
      <ol><li v-for="a in store.data?.achievements ?? []" :key="a.id" :class="{'is-earned':a.unlocked}"><div class="archive__achievement-seal" aria-hidden="true">{{ a.unlocked?'★':'☆' }}</div><div><h2>{{ a.name }} <small v-if="a.unlocked">已达成</small></h2><p>{{ a.description }}</p><progress :value="a.current" :max="a.target" :aria-label="a.name+' 进度'" /><small>{{ a.current }} / {{ a.target }}</small></div><div class="archive__achievement-reward"><b>+{{ a.tide }}</b><span>潮汐徽记</span><small v-if="a.title">另送专属称号</small></div></li></ol>
    </section>
  </section>
</template>
