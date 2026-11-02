<script setup lang="ts">
import { computed, ref } from 'vue'
import BoardPanel from '../game/BoardPanel.vue'
import { cardArtUrl } from '../../cards/cardArt'
import { boardCells, sides } from './frame'
import type { Side, ViewCard, ViewFrame } from './types'

const props = defineProps<{ frame: ViewFrame; mode: 'replay' | 'spectate'; focus?: Side }>()
const cells = computed(() => ({ p1: boardCells(props.frame, 'p1'), p2: boardCells(props.frame, 'p2') }))
const selected = ref<ViewCard | null>(null)
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
          <button v-for="(card, i) in frame.players[side].cards" :key="i" type="button" class="view-card" :title="card.name" @click="selected = card">
            <img v-if="cardArtUrl(card.name)" :src="cardArtUrl(card.name)!" :alt="card.name" /><span v-else>{{ card.name }}</span>
          </button>
          <small v-if="!frame.players[side].cards?.length" class="view-empty">暂无手牌</small>
        </div>
        <div v-else class="view-hand__hidden"><i v-for="i in Math.min(8, frame.players[side].hand_count)" :key="i"></i><small>牌面未公开</small></div>
      </section>
    </div>
    <Teleport to="body">
      <div v-if="selected" class="view-card-dialog" role="dialog" aria-modal="true" :aria-label="selected.name" @click.self="selected = null" @keydown.esc="selected = null">
        <section><button type="button" autofocus @click="selected = null">关闭</button><img v-if="cardArtUrl(selected.name)" :src="cardArtUrl(selected.name)!" :alt="selected.name" /><h2>{{ selected.name }}</h2><p>{{ selected.description }}</p></section>
      </div>
    </Teleport>
  </section>
</template>
