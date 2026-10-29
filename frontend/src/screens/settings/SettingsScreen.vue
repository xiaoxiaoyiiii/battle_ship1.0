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
  document.getElementById('settings-' + key)?.scrollIntoView({ block: 'start', behavior: ui.motion === 'reduced' ? 'auto' : 'smooth' })
}

const themes: ThemeName[] = ['chart', 'journal', 'night']
const themeHints: Record<ThemeName, string> = {
  chart: '竞技场深蓝',
  journal: '清晰明亮',
  night: '沉静冷蓝',
}

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
        <div>
          <h1 id="screen-settings-title" class="settings__title" data-testid="settings-heading">设置</h1>
          <p class="settings__hint">把作战室调整成适合你的样子。</p>
        </div>
        <span class="settings__instant"><span aria-hidden="true">✓</span> 更改即时生效</span>
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
            <span class="settings__nav-symbol" aria-hidden="true">{{ group.key === 'appearance' ? '◈' : group.key === 'sound' ? '♫' : group.key === 'account' ? '◇' : '≡' }}</span>
            {{ group.label }}
          </button>
          <p class="settings__nav-note">主题、字号与动效<br />会在这台设备上记住。</p>
        </nav>

        <div class="settings__panes">

      <section id="settings-appearance" class="settings__group" data-testid="settings-group-appearance" aria-labelledby="settings-group-appearance-title">
        <div class="settings__section-head">
          <h2 id="settings-group-appearance-title" class="settings__group-title">外观</h2>
          <p class="settings__note">让信息清晰，让操作顺手。</p>
        </div>
        <section class="settings__block settings__appearance" data-testid="settings-appearance">
          <div class="settings__appearance-controls">
          <h3 class="settings__block-title">主题</h3>
          <div class="settings__themes" role="group" aria-label="主题">
            <button
              v-for="theme in themes"
              :key="theme"
              type="button"
              class="settings__theme"
              :data-preview-theme="theme"
              :data-testid="'settings-theme-' + theme"
              :aria-pressed="ui.theme === theme"
              :class="{ 'is-active': ui.theme === theme }"
              @click="chooseTheme(theme)"
            >
              <span class="settings__theme-scene" aria-hidden="true">
                <span class="settings__theme-toolbar"></span>
                <span class="settings__theme-boards"><i></i><i></i></span>
                <span class="settings__theme-action"></span>
              </span>
              <span class="settings__theme-name">{{ THEME_LABELS[theme] }}</span>
              <span class="settings__theme-hint">{{ themeHints[theme] }}</span>
              <span v-if="ui.theme === theme" class="settings__theme-check" aria-hidden="true">✓</span>
            </button>
          </div>

          <div class="settings__control-row">
          <div class="settings__control-copy"><h3 class="settings__block-title">主色</h3><p class="settings__note">主操作与选中状态的强调色</p></div>
          <div class="settings__seg settings__seg--colors" role="group" aria-label="主色">
            <button
              v-for="preset in accentPresets"
              :key="'accent-' + preset.label"
              type="button"
              class="settings__seg-item settings__seg-item--accent"
              :class="{ 'is-active': (ui.accent || '') === preset.key, 'is-swatch': Boolean(preset.key) }"
              :data-testid="'settings-accent-' + (preset.key ? preset.key.replace('#', '') : 'theme')"
              :aria-pressed="(ui.accent || '') === preset.key"
              :aria-label="preset.key ? preset.label + '色' : preset.label"
              :title="preset.label"
              :style="preset.key ? { '--swatch': preset.key } : undefined"
              @click="ui.setAccent(preset.key || null)"
            >
              <i v-if="preset.key" class="settings__swatch" aria-hidden="true"></i>
              <span :class="{ 'sr-only': Boolean(preset.key) }">{{ preset.label }}</span>
            </button>
          </div>
          </div>

          <div class="settings__control-row">
          <div class="settings__control-copy"><h3 class="settings__block-title">字号</h3><p class="settings__note">界面文字大小</p></div>
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
            >{{ scale.label }}</button>
          </div>
          </div>

          <div class="settings__control-row">
          <div class="settings__control-copy"><h3 class="settings__block-title">对比度</h3><p class="settings__note">提高文字与边线的辨识度</p></div>
          <div class="settings__seg" role="group" aria-label="对比度">
            <button type="button" class="settings__seg-item" data-testid="settings-contrast-auto"
              :aria-pressed="ui.contrast === 'auto'" :class="{ 'is-active': ui.contrast === 'auto' }"
              @click="chooseContrast(false)">标准对比</button>
            <button type="button" class="settings__seg-item" data-testid="settings-contrast-high"
              :aria-pressed="ui.contrast === 'high'" :class="{ 'is-active': ui.contrast === 'high' }"
              @click="chooseContrast(true)">高对比</button>
          </div>
          </div>

          <div class="settings__control-row">
          <div class="settings__control-copy"><h3 class="settings__block-title">动效</h3><p class="settings__note">减少动效后仍保留必要的状态提示</p></div>
          <div class="settings__seg" role="group" aria-label="动效">
            <button type="button" class="settings__seg-item" data-testid="settings-motion-auto"
              :aria-pressed="ui.motion === 'auto'" :class="{ 'is-active': ui.motion === 'auto' }"
              @click="chooseMotion(false)">完整动效</button>
            <button type="button" class="settings__seg-item" data-testid="settings-motion-reduced"
              :aria-pressed="ui.motion === 'reduced'" :class="{ 'is-active': ui.motion === 'reduced' }"
              @click="chooseMotion(true)">减少动效</button>
          </div>
          </div>
          <div class="settings__control-row">
            <div class="settings__control-copy"><h3 class="settings__block-title">战斗震动</h3><p class="settings__note">调整魔法命中时的画面震动，减少动效时自动关闭</p></div>
            <div class="settings__seg" role="group" aria-label="战斗震动">
              <button type="button" class="settings__seg-item" data-testid="settings-shake-strong" :aria-pressed="ui.battleShake === 'strong'" :class="{ 'is-active': ui.battleShake === 'strong' }" @click="ui.setBattleShake('strong')">明显</button>
              <button type="button" class="settings__seg-item" data-testid="settings-shake-light" :aria-pressed="ui.battleShake === 'light'" :class="{ 'is-active': ui.battleShake === 'light' }" @click="ui.setBattleShake('light')">轻微</button>
              <button type="button" class="settings__seg-item" data-testid="settings-shake-off" :aria-pressed="ui.battleShake === 'off'" :class="{ 'is-active': ui.battleShake === 'off' }" @click="ui.setBattleShake('off')">关闭</button>
            </div>
          </div>
          </div>

          <aside class="settings__preview" data-testid="settings-preview" aria-label="外观预览">
            <div class="settings__preview-head"><h3 class="settings__block-title">效果预览</h3><span>跟随设置</span></div>
            <div class="settings__preview-demo">
            <p class="settings__preview-label">海域示意 <span>6×6</span></p>
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
            <p class="settings__note">主题、主色、字号与对比度会实时反映在此处。</p>
          </aside>
        </section>

        <section class="settings__block settings__control-row" aria-labelledby="settings-phase-title">
          <div class="settings__control-copy">
            <h3 id="settings-phase-title" class="settings__block-title">阶段转换询问</h3>
            <p class="settings__note">对手进入战斗或结束阶段前，手中有可用速阶三时提醒你响应。关闭后自动放行。</p>
          </div>
          <div class="settings__seg" role="group" aria-label="阶段转换询问">
            <button type="button" class="settings__seg-item" data-testid="settings-phase-on" :aria-pressed="ui.phasePrompts" :class="{ 'is-active': ui.phasePrompts }" @click="ui.setPhasePrompts(true)">开启询问</button>
            <button type="button" class="settings__seg-item" data-testid="settings-phase-off" :aria-pressed="!ui.phasePrompts" :class="{ 'is-active': !ui.phasePrompts }" @click="ui.setPhasePrompts(false)">自动放行</button>
          </div>
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
        <div class="settings__section-head">
          <h2 id="settings-group-sound-title" class="settings__group-title">声音</h2>
          <p class="settings__note">保留作战反馈，调到舒服的音量。</p>
        </div>
        <section class="settings__block settings__audio" data-testid="settings-audio">
        <div class="settings__control-row">
        <div class="settings__control-copy"><h3 class="settings__block-title">游戏音效</h3><p class="settings__note">攻击、出牌与操作反馈</p></div>
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

        <div class="settings__control-row settings__audio-divider">
        <div class="settings__control-copy"><h3 class="settings__block-title">背景音乐</h3><p class="settings__note">随时播放、暂停或静音</p></div>
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
        <div class="settings__section-head">
          <h2 id="settings-group-account-title" class="settings__group-title">账号与隐私</h2>
          <p class="settings__note">决定哪些信息可见，以及谁能观看你的对局。</p>
        </div>

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
        <label class="settings__switch">
          <input
            type="checkbox"
            data-testid="settings-allow-replay"
            :checked="settings.replay.value === true"
            :disabled="settings.replay.status !== 'ready' || settings.replay.saving"
            @change="onReplayChange"
          />
          <span>允许保留我的对局回放<small class="settings__switch-hint">任一方关闭，这一局就不会留下回放。</small></span>
        </label>
        <p class="settings__note" data-testid="settings-replay-status" role="status">
          {{ toggleStatus('replay') }}
        </p>
      </section>

      <section id="settings-spectate" class="settings__block" data-testid="settings-spectate">
        <label class="settings__switch">
          <input
            type="checkbox"
            data-testid="settings-allow-spectate"
            :checked="settings.spectate.value === true"
            :disabled="settings.spectate.status !== 'ready' || settings.spectate.saving"
            @change="onSpectateChange"
          />
          <span>允许他人观战我的对局<small class="settings__switch-hint">观众只能看到双方已轰过的格子，看不到你的船位。</small></span>
        </label>
        <p class="settings__note" data-testid="settings-spectate-status" role="status">
          {{ toggleStatus('spectate') }}
        </p>
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
        <div class="settings__section-head">
          <h2 id="settings-group-about-title" class="settings__group-title">关于</h2>
          <p class="settings__note">玩法说明、版本与最近的更新。</p>
        </div>

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
/* 设置使用稳定侧栏与单一内容滚动区；预览独立占位，不覆盖控件。 */
.settings {
  align-items: stretch;
  justify-content: flex-start;
  padding: 28px clamp(18px, 5vw, 72px) 24px;
}

