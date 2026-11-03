<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useMailboxStore, type PlayerMail, type MailAttachment } from '../../stores/mailbox'
const auth = useAuthStore()
const mail = useMailboxStore()
const selectedId = ref('')
const selected = computed(() => mail.items.find(item => item.id === selectedId.value) || null)
function date(value: number): string { return new Date(value * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }
function attachment(item: MailAttachment): string { return item.kind === 'tide_ash' ? `${item.amount} 潮汐徽记` : item.name || item.reward_id || '外观奖励' }
async function select(item: PlayerMail): Promise<void> {
  selectedId.value = item.id
  if (item.unread) await mail.act(item.id, 'read')
}
onMounted(() => { if (!auth.isGuest) void mail.load() })
</script>

<template>
  <section class="mail-page" data-testid="mailbox-screen" aria-labelledby="mailbox-title">
    <header class="mail-page__head"><div><h1 id="mailbox-title">舰长邮箱</h1><p>赛季嘉奖、海域来信，都在这里。</p></div><button class="button button--ghost" :disabled="mail.loading || !!mail.busy" data-testid="mailbox-refresh" @click="mail.load()">刷新</button></header>
    <div v-if="auth.isGuest" class="mail-empty"><h2>登录后查收你的来信</h2><button class="button" @click="auth.open('login', '登录后查看邮箱')">登录 / 注册</button></div>
    <template v-else>
      <p v-if="mail.error" role="alert" class="mail-error">{{ mail.error }}</p>
      <p class="mail-page__note">{{ mail.unclaimedCount }} 封待领附件 · {{ mail.unreadCount }} 封未读。普通邮件 30 天过期，领取后保留 7 天；赛季附件请以信中期限为准。</p>
      <div class="mail-layout">
        <div class="mail-list" aria-label="邮件列表" data-testid="mailbox-list">
          <p v-if="mail.loading && !mail.items.length" class="mail-empty" role="status">正在接收来信…</p>
          <div v-else-if="!mail.items.length" class="mail-empty"><span class="mail-empty__icon" aria-hidden="true">✉</span><h2>暂时没有来信</h2><p>新的赛季奖励与运营通知会送达这里。</p></div>
          <button v-for="item in mail.items" :key="item.id" class="mail-list__item" :class="{ 'is-selected': selectedId === item.id, 'is-unread': item.unread }" :aria-pressed="selectedId === item.id" :data-mail-id="item.id" @click="select(item)">
            <span class="mail-list__title">{{ item.title }}<i v-if="item.unread" aria-label="未读"></i></span>
            <small>{{ date(item.created_at) }}</small><span class="mail-list__status">{{ item.can_claim ? '有附件待领取' : item.claimed_at ? '附件已领取' : item.attachments.length ? '附件已过期' : '通知' }}</span>
          </button>
        </div>
        <article class="mail-letter" data-testid="mailbox-detail">
          <template v-if="selected">
            <header><h2>{{ selected.title }}</h2><p>{{ date(selected.created_at) }}</p></header>
            <p class="mail-letter__body">{{ selected.body }}</p>
            <section v-if="selected.attachments.length" class="mail-letter__attachments" aria-label="邮件附件"><h3>随信附件</h3><ul><li v-for="(item, index) in selected.attachments" :key="index">{{ attachment(item) }}</li></ul><p>{{ selected.claimed_at ? '已领取，邮件将在领取后 7 天移出邮箱。' : `领取截止：${date(selected.attachment_expires_at)}（沪时）` }}</p></section>
            <footer><button v-if="selected.attachments.length" class="button button--primary" data-testid="mailbox-claim" :disabled="!selected.can_claim || !!mail.busy" @click="mail.act(selected.id, 'claim')">{{ mail.busy ? '处理中…' : selected.claimed_at ? '已领取' : selected.can_claim ? '领取附件' : '附件已过期' }}</button><button class="button button--ghost" data-testid="mailbox-delete" :disabled="!selected.can_delete || !!mail.busy" @click="mail.act(selected.id, 'delete')">删除邮件</button><router-link v-if="selected.claimed_at" :to="{ name: 'profile' }">前往名片装备外观</router-link></footer>
          </template>
          <div v-else class="mail-empty"><h2>选择一封来信</h2><p>查看正文后，再领取随信奖励。</p></div>
        </article>
      </div>
    </template>
    <footer class="mail-page__foot"><router-link :to="{ name: 'lobby' }">返回大厅</router-link><router-link :to="{ name: 'terms' }">用户协议</router-link><router-link :to="{ name: 'privacy' }">隐私政策</router-link></footer>
  </section>
</template>

<style scoped>
.mail-page { --text-strong:var(--text-primary); }
.mail-page { width:min(1180px,100%); margin:0 auto; padding:clamp(16px,3vw,36px); box-sizing:border-box; color:var(--text-strong); }
.mail-page__head { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.mail-page h1 { margin:0; font-size:clamp(26px,4vw,34px); }.mail-page h2 { font-size:20px; }.mail-page p { line-height:1.7; }
.mail-page__head p,.mail-page__note,.mail-letter header p,.mail-letter__attachments p { color:var(--text-muted); font-size:14px; }
.mail-layout { display:grid; grid-template-columns:minmax(240px,320px) minmax(0,1fr); border:1px solid var(--border-subtle); border-radius:14px; overflow:hidden; background:var(--surface-sea); min-height:430px; }
.mail-list { min-width:0; border-right:1px solid var(--border-subtle); }.mail-list__item { display:grid; gap:8px; width:100%; padding:20px; text-align:left; color:inherit; border:0; border-bottom:1px solid var(--border-subtle); background:transparent; cursor:pointer; overflow-wrap:anywhere; }
.mail-list__item.is-selected { background:color-mix(in srgb,var(--accent) 13%,transparent); box-shadow:inset 3px 0 var(--accent); }.mail-list__title { font-weight:600; display:flex; align-items:center; gap:8px; }.mail-list__title i { width:6px; height:6px; flex:none; border-radius:50%; background:var(--accent); }.mail-list small { color:var(--text-muted); }.mail-list__status { font-size:12px; color:var(--accent); }
.mail-letter { min-width:0; padding:clamp(18px,3vw,32px); }.mail-letter header { border-bottom:1px solid var(--border-subtle); padding-bottom:14px; }.mail-letter__body { white-space:pre-wrap; overflow-wrap:anywhere; min-height:96px; }.mail-letter__attachments { padding:16px 20px; border:1px solid var(--border-subtle); border-radius:8px; }.mail-letter__attachments h3 { margin:0 0 12px; font-size:15px; }.mail-letter ul { padding-left:20px; line-height:2; }.mail-letter footer { display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-top:24px; }.mail-letter footer a { font-size:13px; }
.mail-empty { padding:32px 20px; text-align:center; color:var(--text-muted); }.mail-empty h2 { color:var(--text-strong); }.mail-empty__icon { display:block; font-size:42px; color:var(--accent); }.mail-empty .button { margin-top:14px; }.mail-error { color:var(--danger); }.mail-page__foot { display:flex; flex-wrap:wrap; justify-content:center; gap:24px; padding:24px 0; font-size:13px; }
@media(max-width:640px) { .mail-layout { grid-template-columns:minmax(0,1fr); }.mail-list { border-right:0; border-bottom:1px solid var(--border-subtle); }.mail-list__item { padding:16px; }.mail-page__note { font-size:12px; } }
</style>
