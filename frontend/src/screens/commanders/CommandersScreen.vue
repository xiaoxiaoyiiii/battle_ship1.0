<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  commanderAvatarUrl,
  commanderEmojiUrl,
  commanderFaceFocus,
  commanderPortraitUrl,
  commanderTierLabel,
  commanderTierOf,
  portraitForLevelAndEquipped,
  portraitVariantFor,
  useCommandersStore,
  type CommanderSpecView,
} from '../../stores/commanders'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import CommanderPortraitStage from '../../components/commander/CommanderPortraitStage.vue'
import type { CommanderVfxStage } from '../../components/commander/CommanderVfxLayer.vue'

const auth = useAuthStore()
const ui = useUiStore()
const store = useCommandersStore()

const inspectedId = ref<string>('chichao')
const previewPortrait = ref<string>('')
const previewTierOverride = ref<number | null>(null)
const previewMotionStage = ref<CommanderVfxStage>('')
let motionTimer: ReturnType<typeof setTimeout> | null = null
const activeTab = ref<'rewards' | 'loadout'>('rewards')
const feedback = ref('')

onMounted(async () => {
  await store.load(true)
  if (store.selectedCommanderId) inspectedId.value = store.selectedCommanderId
})

onBeforeUnmount(() => {
  if (motionTimer !== null) clearTimeout(motionTimer)
})

const roster = computed(() => store.commanders)
const inspected = computed<CommanderSpecView | null>(
  () => roster.value.find((c) => c.id === inspectedId.value) ?? roster.value[0] ?? null,
)
const activeVariant = computed(() => {
  const c = inspected.value
  if (!c) return 'base'
  return previewPortrait.value || portraitVariantFor(c.progress.level, c.equipped)
})
const effectivePreviewTier = computed(() => {
  if (previewTierOverride.value !== null) return previewTierOverride.value
  return commanderTierOf(inspected.value?.progress.level || 1)
})

const PORTRAIT_FORMS: ReadonlyArray<{ id: 'base' | 'ascended' | 'alt' | 'ultimate'; label: string; reqLevel: number }> = [
  { id: 'base', label: '初始形态', reqLevel: 1 },
  { id: 'ascended', label: '进阶武装', reqLevel: 10 },
  { id: 'alt', label: '异色涂装', reqLevel: 17 },
  { id: 'ultimate', label: '终阶动态', reqLevel: 20 },
]

function formStatusLabel(c: CommanderSpecView, variant: 'base' | 'ascended' | 'alt' | 'ultimate', reqLevel: number): string {
  if (!c.owned || auth.isGuest) return '可预览'
  if (c.equipped.portrait === variant) return '已装备'
  if (c.unlocked_options.portraits.includes(variant)) return '已领取'
  if (c.progress.level >= reqLevel) return '可领取'
  return '可预览'
}

function formStatusTone(c: CommanderSpecView, variant: 'base' | 'ascended' | 'alt' | 'ultimate', reqLevel: number): string {
  if (!c.owned || auth.isGuest) return 'preview'
  if (c.equipped.portrait === variant) return 'equipped'
  if (c.unlocked_options.portraits.includes(variant)) return 'claimed'
  if (c.progress.level >= reqLevel) return 'claimable'
  return 'preview'
}

function triggerStageMotion(stage: CommanderVfxStage): void {
  if (motionTimer !== null) clearTimeout(motionTimer)
  previewMotionStage.value = ''
  window.setTimeout(() => {
    previewMotionStage.value = stage
  }, 16)
  const dur = stage === 'chain_enter' || stage === 'negated' ? 480 : stage === 'intro' ? 1020 : stage === 'victory' ? 1120 : 860
  motionTimer = setTimeout(() => {
    previewMotionStage.value = ''
  }, dur)
}

function pickInspect(c: CommanderSpecView): void {
  inspectedId.value = c.id
  previewPortrait.value = ''
  previewTierOverride.value = null
  previewMotionStage.value = ''
  feedback.value = ''
}

