<script setup lang="ts">
import { computed } from 'vue'
import OperatorContact from '../../components/OperatorContact.vue'
import { TERMS, PRIVACY, LEGAL_VERSION, EFFECTIVE_AT } from './legalContent'
const props = defineProps<{ kind: 'terms' | 'privacy' }>()
const title = computed(() => props.kind === 'terms' ? '用户协议' : '隐私政策')
const sections = computed(() => props.kind === 'terms' ? TERMS : PRIVACY)
</script>
<template>
  <main class="legal" data-testid="legal-screen" :data-kind="kind">
    <header class="legal__head"><router-link :to="{name:'settings'}">‹ 返回设置</router-link><span class="legal__eyebrow">战舰棋 · 服务说明</span><h1 data-testid="legal-heading">{{ title }}</h1><p>版本 {{ LEGAL_VERSION }} · 生效时间：{{ EFFECTIVE_AT }}</p><nav aria-label="服务文件"><router-link to="/terms" :aria-current="kind === 'terms' ? 'page' : undefined">用户协议</router-link><router-link to="/privacy" :aria-current="kind === 'privacy' ? 'page' : undefined">隐私政策</router-link><a href="#operator-contact">联系运营者</a></nav></header>
    <p class="legal__intro">请仔细阅读以下说明。涉及账号安全、奖励截止、公开范围与个人信息权利的内容，请结合当前游戏内提示一并查看。</p>
    <div class="legal__layout"><aside aria-label="本文目录"><a v-for="section in sections" :key="section.id" :href="'#'+section.id">{{ section.title }}</a></aside><article><section v-for="section in sections" :id="section.id" :key="section.id"><h2>{{ section.title }}</h2><p v-for="(paragraph,index) in section.paragraphs" :key="index">{{ paragraph }}</p></section><section id="operator-contact"><OperatorContact /></section></article></div>
    <footer><router-link to="/lobby">返回大厅</router-link><router-link :to="{name:'settings'}">返回设置</router-link></footer>
  </main>
</template>
<style scoped>
.legal{max-width:1050px;padding:clamp(20px,4vw,48px);box-sizing:border-box;margin:auto;color:var(--text-primary);line-height:1.95}.legal a{color:var(--accent);text-decoration:none}.legal a:hover{text-decoration:underline}.legal__head{display:grid;gap:14px;padding-bottom:25px;border-bottom:1px solid var(--border-subtle)}.legal__head h1{font-size:clamp(30px,5vw,44px);margin:0;line-height:1.3}.legal__head p{margin:0;font-size:13px;color:var(--text-muted)}.legal__eyebrow{letter-spacing:.14em;font-size:12px;color:var(--text-muted)}.legal nav,.legal footer{display:flex;flex-wrap:wrap;gap:24px;font-size:14px}.legal nav [aria-current=page]{font-weight:700;text-decoration:underline;text-underline-offset:6px}.legal__intro{padding:18px 20px;margin:26px 0;border-left:3px solid var(--accent);background:var(--surface-raised);font-size:14px}.legal__layout{display:grid;grid-template-columns:190px minmax(0,1fr);gap:42px}.legal aside{position:sticky;top:22px;align-self:start;display:grid;gap:13px;font-size:13px}.legal article{min-width:0}.legal article section{padding-bottom:25px;margin-bottom:25px;border-bottom:1px solid var(--border-subtle);scroll-margin-top:24px}.legal h2{font-size:20px;line-height:1.6;margin:0 0 16px}.legal p{font-size:14px;overflow-wrap:anywhere;margin:12px 0}.legal footer{justify-content:center;padding:15px 0 25px}@media(max-width:700px){.legal__layout{grid-template-columns:1fr;gap:20px}.legal aside{position:static;grid-template-columns:repeat(2,minmax(0,1fr));padding-bottom:18px;border-bottom:1px solid var(--border-subtle)}.legal nav,.legal footer{gap:16px}}
</style>
