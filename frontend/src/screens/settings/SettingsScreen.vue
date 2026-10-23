<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSettingsStore, type PrivacyKey } from '../../stores/settings'
import { useAudioStore } from '../../stores/audio'
import { useCollectionStore } from '../../stores/collection'
import { useHomeStore } from '../../stores/home'
import { THEME_LABELS, useUiStore, type FontScale, type ThemeName } from '../../stores/ui'
import { useWallpaperStore } from '../../stores/wallpaper'

/**
 * Ticket #25: settings.
 *
 * The two account switches and every privacy checkbox are written on change and
 * re-read from the server response; the screen never keeps a local "maybe it
 * saved" state. The card payload always carries the frozen eleven fields.
 */
const router = useRouter()
const settings = useSettingsStore()
const audio = useAudioStore()
const collection = useCollectionStore()
const home = useHomeStore()
const ui = useUiStore()
const wallpaperLayer = useWallpaperStore()

const oldPassword = ref('')
const newPassword = ref('')

// ------------------------------------------------------- intent groups ----
// Four groups (spec section 8, ticket #49). The left rail highlights the group
// the player is currently reading and jumps to it on click.
type GroupKey = 'appearance' | 'sound' | 'account' | 'about'
const groups: { key: GroupKey; label: string }[] = [
  { key: 'appearance', label: '外观' },
  { key: 'sound', label: '声音' },
  { key: 'account', label: '账号与隐私' },
  { key: 'about', label: '关于' },
]
const activeGroup = ref<GroupKey>('appearance')

