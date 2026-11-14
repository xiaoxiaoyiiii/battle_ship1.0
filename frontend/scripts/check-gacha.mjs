#!/usr/bin/env node
/**
 * Pure unit checks for the skin-gacha v1 mappers and art helpers.
 * No network, no database. Imports the same ESM module the store uses.
 */
import {
  isValidRequestId,
  createRequestId,
  mapGachaPull,
  mapGachaPullResult,
  normalizeSkinId,
  resolveCardArtUrl,
} from './gacha-map.mjs'

let failed = 0

function assert(name, condition, detail = '') {
  if (condition) {
    console.log(`ok  ${name}`)
    return
  }
  failed += 1
  console.error(`fail  ${name}${detail ? ` — ${detail}` : ''}`)
}

function deepEqual(actual, expected) {
  return JSON.stringify(actual) === JSON.stringify(expected)
}

const shardRow = {
  index: 0,
  kind: 'shard',
  skin_id: null,
  card_key: null,
  card_name: null,
  is_new: false,
  shards_gained: 1,
}

assert(
  'mapGachaPull maps a shard row with skin_id:null',
  deepEqual(mapGachaPull(shardRow), {
    index: 0,
    kind: 'shard',
    skinId: null,
    cardKey: null,
    cardName: null,
    isNew: false,
    shardsGained: 1,
  }),
  JSON.stringify(mapGachaPull(shardRow)),
)

const skinRow = {
  index: 1,
  kind: 'legendary',
  skin_id: 'neon-kanpo',
  card_key: 'kanpo',
  card_name: '看破！',
  is_new: true,
  shards_gained: 0,
}

assert(
  'mapGachaPull maps a legendary pull to camelCase',
  deepEqual(mapGachaPull(skinRow), {
    index: 1,
    kind: 'legendary',
    skinId: 'neon-kanpo',
    cardKey: 'kanpo',
    cardName: '看破！',
    isNew: true,
    shardsGained: 0,
  }),
  JSON.stringify(mapGachaPull(skinRow)),
)

const payload = {
  ok: true,
  request_id: '9f1c2e7a-3b4d-4c5e-8f60-1a2b3c4d5e6f',
  replayed: false,
  count: 10,
  cost: 800,
  currency: 'tide_ash',
  results: [
    shardRow,
    skinRow,
    {
      index: 2,
      kind: 'legendary',
      skin_id: 'neon-hongzha',
      card_key: 'hongzha',
      card_name: '轰炸',
      is_new: false,
      shards_gained: 5,
    },
  ],
  summary: { new_skins: ['neon-kanpo'], duplicates: 1, shards_gained: 6 },
  balance: 440,
  shards: 49,
  progress: { owned: 3, total: 12, complete: false },
}

const mapped = mapGachaPullResult(payload)
assert('mapGachaPullResult.requestId', mapped.requestId === payload.request_id)
assert('mapGachaPullResult.replayed', mapped.replayed === false)
assert('mapGachaPullResult.count', mapped.count === 10)
assert('mapGachaPullResult.balance', mapped.balance === 440)
assert('mapGachaPullResult.shards', mapped.shards === 49)
assert('mapGachaPullResult.results[0].skinId is null', mapped.results[0].skinId === null && mapped.results[0].kind === 'shard')
assert('mapGachaPullResult.results[1].isNew', mapped.results[1].isNew === true && mapped.results[1].skinId === 'neon-kanpo')
assert('mapGachaPullResult.results[2].shardsGained', mapped.results[2].shardsGained === 5 && mapped.results[2].isNew === false)
assert('mapGachaPullResult.summary.newSkins', mapped.summary.newSkins[0] === 'neon-kanpo')

assert('isValidRequestId accepts UUID', isValidRequestId('9f1c2e7a-3b4d-4c5e-8f60-1a2b3c4d5e6f'))
assert('isValidRequestId accepts 8-char token', isValidRequestId('abcdEF12'))
assert('isValidRequestId rejects short', !isValidRequestId('abc_def'))
assert('isValidRequestId rejects empty', !isValidRequestId(''))
assert('isValidRequestId rejects spaces', !isValidRequestId('not valid id!!'))
assert('isValidRequestId rejects overlong', !isValidRequestId('x'.repeat(65)))
assert('createRequestId matches the contract pattern', isValidRequestId(createRequestId()))

assert('normalizeSkinId(null) → null', normalizeSkinId(null) === null)
assert('normalizeSkinId(undefined) → null', normalizeSkinId(undefined) === null)
assert('normalizeSkinId("") → null', normalizeSkinId('') === null)
assert('normalizeSkinId("default") → null', normalizeSkinId('default') === null)
assert('normalizeSkinId("  default  ") → null', normalizeSkinId('  default  ') === null)
assert('normalizeSkinId("neon-kanpo")', normalizeSkinId('neon-kanpo') === 'neon-kanpo')

const defaults = { '看破！': '/art/kanpo.webp', '轰炸': '/art/hongzha.webp' }
const manifest = {
  'neon-kanpo': { url: '/skins/neon-kanpo.webp', cardKey: 'kanpo', tier: 'legendary' },
  'neon-hongzha': { src: '/skins/neon-hongzha.webp' },
}

const defaultUrl = (name) => defaults[name] ?? null

assert(
  'resolveCardArtUrl null skin → default',
  resolveCardArtUrl('看破！', null, { defaultUrl, manifest }) === '/art/kanpo.webp',
)
assert(
  'resolveCardArtUrl missing skin → default',
  resolveCardArtUrl('看破！', undefined, { defaultUrl, manifest }) === '/art/kanpo.webp',
)
assert(
  'resolveCardArtUrl "default" → default',
  resolveCardArtUrl('看破！', 'default', { defaultUrl, manifest }) === '/art/kanpo.webp',
)
assert(
  'resolveCardArtUrl unknown skin id → default',
  resolveCardArtUrl('看破！', 'neon-unknown', { defaultUrl, manifest }) === '/art/kanpo.webp',
)
assert(
  'resolveCardArtUrl known skin uses manifest url',
  resolveCardArtUrl('看破！', 'neon-kanpo', { defaultUrl, manifest }) === '/skins/neon-kanpo.webp',
)
assert(
  'resolveCardArtUrl reads src field',
  resolveCardArtUrl('轰炸', 'neon-hongzha', { defaultUrl, manifest }) === '/skins/neon-hongzha.webp',
)
assert(
  'resolveCardArtUrl empty manifest → default',
  resolveCardArtUrl('看破！', 'neon-kanpo', { defaultUrl, manifest: null }) === '/art/kanpo.webp',
)

if (failed) {
  console.error(`\n${failed} check(s) failed`)
  process.exit(1)
}
console.log('\nall gacha checks passed')
