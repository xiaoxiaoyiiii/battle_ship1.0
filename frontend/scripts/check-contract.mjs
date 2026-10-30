#!/usr/bin/env node
/**
 * Build-time contract gate (ticket #21).
 *
 * The typed socket client imports `CONTRACT_SCHEMA_HASH` from the generated
 * `src/socket/events.gen.ts`. If the backend contract changed and the file was
 * not regenerated, the bundle would silently talk a stale schema. This script
 * asks the backend for the authoritative canonical hash and fails the build on
 * any mismatch.
 *
 * Usage:
 *   node scripts/check-contract.mjs             # gate the real generated file
 *   node scripts/check-contract.mjs --file X    # gate another copy (gate test)
 *
 * The interpreter is auto-detected (BATTLESHIP_PYTHON, the repo venv, the
 * shared verify venv, then PATH). A missing interpreter fails closed: an
 * unverified contract must not produce a deployable bundle.
 */

import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(HERE, '..')
const REPO_ROOT = path.resolve(FRONTEND, '..')
const BACKEND_SRC = path.join(REPO_ROOT, 'backend', 'src')
const DEFAULT_TS = path.join(FRONTEND, 'src', 'socket', 'events.gen.ts')

function parseArgs(argv) {
  const args = { file: DEFAULT_TS }
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--file') args.file = path.resolve(argv[++index])
    else throw new Error(`unknown argument: ${argv[index]}`)
  }
  return args
}

function readBundledHash(file) {
  const text = fs.readFileSync(file, 'utf8')
  const match = text.match(/CONTRACT_SCHEMA_HASH = '([0-9a-f]{64})'/)
  if (!match) throw new Error(`no CONTRACT_SCHEMA_HASH in ${file}`)
  return match[1]
}

function pythonCandidates() {
  const win = process.platform === 'win32'
  return [
    process.env.BATTLESHIP_PYTHON,
    path.join(REPO_ROOT, '.venv', win ? 'Scripts/python.exe' : 'bin/python'),
    'D:/develop/battleship-verify/.venv/Scripts/python.exe',
    win ? 'python' : 'python3',
    win ? 'py' : 'python',
  ].filter(Boolean)
}

function backendHash(python) {
  return spawnSync(
    python,
    ['-m', 'battleship.contracts.export_schema', '--print-hash'],
    {
      cwd: REPO_ROOT,
      env: { ...process.env, PYTHONPATH: BACKEND_SRC, PYTHONIOENCODING: 'utf-8' },
      encoding: 'utf8',
      timeout: 60000,
    },
  )
}

function authoritativeHash() {
  const failures = []
  for (const python of pythonCandidates()) {
    if (python.includes('/') && !fs.existsSync(python)) continue
    const result = backendHash(python)
    if (result.error || result.status !== 0) {
      failures.push(`${python}: ${result.error?.message || (result.stderr || '').trim().slice(-300)}`)
      continue
    }
    const hash = (result.stdout || '').trim().split(/\r?\n/).pop()
    if (!/^[0-9a-f]{64}$/.test(hash)) {
      failures.push(`${python}: unexpected output ${JSON.stringify(hash)}`)
      continue
    }
    return { hash, python }
  }
  console.error('[contract] cannot verify the contract hash: no interpreter could import battleship.contracts.')
  for (const failure of failures) console.error('  - ' + failure)
  console.error('  set BATTLESHIP_PYTHON to a Python that has the backend dependencies installed.')
  process.exit(2)
}

const args = parseArgs(process.argv.slice(2))
const bundled = readBundledHash(args.file)
const { hash: expected, python } = authoritativeHash()

if (bundled !== expected) {
  console.error('[contract] CONTRACT_SCHEMA_HASH mismatch — the generated client is stale.')
  console.error('  bundled:      ' + bundled)
  console.error('  backend:      ' + expected)
  console.error('  regenerate:   PYTHONPATH=backend/src ' + python +
    ' -m battleship.contracts.export_schema --format ts --out frontend/src/socket/events.gen.ts')
  process.exit(1)
}

console.log('[contract] OK ' + expected)