function goGroup(key: GroupKey): void {
  activeGroup.value = key
  document.getElementById('settings-' + key)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

const themes: ThemeName[] = ['chart', 'journal', 'night']

/** 主色预设（原 main 设置页的主色选择器）；空值 = 用主题自带的强调色。 */
const accentPresets: { key: string; label: string }[] = [
  { key: '', label: '跟随主题' },
  { key: '#7c5cf0', label: '紫' },
  { key: '#2f8fdd', label: '蓝' },
  { key: '#4ec8e0', label: '青' },
  { key: '#c9a24c', label: '金' },
  { key: '#45d69b', label: '绿' },
]
const fontScales: { key: FontScale; label: string }[] = [
  { key: 'normal', label: '标准' },
  { key: 'large', label: '大' },
  { key: 'xlarge', label: '特大' },
]

function chooseTheme(theme: ThemeName): void {
  ui.setTheme(theme)
  ui.notify({ code: 'theme-' + theme, tone: 'success', message: '已切换到「' + THEME_LABELS[theme] + '」主题' })
}

function chooseMotion(reduced: boolean): void {
  ui.setMotion(reduced ? 'reduced' : 'auto')
  ui.notify({
    code: 'motion-' + (reduced ? 'reduced' : 'auto'),
    tone: 'success',
    message: reduced ? '已减少动效，只保留状态变化' : '已恢复完整动效',
  })
}

function chooseContrast(high: boolean): void {
  ui.setContrast(high ? 'high' : 'auto')
  ui.notify({
    code: 'contrast-' + (high ? 'high' : 'auto'),
    tone: 'success',
    message: high ? '已开启高对比描边' : '已恢复标准对比',
  })
}

function chooseFontScale(scale: FontScale): void {
  ui.setFontScale(scale)
  ui.notify({ code: 'font-' + scale, tone: 'success', message: '字号已调整为' + fontScales.find((item) => item.key === scale)?.label })
}

function requestLogin(): void {
  ui.requestLogin('login', '登录后才能修改账号与隐私设置')
}

const privacyRows: { key: PrivacyKey; testid: string; label: string; hint: string }[] = [
  { key: 'show_stats', testid: 'settings-privacy-stats', label: '显示战绩亮点', hint: '最高连胜 / 胜率 / 总场次' },
  { key: 'show_fav_cards', testid: 'settings-privacy-favcards', label: '显示最爱用的卡', hint: '名片上的常用卡牌' },
  { key: 'show_history', testid: 'settings-privacy-history', label: '公开对局历史', hint: '别人能在你的名片上看到战绩列表' },
  { key: 'show_guestbook', testid: 'settings-privacy-guestbook', label: '公开留言板', hint: '别人可以在你的名片上留言' },
  { key: 'show_rank', testid: 'settings-privacy-rank', label: '公开段位', hint: '关闭后他人看不到你的段位与排位分（段位榜不受影响）' },
  { key: 'friend_requests_open', testid: 'settings-privacy-friend-requests', label: '允许他人加我好友', hint: '关闭后陌生人不能向你发好友申请' },
]

const anonymous = computed(
  () => settings.profileStatus === 'anonymous' || settings.replay.status === 'anonymous',
)
const profileFailed = computed(() => settings.profileStatus === 'error')
const privacyReady = computed(() => settings.profileStatus === 'ready')

function toggleStatus(kind: 'replay' | 'spectate'): string {
  const state = kind === 'replay' ? settings.replay : settings.spectate
  if (state.status === 'anonymous') return '登录后才能修改'
  if (state.saving) return '保存中…'
  if (state.error) return state.error
  if (state.status === 'loading') return '正在读取…'
  if (state.value === null) return '状态未知'
  return state.value ? '已开启' : '已关闭'
}

const privacyStatus = computed(() => {
  if (!privacyReady.value) return '登录后才能修改'
  if (settings.privacySaving) return '保存中…'
  if (settings.privacyMessage) return settings.privacyMessage
  return '改动会立即保存'
})

const wallpaperStatus = computed(() => {
  const state = settings.wallpaper
  if (state.status === 'loading') return '正在检查本机壁纸库…'
  if (state.status === 'error') return '读取失败：' + state.error
  if (state.status === 'ready') {
    if (state.available === false) return state.reason || '当前环境不可用'
    return '本机可用：发现 ' + state.dirs + ' 个壁纸目录，' + state.items.length + ' 张壁纸'
  }
  return '点「打开壁纸库」扫描本机（仅本机访问可用），选中后立即应用到背景。'
})

const wallpaperItems = computed(() => settings.wallpaper.items)
const wallpaperReady = computed(
  () => settings.wallpaper.status === 'ready' && settings.wallpaper.available === true,
)
const appliedWallpaper = computed(() => wallpaperLayer.applied)

function wallpaperTitle(item: Record<string, unknown>): string {
  const title = typeof item.title === 'string' ? item.title.trim() : ''
  return title || '未命名壁纸'
}

function wallpaperReason(item: Record<string, unknown>): string {
  return typeof item.reason === 'string' ? item.reason : ''
}

function wallpaperMediaUrl(item: Record<string, unknown>): string {
  return typeof item.media_url === 'string' ? item.media_url : ''
}

function wallpaperPreviewUrl(item: Record<string, unknown>): string {
  return typeof item.preview_url === 'string' ? item.preview_url : ''
}

function wallpaperKind(item: Record<string, unknown>): 'video' | 'image' {
  return item.kind === 'video' ? 'video' : 'image'
}

function applyWallpaper(item: Record<string, unknown>): void {
  const mediaUrl = wallpaperMediaUrl(item)
  if (!mediaUrl) return
  wallpaperLayer.apply({
    id: typeof item.id === 'string' ? item.id : '',
    title: wallpaperTitle(item),
    kind: wallpaperKind(item),
    mediaUrl,
    previewUrl: wallpaperPreviewUrl(item),
  })
}


function onSfxVolume(event: Event): void {
  const target = event.target as HTMLInputElement | null
  if (target) audio.setSfxVolume(Number(target.value) / 100)
}

function onBgmVolume(event: Event): void {
  const target = event.target as HTMLInputElement | null
  if (target) audio.setBgmVolume(Number(target.value) / 100)
}

async function onReplayChange(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement | null
  if (!target) return
  await settings.setToggle('replay', target.checked)
}

async function onSpectateChange(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement | null
  if (!target) return
  await settings.setToggle('spectate', target.checked)
}

async function onPrivacyChange(key: PrivacyKey, event: Event): Promise<void> {
  const target = event.target as HTMLInputElement | null
  if (!target) return
  await settings.setPrivacy(key, target.checked)
}

async function submitPassword(): Promise<void> {
  const ok = await settings.changePassword(oldPassword.value, newPassword.value)
  if (ok) {
    oldPassword.value = ''
    newPassword.value = ''
  }
}

// The two wallpaper buttons are different actions: "check" only reports what is
// on this machine; "open" also reveals the library rows.
const libraryOpen = ref(false)

async function checkWallpaperLibrary(): Promise<void> {
  await settings.checkWallpapers()
}

async function openWallpaperLibrary(): Promise<void> {
  libraryOpen.value = true
  await settings.checkWallpapers()
}

// Wallpaper library, migration residual closed: GET /api/wallpapers lists the
// playable local rows, the apply button stores the server's media URL in
// localStorage, and AppWallpaper renders/plays it on every screen.

onMounted(() => {
  void settings.loadOwn()
  void settings.loadToggle('replay')
  void settings.loadToggle('spectate')
  void home.loadChangelog()
})
</script>

<template>
  <section
    class="screen settings"
    data-screen="settings"
    data-testid="screen-settings"
    aria-labelledby="screen-settings-title"
  >
    <div class="settings__modal">
      <header class="settings__head">
        <p class="settings__eyebrow">竞技场 · 设置</p>
        <h1 id="screen-settings-title" class="settings__title" data-testid="settings-heading">设置</h1>
        <p class="settings__hint">回放与观战开关、名片隐私、密码与壁纸入口；改动立即生效。</p>
      </header>

      <div class="settings__layout">
        <nav class="settings__nav" aria-label="设置分区">
          <button
            v-for="group in groups"
            :key="group.key"
            type="button"
            class="settings__nav-item"
            :class="{ 'is-active': activeGroup === group.key }"
            :data-testid="'settings-nav-' + group.key"
            :data-active="activeGroup === group.key ? 'true' : 'false'"
            :aria-current="activeGroup === group.key ? 'true' : undefined"
            @click="goGroup(group.key)"
          >
            {{ group.label }}
          </button>
        </nav>

        <div class="settings__panes">

      <section id="settings-appearance" class="settings__group" data-testid="settings-group-appearance" aria-labelledby="settings-group-appearance-title">
        <h2 id="settings-group-appearance-title" class="settings__group-title">外观</h2>

        <section class="settings__block settings__appearance" data-testid="settings-appearance">
          <h3 class="settings__block-title">主题</h3>
          <div class="settings__seg" role="group" aria-label="主题">
            <button
              v-for="theme in themes"
              :key="theme"
              type="button"
              class="settings__seg-item"
              :data-testid="'settings-theme-' + theme"
              :aria-pressed="ui.theme === theme"
              :class="{ 'is-active': ui.theme === theme }"
              @click="chooseTheme(theme)"
            >
              {{ THEME_LABELS[theme] }}
            </button>
          </div>

          <h3 class="settings__block-title">动效</h3>
          <div class="settings__seg" role="group" aria-label="动效">
            <button type="button" class="settings__seg-item" data-testid="settings-motion-auto"
              :aria-pressed="ui.motion === 'auto'" :class="{ 'is-active': ui.motion === 'auto' }"
              @click="chooseMotion(false)">完整动效</button>
            <button type="button" class="settings__seg-item" data-testid="settings-motion-reduced"
              :aria-pressed="ui.motion === 'reduced'" :class="{ 'is-active': ui.motion === 'reduced' }"
              @click="chooseMotion(true)">减少动效</button>
          </div>

          <h3 class="settings__block-title">对比度</h3>
          <div class="settings__seg" role="group" aria-label="对比度">
            <button type="button" class="settings__seg-item" data-testid="settings-contrast-auto"
              :aria-pressed="ui.contrast === 'auto'" :class="{ 'is-active': ui.contrast === 'auto' }"
              @click="chooseContrast(false)">标准对比</button>
            <button type="button" class="settings__seg-item" data-testid="settings-contrast-high"
              :aria-pressed="ui.contrast === 'high'" :class="{ 'is-active': ui.contrast === 'high' }"
              @click="chooseContrast(true)">高对比</button>
          </div>

          <h3 class="settings__block-title">字号</h3>
          <div class="settings__seg" role="group" aria-label="字号">
            <button
              v-for="scale in fontScales"
              :key="scale.key"
              type="button"
              class="settings__seg-item"
              :data-testid="'settings-font-' + scale.key"
              :aria-pressed="ui.fontScale === scale.key"
              :class="{ 'is-active': ui.fontScale === scale.key }"
              @click="chooseFontScale(scale.key)"
            >
              {{ scale.label }}
            </button>
          </div>
          <h3 class="settings__block-title">主色</h3>
          <div class="settings__seg settings__seg--wrap" role="group" aria-label="主色">
            <button
              v-for="preset in accentPresets"
              :key="'accent-' + preset.label"
              type="button"
              class="settings__seg-item settings__seg-item--accent"
              :class="{ 'is-active': (ui.accent || '') === preset.key }"
              :data-testid="'settings-accent-' + (preset.key ? preset.key.replace('#', '') : 'theme')"
              :aria-pressed="(ui.accent || '') === preset.key"
              :style="preset.key ? { '--swatch': preset.key } : undefined"
              @click="ui.setAccent(preset.key || null)"
            >
              <i v-if="preset.key" class="settings__swatch" aria-hidden="true"></i>
              {{ preset.label }}
            </button>
          </div>

          <h3 class="settings__block-title">预览</h3>
          <div class="settings__preview" data-testid="settings-preview" aria-label="外观预览">
            <div class="settings__preview-board" aria-hidden="true">
              <span
                v-for="cell in 36"
                :key="'pc-' + cell"
                class="settings__preview-cell"
                :class="{
                  'is-ship': cell === 8 || cell === 9 || cell === 14,
                  'is-hit': cell === 20,
                  'is-miss': cell === 27,
                }"
              ></span>
            </div>
            <div class="settings__preview-actions">
              <span class="settings__preview-primary" data-testid="settings-preview-primary">主行动</span>
              <span class="settings__preview-secondary" data-testid="settings-preview-secondary">次行动</span>
              <span class="settings__preview-hit">命中</span>
              <span class="settings__preview-miss">未命中</span>
            </div>
          </div>

          <p class="settings__note">主题、主色、动效、对比度与字号立即生效，并在这台设备上记住。</p>
        </section>

        <section id="settings-wallpaper" class="settings__block" data-testid="settings-wallpaper">
          <h3 class="settings__block-title">动态壁纸</h3>
          <p class="settings__note">
            扫描本机壁纸库（仅本机访问可用），选中后立即应用到背景；视频壁纸可随时暂停。
          </p>
          <div class="settings__wallpaper-actions">
            <button
              type="button"
              class="button"
              data-testid="settings-wallpaper-entry"
              :disabled="settings.wallpaper.status === 'loading'"
              @click="openWallpaperLibrary"
            >
              打开壁纸库
            </button>
            <button type="button" class="button button--ghost" data-testid="settings-wallpaper-check" @click="checkWallpaperLibrary">
              检查本机壁纸库
            </button>
            <button type="button" class="button button--ghost" data-testid="settings-collection-open" @click="collection.open()">
              打开图鉴 / 卡库
            </button>
          </div>
          <p class="settings__note" data-testid="settings-wallpaper-status" role="status">{{ wallpaperStatus }}</p>

          <div v-if="appliedWallpaper" class="settings__wallpaper-current" data-testid="settings-wallpaper-current">
            <span class="settings__wallpaper-current-title" data-testid="settings-wallpaper-current-title">
              当前壁纸：{{ appliedWallpaper.title }}
            </span>
            <button type="button" class="button button--ghost" data-testid="settings-wallpaper-play" @click="wallpaperLayer.togglePlay()">
              {{ wallpaperLayer.playing ? '暂停' : '播放' }}
            </button>
            <button type="button" class="button button--ghost" data-testid="settings-wallpaper-clear" @click="wallpaperLayer.clear()">
              取消壁纸
            </button>
          </div>

          <ul v-if="libraryOpen && wallpaperReady && wallpaperItems.length" class="settings__wallpaper-list" data-testid="settings-wallpaper-list">
            <li
              v-for="item in wallpaperItems"
              :key="String(item.id)"
              class="settings__wallpaper-item"
              data-testid="settings-wallpaper-item"
              :data-wallpaper-id="String(item.id)"
              :data-supported="item.supported === true ? 'true' : 'false'"
            >
              <div class="settings__wallpaper-preview">
                <img
                  v-if="wallpaperPreviewUrl(item)"
                  :src="wallpaperPreviewUrl(item)"
                  :alt="wallpaperTitle(item) + ' 预览'"
                  loading="lazy"
                  decoding="async"
                />
                <span v-else aria-hidden="true">{{ wallpaperKind(item) === 'video' ? '视频' : '图片' }}</span>
              </div>
              <div class="settings__wallpaper-meta">
                <p class="settings__wallpaper-title">{{ wallpaperTitle(item) }}</p>
                <p class="settings__wallpaper-kind">
                  {{ wallpaperKind(item) === 'video' ? '视频壁纸' : '图片壁纸' }}
                </p>
                <p v-if="item.supported !== true" class="settings__note" data-testid="settings-wallpaper-reason">
                  {{ wallpaperReason(item) || '这张壁纸无法在网页里播放' }}
                </p>
              </div>
              <button
                type="button"
                class="button"
                data-testid="settings-wallpaper-apply"
                :disabled="item.supported !== true || !wallpaperMediaUrl(item)"
                @click="applyWallpaper(item)"
              >
                应用
              </button>
            </li>
          </ul>
          <p
            v-else-if="libraryOpen && wallpaperReady && settings.wallpaper.status === 'ready'"
            class="settings__note"
            data-testid="settings-wallpaper-empty"
          >
            没有找到可用的壁纸：{{ settings.wallpaper.reason || '本机壁纸库是空的。' }}
          </p>
        </section>
      </section>

      <section id="settings-sound" class="settings__group" data-testid="settings-group-sound" aria-labelledby="settings-group-sound-title">
        <h2 id="settings-group-sound-title" class="settings__group-title">声音</h2>
        <section class="settings__block settings__audio" data-testid="settings-audio">
        <h2 class="settings__block-title">音效与背景音乐</h2>
        <div class="settings__audio-row">
          <button
            type="button"
            class="button"
            data-testid="settings-sfx-mute"
            :aria-pressed="audio.sfxMuted"
            @click="audio.toggleSfxMute()"
          >
            {{ audio.sfxMuted ? '音效：已静音' : '音效：开启' }}
          </button>
          <button type="button" class="button" data-testid="settings-sfx-preview" @click="audio.previewSfx()">
            试听
          </button>
        </div>
        <label class="settings__range">
          <span>音效音量</span>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            :value="audio.sfxVolumePercent"
            data-testid="settings-sfx-volume"
            @input="onSfxVolume"
          />
          <output data-testid="settings-sfx-volume-value">{{ audio.sfxVolumePercent }}%</output>
        </label>

        <div class="settings__audio-row">
          <button
            type="button"
            class="button"
            data-testid="settings-bgm-toggle"
            :aria-pressed="audio.bgmPlaying"
            @click="audio.toggleBgmPlay()"
          >
            {{ audio.bgmPlaying ? '背景音乐：暂停' : '背景音乐：播放' }}
          </button>
          <button
            type="button"
            class="button button--ghost"
            data-testid="settings-bgm-mute"
            :aria-pressed="audio.bgmMuted"
            @click="audio.toggleBgmMute()"
          >
            {{ audio.bgmMuted ? '取消静音' : '静音' }}
          </button>
        </div>
        <label class="settings__range">
          <span>音乐音量</span>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            :value="audio.bgmVolumePercent"
            data-testid="settings-bgm-volume"
            @input="onBgmVolume"
          />
          <output data-testid="settings-bgm-volume-value">{{ audio.bgmVolumePercent }}%</output>
        </label>
        <p class="settings__note" data-testid="settings-bgm-status" role="status">
          {{ audio.bgmStatus }}（浏览器可能要求先点一下页面才出声）
        </p>
        </section>
      </section>

      <section id="settings-account" class="settings__group" data-testid="settings-group-account" aria-labelledby="settings-group-account-title">
        <h2 id="settings-group-account-title" class="settings__group-title">账号与隐私</h2>

    <section v-if="anonymous" class="settings__login" data-testid="settings-login-required">
      <h2>需要先登录</h2>
      <p>回放开关、观战开关、隐私与密码都绑定账号。</p>
      <button type="button" class="button" data-testid="settings-login-required-action" @click="requestLogin">
        登录 / 注册
      </button>
    </section>
    <p v-else-if="profileFailed" class="settings__state settings__state--error" data-testid="settings-error" role="alert">
      无法加载设置：{{ settings.profileError }}
    </p>

    <template v-else>
      <section id="settings-replay" class="settings__block" data-testid="settings-replay">
        <h2 class="settings__block-title">对局回放</h2>
        <label class="settings__switch">
          <input
            type="checkbox"
            data-testid="settings-allow-replay"
            :checked="settings.replay.value === true"
            :disabled="settings.replay.status !== 'ready' || settings.replay.saving"
            @change="onReplayChange"
          />
          <span>允许保留我的对局回放</span>
        </label>
        <p class="settings__note" data-testid="settings-replay-status" role="status">
          {{ toggleStatus('replay') }}
        </p>
        <p class="settings__note">任一方关闭，这一局就不会留下回放。</p>
      </section>

      <section id="settings-spectate" class="settings__block" data-testid="settings-spectate">
        <h2 class="settings__block-title">观战</h2>
        <label class="settings__switch">
          <input
            type="checkbox"
            data-testid="settings-allow-spectate"
            :checked="settings.spectate.value === true"
            :disabled="settings.spectate.status !== 'ready' || settings.spectate.saving"
            @change="onSpectateChange"
          />
          <span>允许他人观战我的对局</span>
        </label>
        <p class="settings__note" data-testid="settings-spectate-status" role="status">
          {{ toggleStatus('spectate') }}
        </p>
        <p class="settings__note">观众只能看到双方已轰过的格子，看不到你的船位。</p>
      </section>

      <section id="settings-privacy" class="settings__block" data-testid="settings-privacy">
        <h2 class="settings__block-title">名片隐私</h2>
        <label v-for="row in privacyRows" :key="row.key" class="settings__switch">
          <input
            type="checkbox"
            :data-testid="row.testid"
            :checked="settings.privacy[row.key]"
            :disabled="!privacyReady || settings.privacySaving"
            @change="onPrivacyChange(row.key, $event)"
          />
          <span>
            {{ row.label }}
            <small class="settings__switch-hint">{{ row.hint }}</small>
          </span>
        </label>
        <p class="settings__note" data-testid="settings-privacy-status" role="status">{{ privacyStatus }}</p>
      </section>

      <section id="settings-password" class="settings__block" data-testid="settings-password">
        <h2 class="settings__block-title">修改密码</h2>
        <form class="settings__form" @submit.prevent="submitPassword">
          <label>
            <span>原密码</span>
            <input
              v-model="oldPassword"
              type="password"
              autocomplete="current-password"
              data-testid="settings-old-password"
            />
          </label>
          <label>
            <span>新密码（至少 6 位）</span>
            <input
              v-model="newPassword"
              type="password"
              autocomplete="new-password"
              data-testid="settings-new-password"
            />
          </label>
          <button type="submit" class="button" data-testid="settings-change-password" :disabled="settings.passwordSaving">
            更改密码
          </button>
        </form>
        <p
          v-if="settings.passwordMessage"
          class="settings__note"
          :class="{ 'is-error': settings.passwordError }"
          data-testid="settings-password-msg"
          role="status"
        >
          {{ settings.passwordMessage }}
        </p>
      </section>
    </template>
      </section>

      <section id="settings-about" class="settings__group" data-testid="settings-group-about" aria-labelledby="settings-group-about-title">
        <h2 id="settings-group-about-title" class="settings__group-title">关于</h2>

        <section class="settings__block" data-testid="settings-about-help">
          <h2 class="settings__block-title">玩法与帮助</h2>
          <p class="settings__note">
            6×6 海域各摆 6 艘单格战舰，猜拳定先手，按准备 → 战斗 → 结束三个阶段轮流开炮；
            先击沉对方全部战舰的一方获胜。魔法卡分普通 / 场地 / 判定三类，连锁从最后一次出牌往前结算。
          </p>
        </section>

        <section class="settings__block" data-testid="settings-about-changelog">
          <h2 class="settings__block-title">最近公告</h2>
          <p class="settings__note">{{ home.changelogLatest || (home.changelogLoaded ? '暂时没有公告。' : '公告载入中…') }}</p>
          <ul v-if="home.changelog.length" class="settings__about-list">
            <li v-for="entry in home.changelog" :key="entry.date">
              <b>{{ entry.date }}</b> · {{ entry.items.join('；') }}
            </li>
          </ul>
        </section>

        <section class="settings__block" data-testid="settings-about-version">
          <h2 class="settings__block-title">版本</h2>
          <p class="settings__note">战舰棋 · 深海作战室（新前端）· 公告与玩法说明都可以在这里回看。</p>
        </section>
      </section>

      <footer class="settings__actions">
        <button type="button" class="button button--ghost" data-testid="settings-back" @click="router.push({ name: 'start' })">
          返回首页
        </button>
      </footer>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* C+ settings: one 1040px modal, left section rail + right scrolling pane. */