.settings__modal {
  display: flex;
  flex-direction: column;
  width: 1440px;
  max-width: 100%;
  min-height: 0;
  max-height: calc(100dvh - 124px);
  margin: 0 auto;
}

.settings__head {
  display: flex;
  flex: 0 0 auto;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 0 0 26px;
}

.settings__title {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 30px;
  line-height: 1.25;
  letter-spacing: -0.03em;
}

.settings__hint,
.settings__note,
.settings__nav-note {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.settings__instant {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  color: var(--role-success);
  font-size: 13px;
}

.settings__layout {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  gap: 32px;
  flex: 1;
  min-height: 0;
}

.settings__nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  padding: 6px 30px 24px 0;
  border-right: 1px solid var(--border-subtle);
  overflow-y: auto;
  scrollbar-width: thin;
}

.settings__nav-item {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 48px;
  padding: 10px 14px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}

.settings__nav-item:hover {
  background: var(--surface-raised);
  color: var(--text-primary);
}

.settings__nav-item.is-active {
  border-color: var(--border-subtle);
  background: var(--role-action-soft);
  color: var(--text-primary);
  box-shadow: inset 2px 0 var(--role-action);
}

.settings__nav-symbol {
  width: 18px;
  color: var(--text-secondary);
  font-size: 19px;
  text-align: center;
}

