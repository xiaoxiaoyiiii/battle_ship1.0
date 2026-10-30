<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useProfileStore } from '../stores/profile'

const auth = useAuthStore()
const profile = useProfileStore()

const backgroundId = computed(() => {
  const value = profile.own?.profile_bg_id
  return typeof value === 'string' && value ? value : 'deep_ocean'
})

async function ensureProfile(): Promise<void> {
  if (!auth.isGuest) await profile.loadOwn()
}

onMounted(() => { void ensureProfile() })
watch(() => auth.isGuest, () => { void ensureProfile() })
</script>

<template>
  <div
    class="app-profile-background"
    :data-bg="backgroundId"
    data-testid="app-profile-background"
    aria-hidden="true"
  >
    <span class="app-profile-background__aurora"></span>
    <span class="app-profile-background__grid"></span>
    <span class="app-profile-background__stars"></span>
    <span class="app-profile-background__scan"></span>
  </div>
</template>

<style scoped>
.app-profile-background {
  position: fixed;
  z-index: 0;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  background:
    radial-gradient(900px 560px at 50% -18%, rgb(57 152 183 / 24%), transparent 72%),
    linear-gradient(160deg, #07101f 0%, #071b2d 54%, #050914 100%);
  isolation: isolate;
}

.app-profile-background::before,
.app-profile-background::after,
.app-profile-background__aurora,
.app-profile-background__grid,
.app-profile-background__stars,
.app-profile-background__scan {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.app-profile-background::before {
  content: '';
  z-index: -1;
  background: radial-gradient(ellipse at 75% 110%, rgb(26 121 159 / 22%), transparent 58%);
}

.app-profile-background::after {
  content: '';
  z-index: 3;
  background: linear-gradient(180deg, rgb(3 7 16 / 8%), rgb(3 7 16 / 32%));
}

.app-profile-background__grid {
  z-index: 1;
  opacity: .32;
  background-image:
    linear-gradient(rgb(103 185 211 / 10%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(103 185 211 / 10%) 1px, transparent 1px);
  background-size: 64px 64px;
  mask-image: linear-gradient(180deg, #000, transparent 92%);
}

.app-profile-background__stars {
  z-index: 2;
  opacity: .34;
  background-image:
    radial-gradient(circle at 16% 24%, rgb(255 255 255 / 65%) 0 1px, transparent 2px),
    radial-gradient(circle at 73% 18%, rgb(132 224 255 / 58%) 0 1px, transparent 2px),
    radial-gradient(circle at 84% 72%, rgb(255 219 138 / 55%) 0 1px, transparent 2px);
  background-size: 210px 180px, 280px 250px, 340px 300px;
  animation: profile-stars-drift 26s linear infinite;
}

.app-profile-background__aurora {
  z-index: 0;
  opacity: .45;
  background: radial-gradient(ellipse at 12% 14%, rgb(90 225 188 / 26%), transparent 38%);
  filter: blur(10px);
  animation: profile-aurora-breathe 12s ease-in-out infinite;
}

.app-profile-background__scan {
  z-index: 4;
  opacity: .22;
  background: linear-gradient(180deg, transparent 0 47%, rgb(127 225 255 / 18%) 50%, transparent 53%);
  background-size: 100% 320px;
  animation: profile-scan 13s linear infinite;
}

.app-profile-background[data-bg='naval_grid'] {
  background:
    linear-gradient(180deg, rgb(7 22 38 / 66%), rgb(4 9 18 / 88%)),
    linear-gradient(160deg, #0d2942, #050914 78%);
}
.app-profile-background[data-bg='naval_grid'] .app-profile-background__grid { opacity: .72; background-size: 34px 34px; }
.app-profile-background[data-bg='aurora_drift'] { background: radial-gradient(ellipse at 15% 16%, rgb(111 255 194 / 30%), transparent 36%), linear-gradient(160deg, #123f47, #07131d 78%); }
.app-profile-background[data-bg='aurora_drift'] .app-profile-background__aurora { opacity: .82; background: radial-gradient(ellipse at 20% 24%, rgb(123 255 205 / 32%), transparent 40%), radial-gradient(ellipse at 78% 70%, rgb(75 174 255 / 20%), transparent 46%); }
.app-profile-background[data-bg='nebula_wake'] { background: radial-gradient(circle at 20% 24%, rgb(255 255 255 / 35%) 0 1px, transparent 2px), radial-gradient(circle at 74% 32%, rgb(197 160 255 / 32%) 0 1px, transparent 2px), linear-gradient(155deg, #29205b, #070a19 78%); }
.app-profile-background[data-bg='nebula_wake'] .app-profile-background__grid { opacity: .18; }
.app-profile-background[data-bg='storm_atlas'] { background: linear-gradient(115deg, transparent 0 46%, rgb(246 215 122 / 18%) 47% 48%, transparent 49%), linear-gradient(160deg, #233b4b, #070d18 78%); }
.app-profile-background[data-bg='storm_atlas'] .app-profile-background__scan { opacity: .38; }
.app-profile-background[data-bg='season_deep'] { background: radial-gradient(ellipse at 20% 12%, rgb(142 220 236 / 32%), transparent 32%), linear-gradient(160deg, #0f4b60, #061522 78%); }
.app-profile-background[data-bg='season_deep'] .app-profile-background__aurora { opacity: .72; background: radial-gradient(ellipse at 70% 20%, rgb(127 218 255 / 26%), transparent 38%); }

@keyframes profile-stars-drift { from { transform: translate3d(0, 0, 0); } to { transform: translate3d(-34px, 22px, 0); } }
@keyframes profile-aurora-breathe { 0%, 100% { transform: scale(1); opacity: .36; } 50% { transform: scale(1.08); opacity: .72; } }
@keyframes profile-scan { from { transform: translateY(-320px); } to { transform: translateY(100vh); } }

@media (prefers-reduced-motion: reduce) {
  .app-profile-background__stars,
  .app-profile-background__aurora,
  .app-profile-background__scan { animation: none; }
}
</style>