.settings {
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.settings__modal {
  display: flex;
  flex-direction: column;
  width: 1040px;
  max-width: 100%;
  max-height: calc(100vh - 104px);
  overflow: hidden;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.settings__head {
  flex: 0 0 auto;
  padding: 16px 22px 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.settings__eyebrow {
  margin: 0 0 2px;
  color: var(--text-secondary);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.settings__title {
  margin: 0;
  font-size: 24px;
  line-height: 1.2;
}

.settings__hint {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.settings__layout {
  display: grid;
  grid-template-columns: 182px minmax(0, 1fr);
  gap: 18px;
  min-height: 0;
  padding: 16px 22px 20px;
}

.settings__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-self: start;
  padding: 8px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--surface-deck);
}

.settings__nav-item {
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.settings__nav-item:hover {
  border-color: var(--role-self);
  background: var(--role-self-soft);
  color: var(--text-primary);
}

/* The highlight follows the group being read, not the first item forever. */
.settings__nav-item.is-active {
  border-color: var(--role-action);
  background: var(--role-action-soft);
  color: var(--text-primary);
}

.settings__panes {
  display: grid;
  align-content: start;
  gap: 12px;
  min-height: 0;
  padding-right: 8px;
  overflow-y: auto;
}

.settings__login,
.settings__state {
  margin: 0;
  padding: 14px 16px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--surface-deck);
  color: var(--text-muted);
  font-size: 13px;
}

.settings__state--error {
  border-color: var(--danger);
  color: var(--danger);
}

.settings__login h2 {
  margin: 0 0 6px;
  color: var(--text);
  font-size: 18px;
}

.settings__login p {
  margin: 0 0 10px;
}

.settings__block {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--surface-deck);
}

.settings__block-title {
  margin: 0;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
}

.settings__switch {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  cursor: pointer;
}

.settings__switch input {
  width: 18px;
  height: 18px;
  margin: 2px 0 0;
  accent-color: var(--accent);
}

.settings__switch-hint {
  display: block;
  margin-top: 1px;
  color: var(--text-muted);
  font-size: 11px;
}

.settings__note {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.settings__note.is-error {
  color: var(--danger);
}

.settings__form {
  display: grid;
  gap: 10px;
  max-width: 340px;
}

.settings__form label {
  display: grid;
  gap: 4px;
  color: var(--text-muted);
  font-size: 12px;
}

.settings__form input {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-sunken);
  color: var(--text);
  font: inherit;
}

.settings__form button {
  justify-self: start;
}

.settings__wallpaper-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.settings__wallpaper-current {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--gold) 35%, transparent);
  border-radius: var(--radius-sm);
  background: rgba(201, 162, 76, 0.08);
}