.settings__nav-note {
  padding: 30px 14px 0;
  font-size: 12px;
}

.settings__panes {
  display: grid;
  align-content: start;
  gap: 38px;
  min-width: 0;
  min-height: 0;
  padding: 4px 10px 24px 0;
  overflow-y: auto;
  overscroll-behavior-y: contain;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}

.settings__group {
  display: grid;
  align-content: start;
  gap: 0;
  min-width: 0;
  scroll-margin-top: 4px;
}

.settings__section-head {
  margin-bottom: 22px;
}

.settings__group-title {
  margin: 0 0 6px;
  color: var(--text-primary);
  font-size: 21px;
  line-height: 1.35;
}

.settings__block {
  display: grid;
  gap: 12px;
  min-width: 0;
  padding: 20px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.settings__block-title {
  margin: 0;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
}

.settings__appearance {
  grid-template-columns: minmax(0, 1fr) 270px;
  align-items: start;
  gap: 28px;
  padding-top: 0;
}

.settings__appearance-controls {
  min-width: 0;
}

.settings__themes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 12px 0 16px;
}

.settings__theme {
  --mini-bg: #0b1120;
  --mini-panel: #1b2840;
  --mini-cell: #23354d;
  --mini-line: #3b4d68;
  --mini-accent: #a990f5;
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: 9px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--surface-deck);
  color: var(--text-primary);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.settings__theme[data-preview-theme='journal'] {
  --mini-bg: #eff6ff;
  --mini-panel: #b8cee5;
  --mini-cell: #d5e6f4;
  --mini-line: #93b4d3;
  --mini-accent: #2f8fdd;
}

