<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'
const auth = useAuthStore()
const subject = ref('privacy'), contact = ref(''), message = ref(''), busy = ref(false), result = ref(''), error = ref('')
function newRequestId(): string { return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}` }
let requestId = newRequestId()
async function submit(): Promise<void> {
  if (busy.value) return
  busy.value = true; result.value = ''; error.value = ''
  try {
    const response = await fetch('/api/operator-contact', {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({request_id:requestId,subject:subject.value,contact:contact.value,message:message.value})})
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.reason || '暂时无法投递')
    result.value = `已送达运营邮箱。请求编号：${requestId}。${auth.isGuest ? '运营者将通过你留下的邮箱回复。' : '请留意站内邮箱回复。'}`
    message.value = ''; requestId = newRequestId()
  } catch(reason) { error.value = reason instanceof Error ? reason.message : '提交失败，请稍后重试' }
  finally { busy.value = false }
}
</script>
<template>
  <form class="operator-contact" data-testid="operator-contact" @submit.prevent="submit"><h2>联系运营者</h2><p>账号、隐私、申诉及游戏问题由唯一运营管理员处理。请勿填写密码、验证码或身份证件；我们会先核验身份，再处理涉及账号的数据申请。</p><label>事项<select v-model="subject"><option value="privacy">隐私与账号申请</option><option value="bug">问题反馈</option><option value="appeal">申诉</option><option value="other">其他事项</option></select></label><label>回复邮箱{{ auth.isGuest ? '（必填）' : '（可留空，默认站内回复）' }}<input v-model="contact" type="email" :required="auth.isGuest" maxlength="150" /></label><label>具体说明<textarea v-model="message" required minlength="5" maxlength="2000" rows="4" /></label><button class="button button--primary" :disabled="busy">{{ busy ? '投递中…' : '提交给运营者' }}</button><p v-if="result" role="status">{{ result }}</p><p v-if="error" role="alert">{{ error }}</p></form>
</template>
<style scoped>
.operator-contact{display:grid;gap:14px;scroll-margin-top:24px}.operator-contact h2,.operator-contact p{margin:0}.operator-contact label{display:grid;gap:7px;font-size:14px}.operator-contact input,.operator-contact select,.operator-contact textarea{box-sizing:border-box;width:100%;min-width:0;font:inherit;color:var(--text-primary);background:var(--surface-sea);border:1px solid var(--border-subtle);border-radius:6px;padding:12px}.operator-contact p{font-size:13px;line-height:1.8;overflow-wrap:anywhere}.operator-contact button{justify-self:start}
</style>
