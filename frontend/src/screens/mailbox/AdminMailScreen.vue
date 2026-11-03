<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
interface Cosmetic { kind: string; reward_id: string; name: string }
const allowed = ref(false)
const checking = ref(true)
const busy = ref(false)
const error = ref('')
const success = ref('')
const title = ref('')
const body = ref('')
const scope = ref<'all' | 'single' | 'condition'>('single')
const recipient = ref('')
function dispatchKey(): string { return globalThis.crypto?.randomUUID?.() || `mail-${Date.now()}-${Math.random().toString(36).slice(2)}` }
const sourceKey = ref(dispatchKey())
const tide = ref(0)
const minTier = ref<number | ''>('')
const maxTier = ref<number | ''>('')
const minLevel = ref<number | ''>('')
const maxLevel = ref<number | ''>('')
const catalog = ref<Cosmetic[]>([])
const selected = ref<string[]>([])
const titles = ['二级水手', '一级水手', '水手长', '三副', '二副', '大副', '轮机长', '船长', '大舰长']
const kindNames: Record<string, string> = { title: '称号', frame: '头像框', card_bg: '名片底色', profile_bg: '资料背景', pointer: '指针特效', title_fx: '称号特效' }
const scopeText = computed(() => scope.value === 'all' ? '当前全部账号' : scope.value === 'single' ? `账号 ${recipient.value || '未填写'}` : '符合下方筛选条件的账号')
onMounted(async () => {
  try {
    const response = await fetch('/api/admin/mailbox/catalog')
    if (!response.ok) throw new Error(response.status === 403 || response.status === 401 ? '仅管理员可使用运营发信' : '附件目录读取失败')
    catalog.value = (await response.json()).items
    allowed.value = true
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '无法读取管理权限' }
  finally { checking.value = false }
})
async function send(): Promise<void> {
  if (busy.value || !allowed.value) return
  busy.value = true; error.value = ''; success.value = ''
  const audience: Record<string, string | number> = { kind: scope.value }
  if (scope.value === 'single') audience.user_id = recipient.value.trim()
  if (scope.value === 'condition') {
    for (const [key, value] of Object.entries({ min_rank_tier: minTier.value, max_rank_tier: maxTier.value, min_level: minLevel.value, max_level: maxLevel.value })) {
      if (value !== '') audience[key] = value
    }
  }
  const attachments: Array<Record<string, string | number>> = tide.value > 0 ? [{ kind: 'tide_ash', amount: tide.value }] : []
  for (const key of selected.value) {
    const item = catalog.value.find(item => `${item.kind}:${item.reward_id}` === key)
    if (item) attachments.push({ kind: item.kind, reward_id: item.reward_id })
  }
  try {
    const response = await fetch('/api/admin/mailbox/send', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ title: title.value, body: body.value, audience, attachments, source_key: sourceKey.value }) })
    const result = await response.json()
    if (!response.ok || !result.ok) throw new Error(result.reason || '投递失败')
    success.value = result.already_sent ? '这批邮件已发送，不会重复投递。' : `已向 ${result.delivered} 个账号投递。附件由收件人主动领取。`
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '投递失败' }
  finally { busy.value = false }
}
function newDispatch(): void { sourceKey.value = dispatchKey(); success.value = '' }
</script>
<template>
  <section class="admin-mail" data-testid="admin-mail-screen"><header><div><h1>运营发信</h1><p>公告、补偿与奖励统一投递到玩家邮箱。</p></div><router-link :to="{ name: 'mailbox' }">返回邮箱</router-link></header><p v-if="checking" role="status">正在核验管理员身份…</p><p v-if="error" role="alert">{{ error }}</p><p v-if="success" role="status" data-testid="admin-mail-success">{{ success }}</p>
    <form v-if="allowed" @submit.prevent="send">
      <fieldset :disabled="busy"><legend>收件人</legend><label>收件范围<select v-model="scope" data-testid="admin-mail-scope"><option value="single">单个玩家</option><option value="condition">条件群发</option><option value="all">全员群发</option></select></label><label v-if="scope === 'single'">玩家账号 ID<input v-model="recipient" required data-testid="admin-mail-recipient" /></label><div v-if="scope === 'condition'" class="admin-mail__grid"><label>最低段位<select v-model="minTier"><option value="">不限</option><option v-for="(name, i) in titles" :key="i" :value="i">{{ name }}</option></select></label><label>最高段位<select v-model="maxTier"><option value="">不限</option><option v-for="(name, i) in titles" :key="i" :value="i">{{ name }}</option></select></label><label>最低等级<input v-model.number="minLevel" type="number" min="1" max="101" /></label><label>最高等级<input v-model.number="maxLevel" type="number" min="1" max="101" /></label></div></fieldset>
      <fieldset :disabled="busy"><legend>来信内容</legend><label>标题<input v-model="title" maxlength="80" required data-testid="admin-mail-title" /></label><label>正文<textarea v-model="body" maxlength="5000" rows="6" required data-testid="admin-mail-body"></textarea></label></fieldset>
      <fieldset :disabled="busy"><legend>随信附件（可选）</legend><label>潮汐徽记<input v-model.number="tide" type="number" min="0" max="100000" data-testid="admin-mail-tide" /></label><label>外观与称号（可多选，最多合计 10 项附件）<select v-model="selected" multiple size="6"><option v-for="item in catalog" :key="`${item.kind}:${item.reward_id}`" :value="`${item.kind}:${item.reward_id}`">{{ kindNames[item.kind] }} · {{ item.name }}</option></select></label></fieldset>
      <p>将投递给：<strong>{{ scopeText }}</strong>。普通邮件与附件在发送后 30 天过期。</p><label>发送编号<input v-model="sourceKey" required maxlength="100" data-testid="admin-mail-key" /></label><p class="admin-mail__hint">失败重试沿用同一编号，避免重复发奖；发送另一批前，请生成新编号。</p><footer><button type="submit" class="button button--primary" :disabled="busy" data-testid="admin-mail-send">{{ busy ? '投递中…' : '确认投递邮件' }}</button><button type="button" class="button button--ghost" :disabled="busy" @click="newDispatch">生成新发送编号</button></footer>
    </form>
  </section>
</template>
<style scoped>
.admin-mail { --text-strong:var(--text-primary); --surface-deep:var(--surface-deck); }
.admin-mail { width:min(900px,100%); box-sizing:border-box; padding:clamp(18px,4vw,36px); margin:auto; color:var(--text-strong); }.admin-mail header { display:flex; justify-content:space-between; flex-wrap:wrap; gap:12px; align-items:center; }.admin-mail h1 { margin:0; }.admin-mail p { color:var(--text-muted); line-height:1.7; }.admin-mail fieldset { padding:20px; margin:20px 0; border:1px solid var(--border-subtle); border-radius:10px; background:var(--surface-sea); min-width:0; }.admin-mail label { display:grid; gap:9px; margin:14px 0; font-size:14px; }.admin-mail input,.admin-mail select,.admin-mail textarea { box-sizing:border-box; width:100%; min-width:0; padding:11px; background:var(--surface-deep); border:1px solid var(--border-subtle); color:var(--text-strong); border-radius:6px; font:inherit; }.admin-mail textarea { resize:vertical; }.admin-mail__grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 16px; }.admin-mail__hint { font-size:13px; }.admin-mail footer { display:flex; flex-wrap:wrap; gap:12px; padding:12px 0 28px; }
</style>