.settings__theme[data-preview-theme='night'] {
  --mini-bg: #0a1428;
  --mini-panel: #17304b;
  --mini-cell: #12344a;
  --mini-line: #2e5570;
  --mini-accent: #58a6ff;
}

.settings__theme:hover {
  border-color: var(--role-self);
}

.settings__theme.is-active {
  border-color: var(--role-action);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--role-action) 30%, transparent);
}

.settings__theme-scene {
  display: grid;
  grid-template-rows: 7px minmax(0, 1fr) 5px;
  gap: 7px;
  width: 100%;
  height: 76px;
  margin-bottom: 7px;
  padding: 7px;
  border: 1px solid var(--mini-line);
  border-radius: 4px;
  background: var(--mini-bg);
}

.settings__theme-toolbar {
  background: var(--mini-panel);
}

.settings__theme-boards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
}

.settings__theme-boards i {
  border: 1px solid var(--mini-line);
  border-radius: 2px;
  background-color: var(--mini-cell);
  background-image: linear-gradient(var(--mini-line) 1px, transparent 1px), linear-gradient(90deg, var(--mini-line) 1px, transparent 1px);
  background-size: 16.666% 33.333%;
}

.settings__theme-action {
  width: 34%;
  border-radius: 2px;
  background: var(--mini-accent);
}

.settings__theme-name {
  padding-right: 18px;
  font-size: 13px;
  font-weight: 600;
}

.settings__theme-hint {
  color: var(--text-secondary);
  font-size: 11px;
}

.settings__theme-check {
  position: absolute;
  right: 10px;
  bottom: 11px;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--role-action);
  color: var(--on-accent);
  font-size: 11px;
}

.settings__control-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 14px 20px;
  padding: 15px 0;
}

.settings__control-copy {
  flex: 1 1 180px;
  min-width: 0;
}

.settings__control-copy .settings__note {
  max-width: 62ch;
  margin-top: 3px;
  font-size: 12px;
}

.settings__seg {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 3px;
  max-width: 100%;
  padding: 4px;
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  background: var(--surface-sea);
}

.settings__seg-item {
  min-height: 34px;
  padding: 6px 13px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.settings__seg-item:hover {
  color: var(--text-primary);
  background: var(--surface-raised);
}

.settings__seg-item.is-active {
  background: var(--role-action-soft);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--role-action) 35%, transparent);
}

.settings__seg--colors {
  align-items: center;
  gap: 3px;
  padding: 0;
  border: 0;
  background: transparent;
}

.settings__seg-item--accent.is-swatch {
  display: grid;
  place-items: center;
  width: 33px;
  min-height: 38px;
  padding: 0;
  border-radius: 50%;
}

.settings__seg-item--accent.is-swatch.is-active {
  border-color: transparent;
  background: transparent;
}

.settings__swatch {
  width: 21px;
  height: 21px;
  border-radius: 50%;
  background: var(--swatch);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--text-primary) 18%, transparent);
}

.is-active .settings__swatch {
  outline: 1px solid var(--text-primary);
  outline-offset: 3px;
}

.settings__preview {
  display: grid;
  gap: 20px;
  padding: 20px;
  border: 1px solid var(--border-strong);
  border-radius: 11px;
  background: var(--surface-deck);
}

.settings__preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.settings__preview-head > span {
  padding: 3px 7px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 10px;
}

.settings__preview-demo {
  padding: 14px;
  border: 1px solid var(--board-border);
  border-radius: 8px;
  background: var(--surface-sea);
}

.settings__preview-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 16px;
  color: var(--role-self);
  font-size: 12px;
  font-weight: 600;
}

.settings__preview-label span {
  font-size: 11px;
  font-weight: 400;
}

.settings__preview-board {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 4px;
  margin-bottom: 14px;
}

.settings__preview-cell {
  position: relative;
  aspect-ratio: 1;
  border: 1px solid var(--board-border);
  border-radius: 3px;
  background: var(--cell-bg);
}

.settings__preview-cell.is-ship {
  background: var(--ship-metal);
}

.settings__preview-cell.is-hit {
  border-color: var(--role-enemy);
  background: var(--role-enemy-soft);
}

.settings__preview-cell.is-hit::after,
.settings__preview-cell.is-miss::after {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 600;
}