.settings__wallpaper-current-title {
  flex: 1 1 220px;
  min-width: 0;
  color: var(--text);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings__wallpaper-list {
  display: grid;
  gap: 10px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}

.settings__wallpaper-item {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: rgba(13, 17, 34, 0.62);
}

.settings__wallpaper-item[data-supported='false'] {
  opacity: 0.72;
}

.settings__wallpaper-preview {
  display: grid;
  place-items: center;
  width: 96px;
  height: 54px;
  overflow: hidden;
  border-radius: 6px;
  background: var(--surface-sea);
  color: var(--text-dim);
  font-size: 11px;
}

.settings__wallpaper-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.settings__wallpaper-meta {
  min-width: 0;
}

.settings__wallpaper-title {
  margin: 0 0 2px;
  color: var(--text);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings__wallpaper-kind {
  margin: 0;
  color: var(--text-dim);
  font-size: 11px;
}

.settings__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding-top: 4px;
}

.settings__actions .button {
  min-height: 40px;
  padding: 8px 20px;
}

.settings__actions [data-testid='settings-back'] {
  border-color: var(--border-strong);
  background: var(--surface-deck);
  color: var(--text-muted);
}

.settings__audio-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.settings__range {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-muted);
}

.settings__range input[type='range'] {
  flex: 1;
  min-width: 120px;
  accent-color: var(--accent);
}

