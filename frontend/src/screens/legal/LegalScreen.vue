<script setup lang="ts">
import { computed } from 'vue'

/**
 * 赛季邮箱 v1 · 合规占位页。
 *
 * 这一版只提供结构与已确定的运营事实，正式条款要等发布前由人工补齐。
 * 组件不读路由：Codex 侧在 `/terms`、`/privacy` 上用 props 传入 `kind`。
 */
type LegalKind = 'terms' | 'privacy'

const props = defineProps<{ kind: LegalKind }>()

interface LegalSection {
  id: string
  title: string
  paragraphs: string[]
  bullets?: string[]
}

const title = computed(() => (props.kind === 'terms' ? '用户协议' : '隐私政策'))
const label = computed(() => (props.kind === 'terms' ? '协议' : '隐私'))

const lead = computed(() =>
  props.kind === 'terms'
    ? '这份协议说明《战舰棋》网页版提供什么服务、对局与赛季如何运作，以及账号在什么情况下会被限制。'
    : '这份隐私政策说明《战舰棋》网页版会记录哪些数据、用在哪里、保存多久，以及你能怎么管理它们。',
)

const sections = computed<LegalSection[]>(() =>
  props.kind === 'terms'
    ? [
        {
          id: 'legal-scope',
          title: '一、服务范围',
          paragraphs: [
            '《战舰棋》目前只有网页版，直接在现代浏览器里打开即可游玩，不需要另外下载客户端或安装程序。',
            '单人练习、人机对战、好友房与排位赛都在同一套网页界面里完成；排位赛按赛季结算段位与奖励。',
          ],
        },
        {
          id: 'legal-account',
          title: '二、账号与登录',
          paragraphs: [
            '账号用于区分玩家身份、保存战绩与段位，也是邮箱与好友功能的凭据。',
            '请自行保管登录信息。同一账号下的对局记录会累计，公开榜单展示的是账号名与战绩摘要。',
          ],
        },
        {
          id: 'legal-match',
          title: '三、对局与赛季',
          paragraphs: [
            '对局结果由服务端判定并记录；断线重连后会回到原座位，未结束的对局不会被当作弃权。',
            '排位赛按赛季进行：赛季结束时结算段位与奖励，奖励通过站内邮箱发放，需要手动领取。',
          ],
          bullets: [
            '排位奖励邮件自发放起 30 天内可查看。',
            '邮件附件在 14 天内可领取，领取后在邮箱里保留 7 天。',
            '赛季结束时，达到参与场次门槛的账号才会进入结算。',
          ],
        },
        {
          id: 'legal-conduct',
          title: '四、内容与行为',
          paragraphs: [
            '玩家可以自定义名片、头像描述与房间名。请勿发布违法、侵权或骚扰他人的内容。',
            '使用异常程序、恶意利用对局漏洞或反复干扰他人游戏时，账号可能被限制匹配、禁排位或禁房间。',
          ],
        },
        {
          id: 'legal-change',
          title: '五、变更与联系',
          paragraphs: [
            '功能调整时这份协议会同步更新，重要变化会在游戏内公告或邮箱里提示。',
            '正式条款、生效日期与联系方式会在发布前补齐。',
          ],
        },
      ]
    : [
        {
          id: 'legal-collect',
          title: '一、我们收集什么',
          paragraphs: [
            '登录与账号信息：账号名、头像、密码摘要，以及登录状态所需的会话凭据。',
            '对局信息：房间、座位、布船、每一炮的结果、连锁与结算记录，用于回放、战绩与申诉。',
          ],
        },
        {
          id: 'legal-purpose',
          title: '二、这些数据用来做什么',
          paragraphs: [
            '提供游戏本身：匹配、对局判定、断线重连、回放与观战。',
            '运营与安全：赛季结算、邮箱发放、排行榜、反作弊与异常对局排查。',
          ],
          bullets: [
            '不会出售账号数据，也不会把对局记录用于与游戏无关的广告投放。',
            '公开榜单只展示账号名、段位与战绩摘要，不展示登录凭据。',
          ],
        },
        {
          id: 'legal-retention',
          title: '三、保存期限',
          paragraphs: [
            '账号与对局记录在账号存续期间保留，用于战绩、回放与申诉。',
            '站内邮件与附件按运营规则到期：邮件 30 天、附件 14 天、领取后保留 7 天。',
            '数据库按周生成备份快照，只保留最近 4 份。',
          ],
        },
        {
          id: 'legal-share',
          title: '四、共享与第三方',
          paragraphs: [
            '除法律要求或排查安全事件所必需，不会向第三方提供可识别到个人的对局数据。',
            '页面使用的字体、卡图等静态资源随站点一起提供，不用于跨站追踪。',
          ],
        },
        {
          id: 'legal-choice',
          title: '五、你的选择',
          paragraphs: [
            '可以在设置里调整公开展示与隐私开关，也可以申请注销账号。',
            '如需导出或删除与账号关联的对局记录，可在补齐后的正式条款里按联系方式提出。',
          ],
        },
      ],
)

const updated = '2026-11-04'
</script>