.settings__preview-cell.is-hit::after {
  content: '×';
  color: var(--role-enemy);
}

.settings__preview-cell.is-miss::after {
  content: '○';
  color: var(--role-self);
}

.settings__preview-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 9px;
  font-size: 11px;
}

.settings__preview-primary {
  flex-basis: 100%;
  padding: 7px 12px;
  border-radius: 5px;
  background: var(--hero-grad);
  color: var(--on-accent);
  font-size: 12px;
  font-weight: 600;
  text-align: center;
}

.settings__preview-secondary {
  color: var(--role-action);
}

.settings__preview-hit {
  color: var(--role-enemy);
}

.settings__preview-miss {
  color: var(--role-self);
}

.settings__preview > .settings__note {
  font-size: 12px;
}

.settings__switch {
  display: flex;
  flex-direction: row-reverse;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 60px;
  padding: 12px 0;
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
}

.settings__switch + .settings__switch {
  border-top: 1px solid var(--border-subtle);
}

.settings__switch > span {
  min-width: 0;
}

.settings__switch input {
  appearance: none;
  position: relative;
  flex: 0 0 40px;
  width: 40px;
  height: 24px;
  margin: 0;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--surface-raised);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease);
}

.settings__switch input::before {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--text-secondary);
  transition: transform var(--duration-fast) var(--ease);
}

.settings__switch input:checked {
  border-color: var(--role-action);
  background: var(--role-action);
}

.settings__switch input:checked::before {
  transform: translateX(16px);
  background: var(--on-accent);
}

.settings__switch input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.settings__switch-hint {
  display: block;
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.settings__note[role='status'] {
  min-height: 24px;
  overflow-wrap: anywhere;
}

.settings__note.is-error,
.settings__state--error {
  color: var(--danger);
}

.settings__login,
.settings__state {
  margin: 0;
  padding: 22px;
  border: 1px solid var(--border-strong);
  border-radius: 9px;
  background: var(--surface-deck);
  color: var(--text-secondary);
  font-size: 14px;
}

.settings__login h2 {
  margin: 0 0 8px;
  color: var(--text-primary);
  font-size: 18px;
}

.settings__login p {
  margin: 0 0 16px;
}

.settings__audio {
  padding-top: 0;
  gap: 18px;
}

.settings__audio-row,
.settings__wallpaper-actions,
.settings__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.settings__audio .settings__control-row {
  padding-bottom: 0;
}

.settings__audio-divider {
  margin-top: 8px;
  border-top: 1px solid var(--border-subtle);
}

.settings__range {
  display: grid;
  grid-template-columns: 100px minmax(80px, 1fr) 46px;
  align-items: center;
  gap: 16px;
  width: min(100%, 620px);
  padding: 0 0 10px;
  color: var(--text-secondary);
  font-size: 13px;
}

.settings__range input {
  width: 100%;
  min-height: 32px;
  margin: 0;
  accent-color: var(--role-action);
}

.settings__range output {
  color: var(--text-primary);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.settings__form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: end;
  gap: 16px;
  max-width: 620px;
}

.settings__form label {
  display: grid;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 13px;
}

.settings__form input {
  width: 100%;
  min-width: 0;
  min-height: 42px;
  padding: 9px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--surface-sea);
  color: var(--text-primary);
  font: inherit;
}

.settings__form button {
  grid-column: 1 / -1;
  justify-self: start;
}

.settings__wallpaper-current {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--role-action) 35%, transparent);
  border-radius: 7px;
  background: var(--role-action-soft);
}

.settings__wallpaper-current-title {
  flex: 1 1 220px;
  min-width: 0;
  color: var(--text-primary);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.settings__wallpaper-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr));
  gap: 14px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.settings__wallpaper-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--surface-deck);
}

.settings__wallpaper-item[data-supported='false'] {
  opacity: 0.7;
}

