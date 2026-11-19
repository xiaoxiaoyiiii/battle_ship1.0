<script setup lang="ts">
import { computed } from 'vue'
import CardFaceArt from '../../cards/CardFaceArt.vue'
import CommanderSkillCard from '../../components/commander/CommanderSkillCard.vue'
import { parseStack } from '../game/chainAnimation'
import type { Json } from './types'

const props = defineProps<{ chain: Json | null; mode: 'replay' | 'spectate'; cue: Json | null }>()
const cards = computed(() => parseStack(props.chain))
const entering = computed(() => {
  if (props.cue?.stage !== 'join') return null
  const stack = parseStack(props.cue)
  return stack.at(-1) ?? null
})
</script>

<template>
  <section class="viewing__panel">
    <h2>当前连锁</h2>
    <ol :data-testid="mode + '-chain'" class="view-chain">
      <li v-for="card in cards" :key="card.id || card.order" class="view-chain__card" :class="{ 'is-negated': card.negated }">
        <CommanderSkillCard v-if="card.skillId" :skill-id="card.skillId" :order="card.order" :speed="card.speed"
          :negated="card.negated" :entering="entering?.skillId === card.skillId && entering?.order === card.order" />
        <template v-else>
          <CardFaceArt class="view-chain__art" :name="card.name" :skin-id="card.skinId" :context="mode" fit="cover" alt="" />
          <span class="view-chain__order">{{ card.order }}</span>
          <span class="view-chain__name">{{ card.name }}<small v-if="card.negated">已无效</small></span>
        </template>
      </li>
    </ol>
    <small v-if="!cards.length" class="view-empty">当前没有连锁</small>
  </section>
</template>
