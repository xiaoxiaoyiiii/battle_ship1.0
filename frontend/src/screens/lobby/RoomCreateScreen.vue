<script setup lang="ts">
import { computed, ref } from 'vue'
import { useLobbyStore } from '../../stores/lobby'
import { useAuthStore } from '../../stores/auth'
import { useRoomDraftStore } from '../../stores/roomDraft'
import { useLobbyActions } from './useLobbyActions'
import MutationPicker from './MutationPicker.vue'

const lobby = useLobbyStore()
const auth = useAuthStore()
const draft = useRoomDraftStore()
const actions = useLobbyActions()
const pickerOpen = ref(false)
const weekly = computed(() => lobby.snapshot?.weeklyMutations ?? null)
const selected = computed(() => weekly.value?.catalog.filter(e => draft.mutationIds.includes(e.id)) ?? [])
function confirmMutations(ids: string[]): void { draft.mutationIds = ids; pickerOpen.value = false }
</script>
<template>
  <section class="lp-page" data-testid="screen-room-create" aria-labelledby="room-create-title">
    <router-link :to="{ name: 'lobby' }" class="lp-back">‹ 返回游戏大厅</router-link>
    <header class="lp-pagehead"><div><h1 id="room-create-title">创建房间</h1><p>设置这一局的玩法，然后邀请一位对手。</p></div></header>
    <p v-if="lobby.ownRoomId" class="lp-own-banner">你已有等待中的房间。<router-link class="button" :to="{ name: 'lobby-room' }">返回我的房间</router-link></p>
    <form class="lp-create-layout" @submit.prevent="actions.createRoom()"><div class="lp-stack">
      <section class="lp-panel"><div class="lp-panelbody"><h2>房间信息</h2><div class="lp-field"><label for="room-name" class="lp-label">房间名称 <small>可留空</small></label><input id="room-name" v-model="draft.name" class="lp-input" data-testid="lobby-room-name" maxlength="20" placeholder="例如：来试试你的新战术"><p class="lp-help">留空时使用你的玩家名，最多 20 个字。</p></div><fieldset class="lp-field lp-fieldset"><legend class="lp-label">谁可以找到这个房间</legend><div class="lp-choices"><button type="button" class="lp-choice" :class="{ 'is-selected': draft.isPublic }" data-testid="room-visibility-public" :aria-pressed="draft.isPublic" @click="draft.isPublic = true"><span class="lp-choice-icon" aria-hidden="true">◎</span><span><b>公开房间</b><small>显示在大厅，任何玩家可加入</small></span><span class="lp-radio"></span></button><button type="button" class="lp-choice" :class="{ 'is-selected': !draft.isPublic }" data-testid="room-visibility-private" :aria-pressed="!draft.isPublic" @click="draft.isPublic = false"><span class="lp-choice-icon" aria-hidden="true">◇</span><span><b>私密房间</b><small>仅凭邀请链接或好友邀请加入</small></span><span class="lp-radio"></span></button></div></fieldset></div></section>
      <section class="lp-panel" data-testid="room-rules"><div class="lp-panelbody"><h2>本局规则</h2><p class="lp-help">保留默认设置即可开始一场普通自定义对局。</p><div class="lp-setting"><label for="room-ban"><b>赛前 Ban 卡</b><small>双方先禁牌，再进入布船。默认关闭。</small></label><input id="room-ban" v-model="draft.banEnabled" class="lp-switch" data-testid="lobby-ban-enabled" type="checkbox"></div><div v-if="draft.banEnabled" class="lp-ban-detail"><label for="room-ban-quota">每人禁用卡牌</label><span><select id="room-ban-quota" v-model.number="draft.banQuota" data-testid="lobby-ban-quota"><option v-for="n in 10" :key="n" :value="n">{{ n }}</option></select> 张</span><p class="lp-help">双方同 Ban 不顺延；「失灵！」不可 Ban。</p></div><button type="button" class="lp-mutations-open" data-testid="room-mutations-open" :disabled="!weekly" @click="pickerOpen = true"><span class="lp-choice-icon" aria-hidden="true">✧</span><span><b>自定义突变</b><small>{{ weekly ? '自由搭配词条，调整这一局的玩法' : '正在载入本周词条…' }}</small></span><span class="lp-tag">{{ draft.mutationIds.length }} 条</span><span aria-hidden="true">›</span></button><div v-if="selected.length" class="lp-chips"><span v-for="entry in selected" :key="entry.id" class="lp-chip">{{ entry.name }}</span></div></div></section>
    </div><aside class="lp-panel lp-summary" data-testid="room-summary"><div class="lp-panelbody"><div class="lp-summary-top"><span class="lp-tag lp-tag--cyan">自定义对战</span><span>1v1 · 不计排位分</span></div><h2>{{ draft.name.trim() || `${auth.displayName}的房间` }}</h2><div class="lp-duel"><div><span class="lp-avatar">{{ Array.from(auth.displayName)[0] }}</span><small>你 · 房主</small></div><b class="lp-vs">VS</b><div><span class="lp-avatar lp-avatar--empty">＋</span><small>等待对手</small></div></div><dl class="lp-rules"><div><dt>加入方式</dt><dd>{{ draft.isPublic ? '大厅公开' : '邀请链接／好友邀请' }}</dd></div><div><dt>赛前 Ban</dt><dd>{{ draft.banEnabled ? `每人 ${draft.banQuota} 张` : '关闭' }}</dd></div><div><dt>突变词条</dt><dd>{{ selected.length ? selected.map(e => e.name).join('、') : '无' }}</dd></div></dl><p v-if="actions.creationError.value" class="lp-conflict" role="alert">{{ actions.creationError.value }}</p><div class="lp-create-action"><button type="submit" class="button lp-primary" data-testid="room-create-submit" :disabled="actions.createPending.value || !!actions.creationError.value || !lobby.connected || !!lobby.ownRoomId">{{ actions.createPending.value ? '创建中…' : '创建房间' }}</button></div><p class="lp-help lp-center">创建后可复制邀请链接</p></div><p class="lp-summary-foot">自定义房退出不计排位逃跑扣分。</p></aside></form>
    <MutationPicker :open="pickerOpen" :selected="draft.mutationIds" :weekly="weekly" @close="pickerOpen = false" @confirm="confirmMutations" />
  </section>
</template>