.settings__range output {
  min-width: 42px;
  text-align: right;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 860px) {
  .settings {
    justify-content: flex-start;
    padding: 12px;
  }

  .settings__modal {
    max-height: none;
  }

  .settings__layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
    padding: 12px;
  }

  .settings__nav {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .settings__nav-item {
    padding: 8px 10px;
    font-size: 12px;
  }

  .settings__panes {
    overflow: visible;
    padding-right: 0;
  }
}

/* ------------------------------------------------- intent groups ------- */
.settings__group {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.settings__group-title {
  margin: 2px 0 0;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
}

/* Segmented controls: theme / motion / contrast / font scale. */
.settings__seg {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.settings__seg-item {
  min-height: 40px;
  padding: 0 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-chamber);
  color: var(--text-secondary);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.settings__seg-item:hover {
  border-color: var(--role-self);
  color: var(--text-primary);
}

.settings__seg-item.is-active {
  border-color: var(--role-action);
  background: var(--role-action-soft);
  color: var(--text-primary);
}

.settings__about-list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--text-muted);
  font-size: 12px;
}

@media (max-width: 719px) {
  button[data-testid],
  a[data-testid] {
    min-height: 44px;
    min-width: 44px;
  }

  .settings__switch {
    min-height: 44px;
    align-items: center;
  }

  .settings__seg-item,
  .settings__nav-item,
  .settings__actions .button,
  .settings__actions [data-testid='settings-back'] {
    min-height: 44px;
    min-width: 44px;
  }
}
</style>
<style scoped>
/* ---- 主色与即时预览（原 main 设置页的棋盘/命中/主次行动预览） ---- */
.settings__seg--wrap {
  flex-wrap: wrap;
}

