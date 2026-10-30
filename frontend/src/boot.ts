/**
 * `window.__BOOT__`: the startup data the shell injects into index.html.
 *
 * Spec (Implementation Decisions · static/templates): the SPA shell carries a
 * startup JSON instead of the legacy template's per-variable globals. The
 * backend injects it with the signed-session identity, the online counters, the
 * contract hash and the build id, so the first frame needs no API round trip.
 *
 * Everything here degrades to the API: a missing or malformed payload returns
 * null and the stores fetch as before. This module never mutates the global.
 */
export interface BootUser {
  id: string
  username: string
  guest: boolean
}

export interface BootQueue {
  casual: number | null
  ranked: number | null
}

export interface BootHomeStats {
  online_count: number | null
  queue: BootQueue | null
  lobby_rooms: number | null
}

export interface BootPayload {
  version: number
  build_id: string
  contract_hash: string
  user: BootUser | null
  online_count: number | null
  home_stats: BootHomeStats | null
}

declare global {
  interface Window {
    __BOOT__?: BootPayload
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** The injected payload, or null when the shell did not carry one. */
export function readBoot(): BootPayload | null {
  if (typeof window === 'undefined') return null
  const raw: unknown = window.__BOOT__
  if (!isObject(raw)) return null
  const user = isObject(raw.user)
    ? {
        id: asString(raw.user.id),
        username: asString(raw.user.username),
        guest: raw.user.guest === true,
      }
    : null
  const stats = isObject(raw.home_stats) ? raw.home_stats : null
  return {
    version: typeof raw.version === 'number' ? raw.version : 0,
    build_id: asString(raw.build_id),
    contract_hash: asString(raw.contract_hash),
    user,
    online_count: asNumberOrNull(raw.online_count),
    home_stats: stats
      ? {
          online_count: asNumberOrNull(stats.online_count),
          queue: isObject(stats.queue)
            ? {
                casual: asNumberOrNull(stats.queue.casual),
                ranked: asNumberOrNull(stats.queue.ranked),
              }
            : null,
          lobby_rooms: asNumberOrNull(stats.lobby_rooms),
        }
      : null,
  }
}

/** `/api/home_stats`-shaped payload from the boot JSON, or null when absent. */
export function bootHomeStats(): Record<string, unknown> | null {
  const boot = readBoot()
  const stats = boot?.home_stats
  if (!boot || !stats) return null
  return {
    online_count: stats.online_count,
    queue: stats.queue,
    lobby_rooms: stats.lobby_rooms,
  }
}
