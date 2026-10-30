/**
 * Copy the frozen magic-card table into the SPA at build time.
 *
 * The backend JSON (backend/src/battleship/domain/magic/data/magic_card.json)
 * is the single source: the same bytes the server loads are the bytes the
 * collection overlay renders. A hand-edited frontend copy would be a second
 * implementation of the card pool, which this project has learned to ban.
 *
 * The script is idempotent (identical content = no write) and validates the
 * frozen counts before writing, so a truncated table fails the build instead of
 * silently shrinking the collection.
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const source = path.resolve(here, '../../backend/src/battleship/domain/magic/data/magic_card.json')
const target = path.resolve(here, '../src/cards/card_data.json')

const CARD_COUNT = 50
const UNIQUE_CARD_COUNT = 48
const DUPLICATE_ALLOWED = '失灵！'

if (!existsSync(source)) {
  throw new Error('[cards] backend card table missing: ' + source)
}

let rows
try {
  rows = JSON.parse(readFileSync(source, 'utf8'))
} catch (error) {
  throw new Error('[cards] backend card table is not valid JSON: ' + error.message)
}
if (!Array.isArray(rows) || rows.length !== CARD_COUNT) {
  throw new Error('[cards] expected ' + CARD_COUNT + ' rows, got ' + (Array.isArray(rows) ? rows.length : 'non-array'))
}

const seen = new Map()
for (const row of rows) {
  if (!row || typeof row.name !== 'string' || typeof row.type !== 'string') {
    throw new Error('[cards] malformed row: ' + JSON.stringify(row))
  }
  if (![1, 2, 3].includes(row.speed)) {
    throw new Error('[cards] illegal speed for ' + row.name + ': ' + row.speed)
  }
  seen.set(row.name, (seen.get(row.name) || 0) + 1)
}
if (seen.size !== UNIQUE_CARD_COUNT) {
  throw new Error('[cards] expected ' + UNIQUE_CARD_COUNT + ' unique names, got ' + seen.size)
}
for (const [name, count] of seen) {
  if (count > 1 && name !== DUPLICATE_ALLOWED) {
    throw new Error('[cards] duplicate name without an exception: ' + name + ' x' + count)
  }
}

const payload = JSON.stringify(rows, null, 2) + '\n'
let current = ''
try {
  current = readFileSync(target, 'utf8')
} catch {
  current = ''
}
if (current !== payload) {
  writeFileSync(target, payload, 'utf8')
  console.log('[cards] synced ' + rows.length + ' cards -> ' + path.relative(here, target))
} else {
  console.log('[cards] up to date (' + rows.length + ' cards)')
}
