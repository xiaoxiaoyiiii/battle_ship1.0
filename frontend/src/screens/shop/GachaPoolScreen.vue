<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useGachaStore } from '../../stores/gacha'
import { useUiStore } from '../../stores/ui'
import type { GachaPoolSkin } from '../../stores/gachaTypes'
import GachaReveal from './gacha/GachaReveal.vue'

const auth = useAuthStore()
const store = useGachaStore()
const ui = useUiStore()
const confirmSkin = ref<GachaPoolSkin | null>(null)
const shardBar = ref<HTMLElement | null>(null)
const reduceMotion = computed(() => ui.motion === 'reduced')

const rates = computed(() => store.pool?.ratesDisplay ?? [])
const progress = computed(() => store.pool?.progress ?? { owned: 0, total: 12, complete: false })
const exchangeCost = computed(() => store.pool?.exchangeCost ?? { legendary: 20, limited: 60 })
const unowned = computed(() => (store.pool?.skins ?? []).filter((skin) => !skin.owned))
const prices = computed(() => store.prices)
const shards = computed(() => store.shards)
const balance = computed(() => store.balance)
const loggedIn = computed(() => !auth.isGuest && store.status !== 'anonymous')

function shortOf(cost: number): boolean {
  return balance.value !== null && cost > balance.value
}

function pullDisabled(count: 1 | 10): boolean {
  if (!loggedIn.value || store.pulling !== null || store.exchanging !== null) return true
  const price = count === 10 ? prices.value.ten : prices.value.single
  return shortOf(price)
}

function pullLabel(count: 1 | 10): string {
  const price = count === 10 ? prices.value.ten : prices.value.single
  const title = count === 10 ? '十连' : '单抽'
  if (store.pulling === count) return '抽卡中…'
  if (loggedIn.value && shortOf(price)) return '徽记不足'
  return `${title} ${price}`
}

function costOf(skin: GachaPoolSkin): number {
  return skin.tier === 'limited' ? exchangeCost.value.limited : exchangeCost.value.legendary
}

function canExchange(skin: GachaPoolSkin): boolean {
  return loggedIn.value && !store.busy && shards.value >= costOf(skin)
}

async function pull(count: 1 | 10): Promise<void> {
  if (pullDisabled(count)) return
  const result = await store.pull(count)
  if (!result.ok || !result.result) {
    ui.notify({ code: `gacha-pull-${count}-fail`, tone: 'warning', message: result.message || '抽卡没有完成', ttl: 2600 })
    return
  }
  if (result.replayed) {
    ui.notify({ code: 'gacha-pull-replayed', tone: 'success', message: '已展示上次同一请求的抽卡结果', ttl: 2600 })
  }
}

function onRevealSkip(): void {
  // skip 只表示一键翻完，结算总览仍留在本组件上。
}

function closeReveal(): void {
  store.clearLastPull()
}

async function confirmExchange(skin: GachaPoolSkin): Promise<void> {
  const result = await store.exchange(skin.skinId)
  confirmSkin.value = null
  if (!result.ok) {
    ui.notify({ code: `gacha-exchange-${skin.skinId}-fail`, tone: 'warning', message: result.message || '兑换没有完成', ttl: 2600 })
    return
  }
  ui.notify({
    code: `gacha-exchange-${skin.skinId}`,
    tone: 'success',
    message: result.alreadyOwned ? `已经拥有「${skin.cardName}」` : `已兑换并装备「${skin.cardName}」`,
    ttl: 2600,
  })
}

function load(): void {
  if (!auth.isGuest) void store.load(true)
}

onMounted(load)
watch(() => auth.isGuest, (guest) => {
  if (guest) {
    confirmSkin.value = null
    store.reset()
  }
  load()
})
</script>