.settings__wallpaper-preview {
  display: grid;
  grid-column: 1 / -1;
  place-items: center;
  width: 100%;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border-radius: 5px;
  background: var(--surface-chamber);
  color: var(--text-secondary);
  font-size: 12px;
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
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.settings__wallpaper-kind {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.settings__about-list {
  display: grid;
  gap: 16px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.8;
}

.settings__about-list b {
  color: var(--text-primary);
}

.settings__actions {
  padding-top: 2px;
}

.settings__actions .button,
.settings__wallpaper-actions .button,
.settings__audio-row .button {
  min-height: 40px;
}

@media (max-width: 1250px) {
  .settings {
    padding: 22px 28px;
  }

  .settings__layout {
    grid-template-columns: 170px minmax(0, 1fr);
    gap: 24px;
  }

  .settings__nav {
    padding-right: 20px;
  }

  .settings__appearance {
    grid-template-columns: minmax(0, 1fr) 230px;
    gap: 20px;
  }

  .settings__preview {
    padding: 15px;
  }
}

@media (max-width: 1050px) {
  .settings__appearance {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings__preview {
    grid-template-columns: minmax(0, 1fr) 210px;
    align-items: start;
  }

  .settings__preview-head {
    grid-column: 1;
  }

  .settings__preview-demo {
    grid-column: 2;
    grid-row: 1 / span 2;
  }

  .settings__preview > .settings__note {
    grid-column: 1;
    grid-row: 2;
  }
}

@media (max-width: 719px) {
  .settings {
    padding: 18px 14px 24px;
  }

  .settings__modal {
    max-height: none;
  }

  .settings__head {
    align-items: flex-start;
    gap: 12px;
    padding-bottom: 18px;
  }

  .settings__title {
    font-size: 26px;
  }

  .settings__instant {
    gap: 4px;
    margin-top: 6px;
    font-size: 11px;
  }

  .settings__layout {
    display: flex;
    flex-direction: column;
    gap: 22px;
  }

  .settings__nav {
    flex-direction: row;
    gap: 4px;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0 0 10px;
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }

  .settings__nav-item {
    flex: 0 0 auto;
    gap: 6px;
    min-height: 44px;
    padding: 8px 10px;
    font-size: 13px;
  }

  .settings__nav-symbol {
    width: 14px;
    font-size: 16px;
  }

  .settings__nav-note {
    display: none;
  }

  .settings__panes {
    gap: 32px;
    padding: 0;
    overflow: visible;
    scrollbar-gutter: auto;
  }

  .settings__group {
    scroll-margin-top: 76px;
  }

  .settings__themes {
    gap: 7px;
  }

  .settings__theme {
    padding: 7px;
  }

  .settings__theme-scene {
    height: 61px;
    gap: 5px;
    padding: 5px;
  }

  .settings__theme-hint {
    font-size: 10px;
  }

  .settings__theme-check {
    right: 7px;
    bottom: 8px;
    width: 15px;
    height: 15px;
  }

  .settings__control-row {
    gap: 10px;
    padding: 17px 0;
  }

  .settings__control-copy {
    flex-basis: 100%;
  }

  .settings__seg-item,
  .settings__actions .button,
  .settings__audio-row .button,
  .settings__wallpaper-actions .button {
    min-height: 44px;
    min-width: 44px;
  }

  .settings__seg-item--accent.is-swatch {
    width: 42px;
    min-width: 42px;
  }

  .settings__seg--colors {
    gap: 0;
  }

  .settings__preview {
    grid-template-columns: minmax(0, 1fr) 150px;
    gap: 16px;
  }

  .settings__preview-head {
    flex-direction: column;
    align-items: start;
    gap: 8px;
  }

  .settings__preview-demo {
    padding: 10px;
  }

  .settings__preview-board {
    gap: 3px;
  }

  .settings__preview-label {
    gap: 6px;
    margin-bottom: 10px;
    font-size: 10px;
  }

  .settings__preview-actions {
    gap: 7px;
    font-size: 10px;
  }

  .settings__preview-primary {
    font-size: 11px;
  }

  .settings__range {
    grid-template-columns: 76px minmax(70px, 1fr) 40px;
    gap: 10px;
  }

  .settings__form {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (min-width: 720px) and (max-height: 600px) {
  .settings {
    padding-top: 16px;
    padding-bottom: 16px;
  }

  .settings__modal {
    max-height: calc(100dvh - 104px);
  }

  .settings__head {
    padding-bottom: 14px;
  }

  .settings__nav-note {
    display: none;
  }
}

@media (max-width: 359px) {
  .settings__preview {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings__preview-head,
  .settings__preview-demo,
  .settings__preview > .settings__note {
    grid-column: 1;
    grid-row: auto;
  }

  .settings__preview-head {
    flex-direction: row;
  }

  .settings__preview-demo {
    width: min(220px, 100%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .settings__switch input,
  .settings__switch input::before {
    transition: none;
  }
}

:global(html[data-motion='reduced']) .settings__switch input,
:global(html[data-motion='reduced']) .settings__switch input::before {
  transition: none;
}
</style>