async function handleUnlock(): Promise<void> {
  const c = inspected.value
  if (!c) return
  if (auth.isGuest) {
    ui.requestLogin('login', '请登录后解锁并培养指挥官')
    return
  }
  const res = await store.unlock(c.id)
  feedback.value = res.message || (res.ok ? `成功解锁「${c.name}」` : '')
  if (res.ok) {
    ui.notify({ code: 'cmd-unlocked', message: feedback.value, tone: 'success' })
  } else if (res.message) {
    ui.notifyError('cmd-unlock-err', res.message)
  }
}

async function handleSelect(): Promise<void> {
  const c = inspected.value
  if (!c) return
  const res = await store.select(c.id)
  feedback.value = res.message || ''
  if (res.ok) {
    ui.notify({ code: 'cmd-selected', message: feedback.value, tone: 'success' })
  } else if (res.message) {
    ui.notifyError('cmd-select-err', res.message)
  }
}

async function handleClaim(level?: number, claimAll = false): Promise<void> {
  const c = inspected.value
  if (!c) return
  const res = await store.claim(c.id, level, claimAll)
  feedback.value = res.message || ''
  if (res.ok) {
    ui.notify({ code: 'cmd-claimed', message: feedback.value || '奖励已领取', tone: 'success' })
  } else if (res.message) {
    ui.notifyError('cmd-claim-err', res.message)
  }
}

async function handleEquip(slot: string, value: string): Promise<void> {
  const c = inspected.value
  if (!c || !c.owned) return
  const res = await store.equip(c.id, { [slot]: value })
  feedback.value = res.message || ''
  if (res.ok) {
    previewPortrait.value = slot === 'portrait' ? value : previewPortrait.value
    ui.notify({ code: 'cmd-equipped', message: feedback.value || '装配已更新', tone: 'success' })
  } else if (res.message) {
    ui.notifyError('cmd-equip-err', res.message)
  }
}

function portraitLabel(v: string): string {
  return { base: '初始立绘', ascended: '10级进阶', alt: '17级异色', ultimate: '20级终阶动态' }[v] || v
}
</script>

