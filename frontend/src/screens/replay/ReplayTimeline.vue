<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { timelineNodes, positionAt, stepAt, type TimelineNode } from '../viewing/timeline'
const props = defineProps<{ nodes: TimelineNode[]; count: number; step: number }>()
const emit = defineEmits<{ seek: [step: number] }>()
const nodes = computed(() => timelineNodes(props.nodes, props.count))
const active = computed(() => {
  let index = 0
  for (let i = 0; i < nodes.value.length; i++) if (nodes.value[i].step <= props.step) index = i
  return index
})
const track = ref<HTMLElement | null>(null)
watch(active, async () => {
  await nextTick()
  const marker = track.value?.querySelector<HTMLElement>('[aria-current="step"]')
  if (marker && track.value) track.value.scrollLeft = Math.max(0, marker.offsetLeft - track.value.clientWidth / 2)
})
</script>
<template>
  <section class="replay-timeline" data-testid="replay-timeline" aria-label="按关键节点排列的回放时间线">
    <header><span>{{ nodes[active]?.label }}</span><small>节点 {{ active + 1 }}/{{ nodes.length }}</small></header>
    <div ref="track" class="replay-timeline__viewport">
      <div class="replay-timeline__rail" :style="{ minWidth: Math.max(0, (nodes.length - 1) * 36) + 'px' }">
        <input type="range" min="0" max="1000" step="1" :value="positionAt(step,nodes)" :disabled="count < 2"
          aria-label="回放进度" :aria-valuetext="'第 ' + (step + 1) + ' 步，' + nodes[active]?.label" data-testid="replay-progress"
          @input="emit('seek',stepAt(Number(($event.target as HTMLInputElement).value),nodes))" />
        <button v-for="(node,i) in nodes" :key="node.step" type="button" class="replay-timeline__node"
          :style="{ left: (nodes.length > 1 ? i / (nodes.length - 1) * 100 : 0) + '%' }" :class="['is-' + node.kind, { 'is-past': node.step <= step }]"
          :data-step="node.step" :aria-current="i === active ? 'step' : undefined" :title="'第 ' + (node.step + 1) + ' 步 · ' + node.label"
          :aria-label="'跳转：' + node.label" @click="emit('seek',node.step)"><i></i></button>
      </div>
    </div>
    <footer><span>开始</span><span>点击节点跳转 · 拖动可查看节点之间的过程</span><span>结束</span></footer>
  </section>
</template>
<style scoped>
.replay-timeline { min-width:0; padding:10px 14px; border:1px solid var(--board-border); border-radius:10px; background:var(--panel-bg); }
.replay-timeline header { display:flex; justify-content:space-between; gap:12px; font-size:12px; }
.replay-timeline header>span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.replay-timeline small { color:var(--text-secondary); white-space:nowrap; }
.replay-timeline__viewport { overflow-x:auto; padding:0 14px; scrollbar-width:thin; }
.replay-timeline__rail { position:relative; width:100%; height:38px; }
.replay-timeline__rail input { position:absolute; inset:0; margin:0; width:100%; height:38px; accent-color:var(--accent-primary,#2dc7e7); cursor:pointer; }
.replay-timeline__node { position:absolute; top:0; transform:translateX(-50%); display:grid; place-items:center; min-width:0; width:26px; height:38px; padding:0; border:0; background:transparent; cursor:pointer; }
.replay-timeline__node i { width:9px; height:9px; border:2px solid var(--board-border); border-radius:50%; background:var(--panel-bg); }
.replay-timeline__node.is-past i { background:var(--accent-primary,#2dc7e7); border-color:var(--accent-primary,#2dc7e7); }
.replay-timeline__node.is-magic i { border-radius:2px; transform:rotate(45deg); }
.replay-timeline__node.is-sunk i { border-radius:2px; border-color:var(--role-enemy,#ee8d99); }
.replay-timeline__node[aria-current] i,.replay-timeline__node:hover i,.replay-timeline__node:focus-visible i { outline:2px solid var(--text-primary); outline-offset:3px; }
.replay-timeline footer { display:flex; justify-content:space-between; gap:8px; font-size:10px; color:var(--text-secondary); }
@media(max-width:430px) { .replay-timeline { padding:8px 10px; }.replay-timeline footer>span:nth-child(2) { max-width:160px; text-align:center; } }
</style>
