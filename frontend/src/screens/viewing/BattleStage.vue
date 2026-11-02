<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import BoardPanel from '../game/BoardPanel.vue'
import { cardArtUrl } from '../../cards/cardArt'
import { CARDS } from '../../cards/cardData'
import '../game/card-inspect.css'
import { boardCells, sides } from './frame'
import type { Side, ViewCard, ViewFrame } from './types'

const props = defineProps<{ frame: ViewFrame; mode: 'replay' | 'spectate'; focus?: Side }>()
const cells = computed(() => ({ p1: boardCells(props.frame, 'p1'), p2: boardCells(props.frame, 'p2') }))
const selected = ref<ViewCard | null>(null)
const preview = ref<ViewCard | null>(null), tooltip = ref<HTMLElement | null>(null)
const previewPosition = ref({ left: '0px', top: '0px', visibility: 'hidden' as 'hidden' | 'visible' })
const describe = (card: ViewCard): ViewCard => ({ ...CARDS.find(known => known.name === card.name), ...card })
async function showPreview(card: ViewCard, event: Event): Promise<void> {
  if (matchMedia('(hover: none)').matches) return
  const anchor = (event.currentTarget as HTMLElement).getBoundingClientRect()
  preview.value = describe(card); previewPosition.value.visibility = 'hidden'
  await nextTick()
  if (!preview.value || !tooltip.value) return
  const bounds = tooltip.value.getBoundingClientRect()
  previewPosition.value = {
    left: Math.max(10, Math.min(innerWidth - bounds.width - 10, anchor.left + anchor.width / 2 - bounds.width / 2)) + 'px',
    top: Math.max(10, Math.min(innerHeight - bounds.height - 10, anchor.top - bounds.height - 12)) + 'px', visibility: 'visible',
  }
}
</script>

<template>
  <section class="view-battle" data-testid="viewing-battle-stage" :data-view-mode="mode" aria-label="双方战斗海域">
    <div class="view-battle__sea">
      <div v-for="side in sides" :key="side" class="view-battle__half" :data-owner="side" :class="{ 'is-turn': frame.context.state !== 'game_over' && frame.context.current_side === side }">
        <header class="view-player" :data-testid="mode + '-player-' + side">
          <span class="view-player__flag">{{ side === 'p1' ? 'Ⅰ' : 'Ⅱ' }}</span>
          <div><strong>{{ frame.players[side].name }}</strong><small>{{ frame.context.state === 'game_over' ? frame.context.winner === side ? '本局获胜' : '对局结束' : frame.context.current_side === side ? '正在行动' : '舰队待命' }}</small></div>
          <b>{{ frame.players[side].remaining_ships }}<small> 艘</small></b>
        </header>
        <BoardPanel :board="side === 'p1' ? 'self' : 'opponent'" :board-testid="mode + '-board-' + side"
          :title-testid="mode + '-board-title-' + side" :title="frame.players[side].name + ' 的海域'"
          :cells="cells[side]" :interactive="false" :cell-prefix="mode + '-cell-' + side" />
        <div class="view-fleet-effects"><span v-for="(effect, i) in frame.players[side].effects" :key="i">{{ effect.label || effect.name }}</span></div>
      </div>
      <div class="view-battle__divider" aria-hidden="true"><span>交战海域</span></div>
    </div>
    <div class="view-hands">
      <section v-for="side in sides" :key="side" :data-testid="mode + '-hand-' + side" class="view-hand">
        <header><b>{{ frame.players[side].name }}</b><span>手牌 {{ frame.players[side].hand_count }} 张</span></header>
        <div v-if="frame.players[side].cards" class="view-hand__cards">
          <button v-for="(card, i) in frame.players[side].cards" :key="i" type="button" class="view-card" :aria-label="'查看 ' + card.name" :aria-describedby="preview?.name === card.name ? mode + '-card-preview' : undefined"
            @mouseenter="showPreview(card,$event)" @focus="showPreview(card,$event)" @mouseleave="preview = null" @blur="preview = null"
            @click="preview = null; selected = describe(card)">
            <img v-if="cardArtUrl(card.name)" :src="cardArtUrl(card.name)!" :alt="card.name" /><span class="view-card__name">{{ card.name }}</span>
          </button>
          <small v-if="!frame.players[side].cards?.length" class="view-empty">暂无手牌</small>
        </div>
        <div v-else class="view-hand__hidden"><i v-for="i in Math.min(8, frame.players[side].hand_count)" :key="i"></i><small>牌面未公开</small></div>
      </section>
    </div>
    <Teleport to="body">
      <aside v-if="preview" :id="mode + '-card-preview'" ref="tooltip" class="game-card-inspect view-card-preview" data-testid="viewing-card-hover-preview" role="tooltip" :style="previewPosition">
        <div class="game-card-inspect__art" :class="{ 'is-empty': !cardArtUrl(preview.name) }"><img v-if="cardArtUrl(preview.name)" :src="cardArtUrl(preview.name)!" :alt="preview.name + ' 卡面预览'" /><span v-else>{{ preview.name }}</span></div>
        <div class="game-card-inspect__body"><div class="game-card-inspect__head"><strong>{{ preview.name }}</strong><span>速阶 {{ preview.speed }} · {{ preview.type }}</span></div><p>{{ preview.description || '这张牌没有记录效果说明。' }}</p><small class="game-card-inspect__hint">点击查看完整卡牌</small></div>
      </aside>
      <div v-if="selected" class="view-card-dialog" role="dialog" aria-modal="true" :aria-label="selected.name" @click.self="selected = null" @keydown.esc="selected = null">
        <section><button type="button" autofocus @click="selected = null">关闭</button><img v-if="cardArtUrl(selected.name)" :src="cardArtUrl(selected.name)!" :alt="selected.name" /><h2>{{ selected.name }}</h2><small>速阶 {{ selected.speed }} · {{ selected.type }}</small><p>{{ selected.description }}</p></section>
      </div>
    </Teleport>
  </section>
</template>