.settings__seg-item--accent {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.settings__swatch {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--swatch, var(--role-action));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--text-primary) 24%, transparent);
}

.settings__preview {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  margin-top: 8px;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-deck);
}

.settings__preview-board {
  display: grid;
  grid-template-columns: repeat(6, 22px);
  grid-auto-rows: 22px;
  gap: 3px;
  padding: 6px;
  border-radius: 10px;
  background: var(--board-bg, var(--surface-chamber));
  border: 1px solid var(--board-border, var(--border-subtle));
}

.settings__preview-cell {
  border-radius: 4px;
  background: var(--cell-bg, var(--surface-chamber));
  border: 1px solid color-mix(in srgb, var(--board-border, var(--border-subtle)) 70%, transparent);
}

.settings__preview-cell.is-ship {
  background: linear-gradient(160deg, var(--ship-metal, var(--border-strong)), color-mix(in srgb, var(--ship-metal, var(--border-strong)) 55%, #000));
}

.settings__preview-cell.is-hit {
  background: radial-gradient(circle, #ff6b6b, #b3261e);
  border-color: #ff9a9a;
}

.settings__preview-cell.is-miss {
  box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--role-self, #4ec8e0) 70%, transparent);
}

.settings__preview-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.settings__preview-primary,
.settings__preview-secondary {
  padding: 6px 14px;
  border-radius: 8px;
  font-weight: 600;
}

.settings__preview-primary {
  color: var(--on-accent, #fff);
  background: var(--role-action);
}

.settings__preview-secondary {
  color: var(--text-primary);
  border: 1px solid color-mix(in srgb, var(--role-action) 55%, transparent);
  background: color-mix(in srgb, var(--role-action) 12%, transparent);
}

.settings__preview-hit,
.settings__preview-miss {
  padding: 3px 8px;
  border-radius: 999px;
}

.settings__preview-hit {
  color: #ffd7d4;
  background: color-mix(in srgb, #e5484d 26%, transparent);
}

.settings__preview-miss {
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--role-self, #4ec8e0) 18%, transparent);
}
</style>