<template>
  <section class="cmd-page" data-testid="screen-commanders" aria-labelledby="commanders-page-title">
    <header class="cmd-page__head">
      <div>
        <p class="cmd-page__kicker">COMMANDER SYSTEM · 海战统帅档案</p>
        <h1 id="commanders-page-title">指挥官殿堂</h1>
        <p class="cmd-page__lead">首发四位原创指挥官，具备独立局内主动/速阶三技能与 1～20 级专属养成奖励。</p>
      </div>
      <div class="cmd-page__economy">
        <div class="cmd-stat-pill" data-testid="commanders-tide-ash">
          <span>潮汐徽记</span>
          <b>{{ store.view?.tide_ash_balance ?? 0 }}</b>
        </div>
        <div class="cmd-stat-pill" data-testid="commanders-ai-daily-cap">
          <span>今日人机 XP（{{ store.view?.day_cst || '--' }}）</span>
          <b>{{ store.view?.ai_daily_xp_used ?? 0 }} / {{ store.view?.ai_daily_xp_cap ?? 100 }}</b>
        </div>
      </div>
    </header>

    <div v-if="store.freeInitialAvailable" class="cmd-free-banner" data-testid="commanders-free-banner">
      <b>首领任选赠礼未领取：</b>从下方 4 位指挥官中任选 1 位即可 <strong>0 潮汐徽记</strong> 免费解锁出战！其余每位 500 潮汐徽记。
    </div>

    <div class="cmd-roster" role="tablist" aria-label="指挥官列表">
      <button
        v-for="c in roster"
        :key="c.id"
        type="button"
        class="cmd-card"
        :class="{ 'is-active': inspected?.id === c.id, 'is-selected': c.selected, 'is-locked': !c.owned && store.view?.authenticated }"
        :style="{ '--cmd-pri': c.palette.primary, '--cmd-acc': c.palette.accent }"
        :data-testid="'commander-card-' + c.id"
        @click="pickInspect(c)"
      >
        <img
          class="cmd-card__thumb"
          :src="portraitForLevelAndEquipped(c.id, c.progress.level, c.equipped)"
          :style="{ objectPosition: commanderFaceFocus(c.id, c.progress.level, c.equipped) }"
          :alt="c.name"
        />
        <div class="cmd-card__info">
          <div class="cmd-card__top">
            <b>{{ c.name }}</b>
            <span class="cmd-card__gender">{{ c.gender }}</span>
            <span v-if="c.selected" class="cmd-badge cmd-badge--gold">出战中</span>
            <span v-else-if="c.owned" class="cmd-badge">Lv.{{ c.progress.level }}</span>
            <span v-else-if="store.freeInitialAvailable" class="cmd-badge cmd-badge--free">可免费领</span>
            <span v-else class="cmd-badge cmd-badge--locked">{{ c.unlock_cost }} 徽记</span>
          </div>
          <small class="cmd-card__tagline">{{ c.title_tagline }} · 「{{ c.skill.name }}」</small>
          <div class="cmd-card__bar">
            <i :style="{ width: c.progress.progress_pct + '%' }"></i>
          </div>
          <span v-if="c.owned && c.claimable_levels.length" class="cmd-card__claim-dot">
            {{ c.claimable_levels.length }} 项待领
          </span>
        </div>
      </button>
    </div>

    <div v-if="inspected" class="cmd-stage" :style="{ '--cmd-pri': inspected.palette.primary, '--cmd-acc': inspected.palette.accent }">
      <aside class="cmd-stage__art">
        <div
          class="cmd-stage__portrait-box"
          :class="'tier-' + effectivePreviewTier"
        >
          <CommanderPortraitStage
            class="cmd-stage__portrait-stage"
            :commander-id="inspected.id"
            :commander-name="inspected.name"
            :level="inspected.progress.level"
            :equipped="inspected.equipped"
            :portrait-override="previewPortrait"
            :preview-stage="previewMotionStage"
            :preview-tier="effectivePreviewTier"
            mode="full"
            :active="effectivePreviewTier >= 1"
          />
          <span class="cmd-stage__tier-tag">
            Lv.{{ inspected.progress.level }} · {{ commanderTierLabel(effectivePreviewTier) }}
          </span>
        </div>

        <!-- 四形态进化对照（标注等级与已装备/已领取/可领取/可预览状态） -->
        <div class="cmd-forms-grid" data-testid="commander-forms-comparison" role="group" aria-label="四形态进化对照">
          <button
            v-for="form in PORTRAIT_FORMS"
            :key="form.id"
            type="button"
            class="cmd-form-card"
            :class="[
              'is-tone-' + formStatusTone(inspected, form.id, form.reqLevel),
              { 'is-current': activeVariant === form.id },
            ]"
            :data-testid="'commander-portrait-tab-' + form.id"
            @click="previewPortrait = form.id; previewTierOverride = commanderTierOf(form.reqLevel)"
          >
            <img
              class="cmd-form-card__img"
              :src="commanderPortraitUrl(inspected.id, form.id)"
              :style="{ objectPosition: commanderFaceFocus(inspected.id, form.id) }"
              :alt="inspected.name + form.label"
            />
            <div class="cmd-form-card__meta">
              <b>Lv.{{ form.reqLevel }} · {{ form.label }}</b>
              <span class="cmd-form-card__badge">{{ formStatusLabel(inspected, form.id, form.reqLevel) }}</span>
            </div>
          </button>
        </div>

        <!-- 阶位光效与动作预览控件 -->
        <div class="cmd-motion-preview" data-testid="commander-motion-preview">
          <div class="cmd-motion-preview__tiers">
            <span>阶位预览：</span>
            <button
              v-for="t in [
                { val: null, label: '当前' },
                { val: 0, label: 'Lv.1' },
                { val: 1, label: 'Lv.5' },
                { val: 2, label: 'Lv.10' },
                { val: 3, label: 'Lv.15' },
                { val: 4, label: 'Lv.20' },
              ]"
              :key="String(t.val)"
              type="button"
              class="cmd-var-btn"
              :class="{ 'is-current': previewTierOverride === t.val }"
              @click="previewTierOverride = t.val"
            >{{ t.label }}</button>
          </div>
          <div class="cmd-motion-preview__actions">
            <button type="button" class="cmd-var-btn" @click="triggerStageMotion('intro')">预览登场</button>
            <button type="button" class="cmd-var-btn" @click="triggerStageMotion('resolve')">预览技能</button>
            <button
              v-if="inspected.id === 'qingtong'"
              type="button"
              class="cmd-var-btn"
              @click="triggerStageMotion('reveal')"
            >延迟揭晓</button>
            <button
              v-if="inspected.skill.enters_chain"
              type="button"
              class="cmd-var-btn"
              @click="triggerStageMotion('chain_enter')"
            >入链示意</button>
            <button
              v-if="inspected.skill.enters_chain"
              type="button"
              class="cmd-var-btn"
              @click="triggerStageMotion('negated')"
            >无效退场</button>
            <button type="button" class="cmd-var-btn" @click="triggerStageMotion('victory')">预览胜利</button>
          </div>
          <small class="cmd-motion-preview__hint">预览不改动已装备外观，实战严格按各自装备槽生效。</small>
        </div>
      </aside>

      <main class="cmd-stage__detail">
        <div class="cmd-stage__header">
          <div>
            <h2 data-testid="commander-detail-name">{{ inspected.name }}</h2>
            <p class="cmd-stage__traits">{{ inspected.outfit }} · {{ inspected.personality }}</p>
          </div>
          <div class="cmd-stage__actions">
            <button
              v-if="!inspected.owned"
              type="button"
              class="button button--primary"
              :disabled="store.busy"
              data-testid="commander-unlock-btn"
              @click="handleUnlock"
            >
              {{ store.freeInitialAvailable ? '免费选择首发解锁' : `解锁（${inspected.unlock_cost} 潮汐徽记）` }}
            </button>
            <button
              v-else-if="!inspected.selected"
              type="button"
              class="button button--primary"
              :disabled="store.busy"
              data-testid="commander-select-btn"
              @click="handleSelect"
            >设为出战指挥官</button>
            <span v-else class="cmd-active-pill" data-testid="commander-already-selected">当前出战指挥官</span>
          </div>
        </div>

        <p v-if="feedback" class="cmd-feedback" role="status" data-testid="commander-action-feedback">{{ feedback }}</p>

        <div class="cmd-xp-box">
          <div class="cmd-xp-box__top">
            <b>等级成长：Lv.{{ inspected.progress.level }} / {{ inspected.progress.max_level }}</b>
            <span data-testid="commander-xp-progress-text">{{ inspected.progress.is_max_level ? '已满级（3800 / 3800 XP）' : `${inspected.progress.xp} XP（本级 ${inspected.progress.xp_in_level} / ${inspected.progress.xp_needed}）` }}</span>
          </div>
          <div class="cmd-xp-box__bar"><i :style="{ width: inspected.progress.progress_pct + '%' }"></i></div>
          <small>每级固定 200 XP（1→20 级共 3800 XP）；完赛 +20 XP、胜局 +10 XP；人机全账号每日上限 100 XP，每日挑战不开放技能与 XP。</small>
        </div>

        <section class="cmd-skill-panel" data-testid="commander-skill-panel">
          <div class="cmd-skill-panel__head">
            <h3>专属技能 · 【{{ inspected.skill.name }}】</h3>
            <span class="cmd-skill-panel__chip">{{ inspected.skill.limit_label }}</span>
            <span class="cmd-skill-panel__chip">{{ inspected.skill.enters_chain ? `速阶 ${inspected.skill.speed} · 入链` : '主动技能 · 不入链' }}</span>
          </div>
          <p class="cmd-skill-panel__timing">发动时机：{{ inspected.skill.timing_label }}</p>
          <p class="cmd-skill-panel__desc">{{ inspected.skill.description }}</p>
        </section>

        <nav class="cmd-tabs" aria-label="指挥官养成标签">
          <button
            type="button"
            :class="{ 'is-active': activeTab === 'rewards' }"
            data-testid="commander-tab-rewards"
            @click="activeTab = 'rewards'"
          >2～20 级奖励（{{ inspected.claimed_levels.length }}/19）</button>
          <button
            type="button"
            :class="{ 'is-active': activeTab === 'loadout' }"
            data-testid="commander-tab-loadout"
            @click="activeTab = 'loadout'"
          >外观装配</button>
        </nav>

        <section v-if="activeTab === 'rewards'" class="cmd-rewards" data-testid="commander-rewards-list">
          <div class="cmd-rewards__toolbar">
            <span>领取奖励后，已装备的外观仍会保留。</span>
            <button
              v-if="inspected.owned && inspected.claimable_levels.length"
              type="button"
              class="button button--primary"
              :disabled="store.busy"
              data-testid="commander-claim-all-btn"
              @click="handleClaim(undefined, true)"
            >一键领取全部（{{ inspected.claimable_levels.length }}）</button>
          </div>
          <ol class="cmd-track">
            <li
              v-for="row in inspected.reward_track"
              :key="row.level"
              class="cmd-track__item"
              :class="{
                'is-milestone': Boolean(row.milestone_tier),
                'is-claimed': row.claimed,
                'is-claimable': row.claimable,
              }"
              :data-testid="'commander-reward-lvl-' + row.level"
            >
              <span class="cmd-track__lvl">Lv.{{ row.level }}</span>
              <div class="cmd-track__info">
                <b>{{ row.label }}</b>
                <small>{{ row.summary }}</small>
              </div>
              <div class="cmd-track__cta">
                <span v-if="row.claimed" class="cmd-claimed-tag">已领取</span>
                <button
                  v-else-if="row.claimable"
                  type="button"
                  class="button button--primary"
                  :disabled="store.busy"
                  :data-testid="'commander-claim-btn-' + row.level"
                  @click="handleClaim(row.level, false)"
                >领取</button>
                <span v-else class="cmd-locked-tag">未达成</span>
              </div>
            </li>
          </ol>
        </section>

        <section v-else class="cmd-loadout" data-testid="commander-loadout-panel">
          <div class="cmd-loadout__group">
            <h4>角色装配槽位</h4>
            <div class="cmd-loadout__slots">
              <div class="cmd-slot">
                <label>立绘版本</label>
                <div class="cmd-slot__opts">
                  <button
                    v-for="p in ['base', 'ascended', 'alt', 'ultimate']"
                    :key="p"
                    type="button"
                    class="cmd-opt-btn"
                    :class="{ 'is-picked': inspected.equipped.portrait === p }"
                    :disabled="!inspected.owned || !inspected.unlocked_options.portraits.includes(p)"
                    @click="handleEquip('portrait', p)"
                  >{{ portraitLabel(p) }}</button>
                </div>
              </div>
              <div class="cmd-slot">
                <label>登场动画 & 技能特效 & 胜利动作</label>
                <div class="cmd-slot__opts">
                  <button
                    v-for="intro in ['base', 'enhanced', 'ultimate']"
                    :key="intro"
                    type="button"
                    class="cmd-opt-btn"
                    :class="{ 'is-picked': inspected.equipped.intro === intro }"
                    :disabled="!inspected.owned || !inspected.unlocked_options.intros.includes(intro)"
                    @click="handleEquip('intro', intro)"
                  >登场:{{ intro === 'base' ? '基础' : intro === 'enhanced' ? '15级强化' : '20级顶配' }}</button>
                  <button
                    type="button"
                    class="cmd-opt-btn"
                    :class="{ 'is-picked': inspected.equipped.skill_vfx === 'exclusive' }"
                    :disabled="!inspected.owned || !inspected.unlocked_options.skill_vfx.includes('exclusive')"
                    @click="handleEquip('skill_vfx', inspected.equipped.skill_vfx === 'exclusive' ? 'base' : 'exclusive')"
                  >15级技能特效</button>
                  <button
                    type="button"
                    class="cmd-opt-btn"
                    :class="{ 'is-picked': inspected.equipped.victory_motion === 'exclusive' }"
                    :disabled="!inspected.owned || !inspected.unlocked_options.victory_motions.includes('exclusive')"
                    @click="handleEquip('victory_motion', inspected.equipped.victory_motion === 'exclusive' ? 'base' : 'exclusive')"
                  >13级胜利动作</button>
                </div>
              </div>
            </div>
          </div>

          <div class="cmd-loadout__group">
            <h4>专属头像与表情贴纸</h4>
            <div class="cmd-emoji-grid">
              <div class="cmd-emoji-card">
                <img :src="commanderAvatarUrl(inspected.id)" alt="专属头像" />
                <span>5级专属头像</span>
              </div>
              <div v-for="ek in ['emoji_1', 'emoji_2', 'emoji_3', 'emoji_dynamic']" :key="ek" class="cmd-emoji-card">
                <img :src="commanderEmojiUrl(inspected.id, ek)" :alt="ek" />
                <span>{{ ek === 'emoji_dynamic' ? '16级动态表情' : '表情' }}</span>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.cmd-page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 18px 16px 64px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.cmd-page__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  padding: 16px 20px;
  border-radius: 16px;
  border: 1px solid rgb(56 189 248 / 28%);
  background: linear-gradient(135deg, rgb(10 22 40 / 94%), rgb(15 29 52 / 94%));
  box-shadow: 0 12px 28px rgb(8 19 36 / 16%);
}
.cmd-page__kicker {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.14em;
  color: #7dd3fc;
}
.cmd-page__head h1 {
  margin: 0;
  font-size: 28px;
  color: #f4f9ff;
}
.cmd-page__lead {
  margin: 4px 0 0;
  font-size: 13px;
  color: #c2d6eb;
}
.cmd-page__economy {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.cmd-stat-pill {
  padding: 8px 14px;
  border-radius: 12px;
  border: 1px solid rgb(125 211 252 / 28%);
  background: rgb(6 15 28 / 86%);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cmd-stat-pill span {
  font-size: 11px;
  color: #9bc0dc;
}
.cmd-stat-pill b {
  font-size: 16px;
  color: #fde68a;
}
.cmd-free-banner {
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid rgb(250 204 21 / 56%);
  background: linear-gradient(90deg, rgb(32 23 8 / 92%), rgb(48 34 10 / 90%));
  color: #fef08a;
  font-size: 13px;
}
.cmd-roster {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
@media (max-width: 820px) {
  .cmd-roster {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.cmd-card {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border-radius: 14px;
  border: 1px solid rgb(148 163 184 / 24%);
  background: rgb(10 22 39 / 84%);
  color: #e2e8f0;
  text-align: left;
  cursor: pointer;
}
.cmd-card.is-active {
  border-color: var(--cmd-acc);
  box-shadow: 0 0 0 1px var(--cmd-pri), 0 10px 24px rgb(0 0 0 / 34%);
  background: linear-gradient(145deg, color-mix(in srgb, var(--cmd-pri) 22%, #091627), rgb(7 16 30 / 92%));
}
.cmd-card.is-locked {
  opacity: 0.78;
}
.cmd-card__thumb {
  width: 52px;
  height: 68px;
  border-radius: 10px;
  object-fit: cover;
  border: 1px solid var(--cmd-pri);
  flex-shrink: 0;
}
.cmd-card__info {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cmd-card__top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.cmd-card__gender {
  font-size: 11px;
  color: #94a3b8;
}
.cmd-badge {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10px;
  background: rgb(59 130 246 / 22%);
  color: #bae6fd;
}
.cmd-badge--gold {
  background: linear-gradient(90deg, #facc15, #f59e0b);
  color: #161005;
  font-weight: 700;
}
.cmd-badge--free {
  background: #22c55e;
  color: #052e16;
  font-weight: 700;
}
.cmd-badge--locked {
  background: rgb(148 163 184 / 20%);
  color: #cbd5e1;
}
.cmd-card__tagline {
  font-size: 11px;
  color: #9bb8d3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-card__bar {
  height: 5px;
  border-radius: 999px;
  background: rgb(255 255 255 / 10%);
  overflow: hidden;
}
.cmd-card__bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--cmd-pri), var(--cmd-acc));
}
.cmd-card__claim-dot {
  font-size: 10px;
  color: #fde047;
  font-weight: 700;
}
.cmd-stage {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  padding: 18px;
  border-radius: 18px;
  border: 1px solid color-mix(in srgb, var(--cmd-pri) 42%, transparent);
  background: linear-gradient(155deg, rgb(9 22 39 / 90%), rgb(7 14 26 / 95%));
}
@media (max-width: 900px) {
  .cmd-stage {
    grid-template-columns: 1fr;
  }
}
.cmd-stage__art {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cmd-stage__portrait-box {
  position: relative;
  border-radius: 16px;
  overflow: hidden;
  border: 1.5px solid var(--cmd-acc);
}
.cmd-stage__portrait-stage {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
}
.cmd-forms-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.cmd-form-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px;
  border-radius: 10px;
  border: 1px solid rgb(148 163 184 / 24%);
  background: rgb(11 23 40 / 84%);
  color: #cbd5e1;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease;
}
.cmd-form-card.is-current {
  border-color: var(--cmd-acc);
  background: color-mix(in srgb, var(--cmd-pri) 22%, #0c1b2e);
}
.cmd-form-card__img {
  width: 36px;
  height: 48px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
  border: 1px solid rgb(148 163 184 / 30%);
}
.cmd-form-card__meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.cmd-form-card__meta b {
  font-size: 11px;
  color: #f1f5f9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-form-card__badge {
  display: inline-block;
  align-self: flex-start;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10px;
  background: rgb(148 163 184 / 20%);
  color: #cbd5e1;
}
.cmd-form-card.is-tone-equipped .cmd-form-card__badge {
  background: linear-gradient(90deg, #facc15, #f59e0b);
  color: #161005;
  font-weight: 700;
}
.cmd-form-card.is-tone-claimed .cmd-form-card__badge {
  background: rgb(34 197 94 / 22%);
  color: #86efac;
}
.cmd-form-card.is-tone-claimable .cmd-form-card__badge {
  background: rgb(56 189 248 / 24%);
  color: #bae6fd;
}
.cmd-motion-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 9px 10px;
  border-radius: 10px;
  border: 1px solid rgb(148 163 184 / 20%);
  background: rgb(9 20 35 / 80%);
}
.cmd-motion-preview__tiers,
.cmd-motion-preview__actions {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}
.cmd-motion-preview__tiers span {
  font-size: 11px;
  color: #93b5d1;
}
.cmd-motion-preview__hint {
  font-size: 10.5px;
  color: #7da1c4;
}
.cmd-stage__tier-tag {
  position: absolute;
  top: 10px;
  left: 10px;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgb(5 12 24 / 82%);
  border: 1px solid var(--cmd-acc);
  color: var(--cmd-acc);
  font-size: 11px;
  font-weight: 700;
}
.cmd-stage__variants {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.cmd-var-btn {
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid rgb(148 163 184 / 26%);
  background: rgb(11 23 40 / 82%);
  color: #cbd5e1;
  font-size: 11px;
  cursor: pointer;
}
.cmd-var-btn.is-current {
  border-color: var(--cmd-acc);
  color: #fffbeb;
  background: color-mix(in srgb, var(--cmd-pri) 26%, #0c1b2e);
}
.cmd-stage__detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cmd-stage__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.cmd-stage__header h2 {
  margin: 0;
  font-size: 24px;
  color: #fff;
}
.cmd-stage__traits {
  margin: 4px 0 0;
  font-size: 12px;
  color: #9cc1de;
}
.cmd-active-pill {
  display: inline-block;
  padding: 7px 14px;
  border-radius: 999px;
  background: rgb(250 204 21 / 20%);
  border: 1px solid #facc15;
  color: #fde68a;
  font-size: 12px;
  font-weight: 700;
}
.cmd-feedback {
  margin: 0;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgb(56 189 248 / 15%);
  color: #bae6fd;
  font-size: 12px;
}
.cmd-xp-box {
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid rgb(148 163 184 / 22%);
  background: rgb(11 23 42 / 75%);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cmd-xp-box__top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: #e2e8f0;
  flex-wrap: wrap;
}
.cmd-xp-box__bar {
  height: 8px;
  border-radius: 999px;
  background: rgb(255 255 255 / 12%);
  overflow: hidden;
}
.cmd-xp-box__bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--cmd-pri), var(--cmd-acc));
}
.cmd-xp-box small {
  font-size: 11px;
  color: #93b5d1;
}
.cmd-skill-panel {
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--cmd-acc) 35%, transparent);
  background: rgb(14 28 48 / 80%);
}
.cmd-skill-panel__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cmd-skill-panel__head h3 {
  margin: 0;
  font-size: 15px;
  color: #fde68a;
}
.cmd-skill-panel__chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgb(255 255 255 / 10%);
  color: #cde8fc;
  font-size: 11px;
}
.cmd-skill-panel__timing {
  margin: 6px 0 4px;
  font-size: 12px;
  color: #7dd3fc;
}
.cmd-skill-panel__desc {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #e6f2fc;
}
.cmd-tabs {
  display: flex;
  gap: 8px;
}
.cmd-tabs button {
  padding: 7px 14px;
  border-radius: 10px;
  border: 1px solid rgb(148 163 184 / 26%);
  background: rgb(11 22 40 / 76%);
  color: #b7cde0;
  font-size: 13px;
  cursor: pointer;
}
.cmd-tabs button.is-active {
  border-color: var(--cmd-acc);
  color: #ffffff;
  background: color-mix(in srgb, var(--cmd-pri) 24%, #0f2038);
}
.cmd-rewards__toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 12px;
  color: #9ec0dc;
}
.cmd-track {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
  max-height: 420px;
  overflow-y: auto;
}
.cmd-track__item {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid rgb(148 163 184 / 18%);
  background: rgb(10 21 38 / 74%);
}
.cmd-track__item.is-milestone {
  border-color: rgb(250 204 21 / 46%);
  background: linear-gradient(90deg, rgb(250 204 21 / 12%), rgb(10 21 38 / 84%));
}
.cmd-track__item.is-claimable {
  border-color: #38bdf8;
}
.cmd-track__lvl {
  font-size: 13px;
  font-weight: 700;
  color: var(--cmd-acc);
}
.cmd-track__info b {
  display: block;
  font-size: 13px;
  color: #f1f5f9;
}
.cmd-track__info small {
  font-size: 11px;
  color: #93b5d1;
}
.cmd-claimed-tag {
  font-size: 12px;
  color: #4ade80;
}
.cmd-locked-tag {
  font-size: 12px;
  color: #64748b;
}
.cmd-loadout {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.cmd-loadout__group h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #fde68a;
}
.cmd-loadout__slots {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cmd-slot {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.cmd-slot label {
  font-size: 12px;
  color: #9cc1de;
}
.cmd-slot__opts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.cmd-opt-btn {
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid rgb(148 163 184 / 26%);
  background: rgb(11 23 41 / 82%);
  color: #e2e8f0;
  font-size: 12px;
  cursor: pointer;
}
.cmd-opt-btn.is-picked {
  border-color: #facc15;
  color: #fef08a;
  background: rgb(234 179 84 / 18%);
}
.cmd-opt-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.cmd-emoji-grid {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.cmd-emoji-card {
  width: 78px;
  padding: 6px;
  border-radius: 10px;
  background: rgb(10 21 38 / 82%);
  border: 1px solid rgb(148 163 184 / 22%);
  text-align: center;
}
.cmd-emoji-card img {
  width: 56px;
  height: 56px;
  display: block;
  margin: 0 auto 4px;
}
.cmd-emoji-card span {
  font-size: 10px;
  color: #cbd5e1;
}
</style>
