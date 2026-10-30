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
    <span class="app-profile-background__current"></span>
    <span class="app-profile-background__rings"></span>
  </div>
</template>

<style scoped>
/*
 * The profile background is a layered atmosphere rather than a single scan
 * line. Each theme gets a different movement language: current, grid,
 * aurora, star drift, storm bands or tidal rings.
 */
.app-profile-background {
  position: fixed;
  z-index: 0;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  background:
    radial-gradient(980px 620px at 52% -20%, rgb(57 152 183 / 22%), transparent 70%),
    linear-gradient(160deg, #07101f 0%, #071b2d 54%, #050914 100%);
  isolation: isolate;
}

.app-profile-background::before,
.app-profile-background::after,
.app-profile-background__aurora,
.app-profile-background__grid,
.app-profile-background__stars,
.app-profile-background__current,
.app-profile-background__rings {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.app-profile-background::before {
  content: '';
  z-index: 4;
  background: radial-gradient(ellipse at 72% 112%, rgb(26 121 159 / 22%), transparent 58%);
}

.app-profile-background::after {
  content: '';
  z-index: 5;
  background: linear-gradient(180deg, rgb(3 7 16 / 8%), rgb(3 7 16 / 35%));
}

.app-profile-background__grid {
  z-index: 1;
  opacity: .25;
  background-image:
    linear-gradient(rgb(103 185 211 / 10%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(103 185 211 / 10%) 1px, transparent 1px);
  background-size: 64px 64px;
  mask-image: linear-gradient(180deg, #000, transparent 94%);
  animation: profile-grid-drift 28s ease-in-out infinite alternate;
}

.app-profile-background__stars {
  z-index: 2;
  opacity: .28;
  background-image:
    radial-gradient(circle at 16% 24%, rgb(255 255 255 / 65%) 0 1px, transparent 2px),
    radial-gradient(circle at 73% 18%, rgb(132 224 255 / 58%) 0 1px, transparent 2px),
    radial-gradient(circle at 84% 72%, rgb(255 219 138 / 55%) 0 1px, transparent 2px);
  background-size: 210px 180px, 280px 250px, 340px 300px;
  animation: profile-stars-drift 30s linear infinite;
}

.app-profile-background__aurora {
  z-index: 0;
  opacity: .42;
  background:
    radial-gradient(ellipse at 12% 14%, rgb(90 225 188 / 26%), transparent 38%),
    radial-gradient(ellipse at 78% 80%, rgb(50 150 220 / 13%), transparent 48%);
  filter: blur(12px);
  transform-origin: 18% 22%;
  animation: profile-aurora-breathe 15s ease-in-out infinite alternate;
}

.app-profile-background__current {
  z-index: 3;
  opacity: .24;
  background:
    radial-gradient(ellipse at 18% 52%, rgb(91 219 237 / 24%), transparent 18%),
    radial-gradient(ellipse at 76% 78%, rgb(43 148 190 / 18%), transparent 26%),
    conic-gradient(from 236deg at 52% 42%, transparent, rgb(116 221 233 / 7%), transparent 27%, rgb(58 166 210 / 6%), transparent 58%);
  background-size: 150% 150%, 130% 130%, 130% 130%;
  background-position: 0% 50%, 100% 100%, 0% 0%;
  filter: blur(1px);
  animation: profile-current-drift 22s ease-in-out infinite alternate;
}

.app-profile-background__rings {
  z-index: 3;
  opacity: .18;
  background:
    radial-gradient(circle at 22% 62%, transparent 0 11%, rgb(93 212 235 / 26%) 11.2% 11.35%, transparent 11.6% 19%, rgb(93 212 235 / 16%) 19.2% 19.35%, transparent 19.7%),
    radial-gradient(circle at 78% 26%, transparent 0 9%, rgb(148 211 232 / 20%) 9.2% 9.35%, transparent 9.7% 17%, rgb(148 211 232 / 12%) 17.2% 17.35%, transparent 17.7%);
  transform: scale(.96);
  animation: profile-rings-pulse 12s ease-in-out infinite alternate;
}

.app-profile-background[data-bg='naval_grid'] {
  background:
    radial-gradient(700px 520px at 18% 26%, rgb(31 118 156 / 20%), transparent 68%),
    linear-gradient(160deg, #0d2942, #050914 78%);
}
.app-profile-background[data-bg='naval_grid'] .app-profile-background__grid {
  opacity: .64;
  background-size: 34px 34px;
  animation: profile-grid-sail 24s linear infinite;
}
.app-profile-background[data-bg='naval_grid'] .app-profile-background__current {
  opacity: .3;
  background:
    radial-gradient(ellipse at 18% 36%, rgb(81 221 244 / 30%), transparent 22%),
    linear-gradient(158deg, transparent 0 28%, rgb(95 210 232 / 10%) 44%, transparent 58%),
    linear-gradient(22deg, transparent 0 62%, rgb(54 145 190 / 12%) 72%, transparent 88%);
  animation-duration: 18s;
}

.app-profile-background[data-bg='aurora_drift'] {
  background:
    radial-gradient(ellipse at 15% 16%, rgb(111 255 194 / 30%), transparent 36%),
    linear-gradient(160deg, #123f47, #07131d 78%);
}
.app-profile-background[data-bg='aurora_drift'] .app-profile-background__aurora {
  opacity: .82;
  background:
    radial-gradient(ellipse at 20% 24%, rgb(123 255 205 / 32%), transparent 40%),
    radial-gradient(ellipse at 76% 70%, rgb(75 174 255 / 24%), transparent 46%),
    conic-gradient(from 210deg at 58% 42%, transparent, rgb(100 255 205 / 12%), transparent 44%, rgb(78 183 255 / 11%), transparent);
  animation: profile-aurora-sweep 20s ease-in-out infinite alternate;
}
.app-profile-background[data-bg='aurora_drift'] .app-profile-background__current { opacity: .17; }

.app-profile-background[data-bg='nebula_wake'] {
  background:
    radial-gradient(circle at 20% 24%, rgb(255 255 255 / 35%) 0 1px, transparent 2px),
    radial-gradient(circle at 74% 32%, rgb(197 160 255 / 32%) 0 1px, transparent 2px),
    linear-gradient(155deg, #29205b, #070a19 78%);
}
.app-profile-background[data-bg='nebula_wake'] .app-profile-background__stars {
  opacity: .54;
  background-size: 90px 90px, 130px 130px, 180px 180px;
  animation: profile-stars-twinkle 8s ease-in-out infinite alternate;
}
.app-profile-background[data-bg='nebula_wake'] .app-profile-background__aurora {
  opacity: .56;
  background: conic-gradient(from 30deg at 52% 50%, transparent, rgb(174 130 255 / 20%), transparent 32%, rgb(90 210 255 / 15%), transparent 68%);
  filter: blur(24px);
  animation: profile-nebula-rotate 34s linear infinite;
}
.app-profile-background[data-bg='nebula_wake'] .app-profile-background__rings { opacity: .24; }

.app-profile-background[data-bg='storm_atlas'] {
  background:
    radial-gradient(ellipse at 70% 12%, rgb(147 184 210 / 25%), transparent 32%),
    linear-gradient(160deg, #233b4b, #070d18 78%);
}
.app-profile-background[data-bg='storm_atlas'] .app-profile-background__current {
  opacity: .35;
  background:
    linear-gradient(116deg, transparent 0 34%, rgb(246 215 122 / 10%) 42%, transparent 52%),
    repeating-linear-gradient(116deg, transparent 0 17%, rgb(150 204 222 / 9%) 18% 18.4%, transparent 19% 32%);
  background-size: 150% 150%, 180% 180%;
  animation: profile-storm-front 13s ease-in-out infinite alternate;
}
.app-profile-background[data-bg='storm_atlas'] .app-profile-background__rings { opacity: .1; }

.app-profile-background[data-bg='season_deep'] {
  background:
    radial-gradient(ellipse at 20% 12%, rgb(142 220 236 / 32%), transparent 32%),
    linear-gradient(160deg, #0f4b60, #061522 78%);
}
.app-profile-background[data-bg='season_deep'] .app-profile-background__aurora {
  opacity: .72;
  background:
    radial-gradient(ellipse at 70% 20%, rgb(127 218 255 / 26%), transparent 38%),
    radial-gradient(ellipse at 32% 92%, rgb(41 177 202 / 20%), transparent 44%);
}
.app-profile-background[data-bg='season_deep'] .app-profile-background__current {
  opacity: .28;
  background:
    radial-gradient(ellipse at 20% 100%, rgb(102 227 235 / 22%) 0 11%, transparent 12%),
    radial-gradient(ellipse at 50% 100%, rgb(77 190 221 / 18%) 0 15%, transparent 16%),
    radial-gradient(ellipse at 82% 100%, rgb(114 226 239 / 18%) 0 12%, transparent 13%);
  background-size: 50% 100%, 62% 100%, 46% 100%;
  background-position: 0 0, 46% 0, 100% 0;
  animation: profile-tide-swell 14s ease-in-out infinite alternate;
}
.app-profile-background[data-bg='season_deep'] .app-profile-background__rings { opacity: .24; }

@keyframes profile-grid-drift {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to { transform: translate3d(-18px, 12px, 0) scale(1.02); }
}
@keyframes profile-grid-sail {
  from { background-position: 0 0; }
  to { background-position: 34px 34px; }
}
@keyframes profile-stars-drift {
  from { transform: translate3d(0, 0, 0); }
  to { transform: translate3d(-34px, 22px, 0); }
}
@keyframes profile-stars-twinkle {
  from { transform: translate3d(0, 0, 0); opacity: .32; }
  50% { opacity: .62; }
  to { transform: translate3d(-26px, 18px, 0); opacity: .44; }
}
@keyframes profile-aurora-breathe {
  from { transform: scale(1) translate3d(0, 0, 0); opacity: .34; }
  to { transform: scale(1.12) translate3d(4%, 2%, 0); opacity: .68; }
}
@keyframes profile-aurora-sweep {
  from { transform: translate3d(-3%, 2%, 0) rotate(-2deg) scale(1); }
  to { transform: translate3d(5%, -3%, 0) rotate(4deg) scale(1.12); }
}
@keyframes profile-current-drift {
  from { background-position: 0% 50%, 100% 100%, 0% 0%; transform: translate3d(-2%, 0, 0) scale(1.02); }
  to { background-position: 34% 46%, 66% 64%, 26% 18%; transform: translate3d(3%, -2%, 0) scale(1.08); }
}
@keyframes profile-rings-pulse {
  from { transform: scale(.92) translate3d(0, 2%, 0); opacity: .48; }
  to { transform: scale(1.08) translate3d(0, -2%, 0); opacity: .9; }
}
@keyframes profile-nebula-rotate {
  from { transform: rotate(0deg) scale(1); }
  to { transform: rotate(18deg) scale(1.12); }
}
@keyframes profile-storm-front {
  from { background-position: 0 0, 0 0; transform: translate3d(-2%, 2%, 0); }
  to { background-position: 34% -18%, -24% 20%; transform: translate3d(2%, -1%, 0); }
}
@keyframes profile-tide-swell {
  from { transform: translate3d(-2%, 0, 0) scaleY(.96); }
  to { transform: translate3d(2%, -1%, 0) scaleY(1.08); }
}

@media (prefers-reduced-motion: reduce) {
  .app-profile-background__stars,
  .app-profile-background__aurora,
  .app-profile-background__grid,
  .app-profile-background__current,
  .app-profile-background__rings { animation: none; }
}
</style>