<template>
  <section class="gacha-pool" data-testid="shop-gacha" aria-labelledby="gacha-pool-title">
    <header class="gacha-pool__head">
      <div>
        <h2 id="gacha-pool-title">霓虹赛博卡池</h2>
        <p>用潮汐徽记抽取 12 款卡面皮肤。皮肤不在常驻货架出售，只能抽取或用碎片兑换。</p>
        <p>首次抽中或兑换皮肤后会自动装备，可在图鉴切回默认卡面。</p>
      </div>
    </header>

    <div v-if="store.status === 'loading'" class="gacha-pool__state" role="status">正在读取卡池…</div>
    <div v-else-if="store.status === 'error'" class="gacha-pool__state gacha-pool__state--error" role="alert">
      {{ store.error || '卡池暂时无法读取。' }}
      <button type="button" class="button button--ghost" @click="load">重试</button>
    </div>
    <template v-else>
      <section class="gacha-pool__rates" data-testid="gacha-rates" aria-label="概率公示">
        <h3>概率公示</h3>
        <ul v-if="rates.length">
          <li v-for="line in rates" :key="line.kind">
            <b>{{ line.label }}</b>
            <span>{{ line.percent }}</span>
            <small v-if="line.note">{{ line.note }}</small>
          </li>
        </ul>
        <ul v-else>
          <li><b>限定皮肤</b><span>1%</span><small>3 款中均匀抽取</small></li>
          <li><b>传说皮肤</b><span>9%</span><small>9 款中均匀抽取</small></li>
          <li><b>潮汐碎片 ×1</b><span>90%</span></li>
        </ul>
        <p class="gacha-pool__note" data-testid="gacha-rates-note">
          限定 1%（3 款中均匀抽取）、传说 9%、碎片 90%。抽到已拥有的皮肤返还 5 碎片。无保底；碎片兑换即保底（传说 20 / 限定 60）。集齐后仍可抽取，皮肤按重复折算碎片。
        </p>
      </section>

      <section class="gacha-pool__status">
        <p class="gacha-pool__progress" data-testid="gacha-progress">
          集齐进度 <b>{{ progress.owned }}</b> / {{ progress.total }}
          <span v-if="progress.complete">已集齐</span>
        </p>
        <p ref="shardBar" class="gacha-pool__shards" data-testid="gacha-shards">潮汐碎片 <b>{{ shards }}</b></p>
      </section>

      <div class="gacha-pool__actions">
        <button
          type="button"
          class="button button--primary"
          data-testid="gacha-pull-1"
          :class="{ 'is-short': shortOf(prices.single) }"
          :disabled="pullDisabled(1)"
          @click="pull(1)"
        >{{ pullLabel(1) }}</button>
        <button
          type="button"
          class="button button--primary"
          data-testid="gacha-pull-10"
          :class="{ 'is-short': shortOf(prices.ten) }"
          :disabled="pullDisabled(10)"
          @click="pull(10)"
        >{{ pullLabel(10) }}</button>
      </div>
      <p v-if="store.error" class="gacha-pool__error" data-testid="gacha-feedback" role="alert">{{ store.error }}</p>

      <div v-if="store.lastPull" class="gacha-pool__reveal" data-testid="gacha-reveal-mount">
        <GachaReveal
          :key="store.lastPull.requestId"
          :results="store.lastPull.results"
          :shard-balance="store.lastPull.shards"
          :shard-target="shardBar"
          :reduced-motion="reduceMotion"
          @skip="onRevealSkip"
          @done="closeReveal"
        />
      </div>

      <section class="gacha-pool__exchange" data-testid="gacha-exchange" aria-label="碎片兑换">
        <h3>碎片兑换</h3>
        <p>传说 20 碎片、限定 60 碎片，只能兑换尚未拥有的皮肤。</p>
        <p v-if="!unowned.length" class="gacha-pool__empty" data-testid="gacha-exchange-empty">12 款皮肤都已拥有，无需兑换。</p>
        <ul v-else class="gacha-pool__skins">
          <li v-for="skin in unowned" :key="skin.skinId" class="gacha-skin" :data-testid="'gacha-exchange-' + skin.skinId">
            <div>
              <small>{{ skin.tier === 'limited' ? '限定' : '传说' }}</small>
              <strong>{{ skin.cardName }}</strong>
              <span>{{ costOf(skin) }} 碎片</span>
            </div>
            <button
              type="button"
              class="button button--ghost"
              :disabled="!canExchange(skin)"
              :data-testid="'gacha-exchange-btn-' + skin.skinId"
              @click="confirmSkin = skin"
            >{{ shards < costOf(skin) ? '碎片不足' : '兑换' }}</button>
          </li>
        </ul>
        <div v-if="confirmSkin" class="gacha-pool__confirm" data-testid="gacha-exchange-confirm" role="dialog" :aria-label="'确认兑换 ' + confirmSkin.cardName">
          <p>用 {{ costOf(confirmSkin) }} 碎片兑换「{{ confirmSkin.cardName }}」？兑换后无法撤销。</p>
          <div>
            <button type="button" class="button button--ghost" data-testid="gacha-exchange-cancel" @click="confirmSkin = null">取消</button>
            <button type="button" class="button button--primary" data-testid="gacha-exchange-ok" :disabled="store.exchanging !== null" @click="confirmExchange(confirmSkin)">确认兑换</button>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.gacha-pool { display: grid; gap: 18px; }