<template>
  <section
    class="screen legal"
    data-screen="legal"
    data-testid="legal-screen"
    :data-kind="kind"
    aria-labelledby="legal-title"
  >
    <header class="legal__head">
      <p class="legal__eyebrow">竞技场 · {{ label }}</p>
      <h1 id="legal-title" class="legal__title" data-testid="legal-heading">{{ title }}</h1>
      <p class="legal__lead">{{ lead }}</p>
      <p class="legal__meta" data-testid="legal-updated">占位版本 · 最后更新 {{ updated }}</p>
    </header>

    <p class="legal__notice" data-testid="legal-notice" role="note">
      <b>正文待正式发布前补齐。</b>
      本页先把结构与已经确定的运营事实写清楚，正式条款、生效日期与联系方式会在发布前由人工补完，因此这里的内容不构成最终法律承诺。
    </p>

    <div class="legal__body">
      <nav class="legal__toc" data-testid="legal-toc" aria-label="页内目录">
        <p class="legal__toc-title">本页内容</p>
        <a v-for="section in sections" :key="section.id" class="legal__toc-link" :href="'#' + section.id">
          {{ section.title.replace(/^[一二三四五]、/, '') }}
        </a>
      </nav>

      <article class="legal__doc" data-testid="legal-doc">
        <section v-for="section in sections" :id="section.id" :key="section.id" class="legal__section">
          <h2 class="legal__section-title">{{ section.title }}</h2>
          <p v-for="(text, index) in section.paragraphs" :key="index" class="legal__text">{{ text }}</p>
          <ul v-if="section.bullets" class="legal__list">
            <li v-for="(item, index) in section.bullets" :key="index">{{ item }}</li>
          </ul>
        </section>

        <p class="legal__foot-note">
          页面结构与说明由运营整理；正式文本补齐时会替换本页全部段落，并保留同样的章节编号。
        </p>
      </article>
    </div>

    <footer class="legal__actions">
      <router-link class="legal__action" :to="{ name: 'start' }" data-testid="legal-home">返回首页</router-link>
      <router-link class="legal__action legal__action--quiet" :to="{ name: 'settings' }" data-testid="legal-settings">
        前往设置
      </router-link>
    </footer>
  </section>
</template>

<style scoped>
.legal {
  max-width: 1040px;
  margin: 0 auto;
  gap: 16px;
}

.legal__head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.legal__eyebrow {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-secondary);
}

.legal__title {
  margin: 0;
  font-size: clamp(24px, 4vw, 30px);
  line-height: 1.25;
  color: var(--text-primary);
}

.legal__lead {
  margin: 0;
  max-width: 62ch;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.legal__meta {
  margin: 0;
  font-size: 11px;
  color: var(--text-secondary);
  opacity: 0.78;
}

/* 全页唯一的强调块：只用来提醒「这是占位稿」。 */
.legal__notice {
  margin: 0;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--gold) 42%, transparent);
  background: color-mix(in srgb, var(--gold) 10%, transparent);
  color: var(--text-primary);
  font-size: 12.5px;
  line-height: 1.75;
}

.legal__notice b {
  color: var(--gold-strong, var(--gold));
}

.legal__body {
  display: grid;
  grid-template-columns: 172px minmax(0, 1fr);
  gap: 22px;
  align-items: start;
  min-width: 0;
}

.legal__toc {
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--panel);
}

.legal__toc-title {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}

.legal__toc-link {
  padding: 5px 6px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  text-decoration: none;
}

.legal__toc-link:hover,
.legal__toc-link:focus-visible {
  background: var(--surface-raised);
  color: var(--text-primary);
}

.legal__doc {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 18px 20px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--panel);
}

.legal__section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  scroll-margin-top: 14px;
}

.legal__section-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.legal__text {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.85;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}

.legal__list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12.5px;
  line-height: 1.8;
  color: var(--text-secondary);
}

.legal__foot-note {
  margin: 4px 0 0;
  padding-top: 12px;
  border-top: 1px dashed var(--border-subtle);
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  opacity: 0.85;
}

.legal__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.legal__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 16px;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--role-self) 46%, transparent);
  background: color-mix(in srgb, var(--role-self) 16%, transparent);
  color: var(--text-primary);
  font-size: 12.5px;
  text-decoration: none;
}

.legal__action:hover,
.legal__action:focus-visible {
  background: color-mix(in srgb, var(--role-self) 26%, transparent);
}

.legal__action--quiet {
  border-color: var(--border-subtle);
  background: var(--surface-raised);
  color: var(--text-secondary);
}

.legal__action--quiet:hover,
.legal__action--quiet:focus-visible {
  background: var(--surface-deck);
  color: var(--text-primary);
}

@media (max-width: 860px) {
  .legal__body {
    grid-template-columns: minmax(0, 1fr);
    gap: 14px;
  }

  .legal__toc {
    position: static;
    flex-direction: row;
    flex-wrap: wrap;
    gap: 6px;
    padding: 8px;
  }

  .legal__toc-title {
    display: none;
  }

  .legal__toc-link {
    border: 1px solid var(--border-subtle);
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 11.5px;
  }

  .legal__doc {
    padding: 14px 15px;
  }

  .legal__text,
  .legal__list {
    font-size: 13px;
  }
}

@media (max-width: 520px) {
  .legal {
    gap: 12px;
  }

  .legal__title {
    font-size: 22px;
  }

  .legal__action {
    flex: 1 1 auto;
  }
}
</style>
