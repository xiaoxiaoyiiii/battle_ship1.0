<script setup lang="ts">
import { useAuthStore } from '../../stores/auth'
const auth = useAuthStore()
</script>
<template>
  <section class="welcome" data-testid="welcome-screen"><div class="welcome__mark" aria-hidden="true">⚓</div><h1>欢迎登舰，{{ auth.displayName }}。</h1><p class="welcome__intro">一片海域，六艘战舰。用炮击探路，用魔法争取下一次机会。</p><ol><li><b>先布下舰队</b><p>在 6×6 海域放好 6 艘单格战舰。猜拳决定先手，敌方的战舰起初不可见。</p></li><li><b>每回合做出选择</b><p>准备阶段使用魔法，战斗阶段点击敌方海域开炮；连锁从最后一次出牌向前结算。</p></li><li><b>击沉全部敌舰</b><p>首次可以与入门电脑练习，随后去大厅找一位对手。人机与自定义对局不计排位分。</p></li></ol><div class="welcome__actions"><router-link class="button button--primary" :to="{ name: 'start', query: { first_battle: '1' } }" data-testid="welcome-first-battle">去打一场入门人机</router-link><router-link class="button button--ghost" :to="{ name: 'lobby' }" data-testid="welcome-lobby">我已了解，进入大厅</router-link></div><footer><span>战舰棋目前通过网页游玩。</span><router-link :to="{ name: 'terms' }">用户协议</router-link><router-link :to="{ name: 'privacy' }">隐私政策</router-link></footer></section>
</template>
<style scoped>
.welcome { --text-strong:var(--text-primary); }
.welcome { width:min(780px,100%); margin:auto; box-sizing:border-box; padding:clamp(24px,5vw,60px); color:var(--text-strong); }.welcome__mark { font-size:42px; color:var(--accent); }.welcome h1 { font-size:clamp(26px,4vw,36px); }.welcome__intro { font-size:18px; line-height:1.8; color:var(--text-muted); }.welcome ol { padding-left:24px; margin:30px 0; }.welcome li { padding:12px 0 12px 12px; border-bottom:1px solid var(--border-subtle); }.welcome li p { color:var(--text-muted); line-height:1.8; font-size:14px; }.welcome__actions { display:flex; flex-wrap:wrap; gap:14px; padding:12px 0 24px; }.welcome footer { display:flex; flex-wrap:wrap; gap:12px 20px; color:var(--text-muted); font-size:12px; }
</style>