.gacha-pool__head h2 { margin: 0 0 6px; color: var(--text-primary); font-size: 22px; letter-spacing: -0.02em; }
.gacha-pool__head p, .gacha-pool__rates p, .gacha-pool__exchange p, .gacha-pool__state { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.gacha-pool__state, .gacha-pool__rates, .gacha-pool__exchange, .gacha-pool__status { padding: 16px; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--surface-deck); }
.gacha-pool__state--error, .gacha-pool__error { color: var(--role-warning); }
.gacha-pool__error { margin: 0; font-size: 13px; }
.gacha-pool__rates h3, .gacha-pool__exchange h3 { margin: 0 0 10px; color: var(--text-primary); font-size: 15px; }
.gacha-pool__rates ul { margin: 0 0 10px; padding: 0; list-style: none; display: grid; gap: 8px; }
.gacha-pool__rates li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; color: var(--text-primary); font-size: 14px; }
.gacha-pool__rates li span { color: var(--gold-strong); font-variant-numeric: tabular-nums; }
.gacha-pool__rates li small { flex-basis: 100%; color: var(--text-secondary); font-size: 12px; }
.gacha-pool__note { font-size: 12px !important; }
.gacha-pool__status { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px 20px; color: var(--text-secondary); font-size: 14px; }
.gacha-pool__status b { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.gacha-pool__actions { display: flex; flex-wrap: wrap; gap: 10px; }
.gacha-pool__actions .button { min-width: 132px; }
.gacha-pool__actions .is-short { color: var(--role-warning); }
.gacha-pool__skins { margin: 12px 0 0; padding: 0; list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; }
.gacha-skin { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px; border: 1px solid var(--border-subtle); border-radius: 10px; background: var(--surface-sea); }
.gacha-skin div { display: grid; gap: 3px; min-width: 0; }
.gacha-skin small { color: var(--role-action); font-size: 11px; letter-spacing: 0.08em; }
.gacha-skin strong { color: var(--text-primary); font-size: 15px; }
.gacha-skin span { color: var(--gold-strong); font-size: 13px; font-variant-numeric: tabular-nums; }
.gacha-pool__confirm { margin-top: 12px; padding: 12px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface-sea); }
.gacha-pool__confirm div { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
.gacha-pool__empty { margin-top: 8px !important; }
@media (max-width: 390px) {
  .gacha-pool__skins { grid-template-columns: 1fr; }
  .gacha-pool__actions .button { flex: 1 1 140px; min-width: 0; }
  .gacha-pool__head h2 { font-size: 19px; }
}
@media (max-width: 320px) {
  .gacha-pool__status, .gacha-pool__rates, .gacha-pool__exchange { padding: 12px; }
}
</style>
