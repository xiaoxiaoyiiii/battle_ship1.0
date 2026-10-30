import { io, type Socket } from 'socket.io-client'
import {
  CONTRACT_SCHEMA_HASH,
  type AckResponse,
  type InboundEvent,
  type OutboundEvent,
} from './events.gen'

/**
 * Typed Socket.IO client (ticket #21).
 *
 * * Build time: `scripts/check-contract.mjs` fails the build when events.gen.ts
 *   is stale, so the imported event names/types cannot drift from the backend.
 * * Runtime: `checkContract()` compares the server's canonical hash with the
 *   bundled one. A mismatch is surfaced on the console and through the
 *   onContractMismatch callback; it never crashes the shell.
 */

export class ContractHashMismatchError extends Error {
  constructor(readonly bundled: string, readonly remote: string) {
    super(
      'contract schema hash mismatch: the frontend bundle and the backend disagree ' +
        `(bundled ${bundled.slice(0, 12)}…, server ${remote.slice(0, 12)}…)`,
    )
    this.name = 'ContractHashMismatchError'
  }
}

export function verifyContractHash(remote: string, bundled: string = CONTRACT_SCHEMA_HASH): void {
  if (remote !== bundled) throw new ContractHashMismatchError(bundled, remote)
}

export async function fetchRemoteContractHash(fetchImpl: typeof fetch = fetch): Promise<string> {
  const response = await fetchImpl('/api/contracts/schema', {
    headers: { accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!response.ok) throw new Error(`contract schema request failed: HTTP ${response.status}`)
  const body = (await response.json()) as { hash?: unknown }
  if (typeof body.hash !== 'string' || !/^[0-9a-f]{64}$/.test(body.hash)) {
    throw new Error('contract schema response has no canonical hash')
  }
  return body.hash
}

export interface TypedSocketOptions {
  url?: string
  autoConnect?: boolean
  ackTimeoutMs?: number
  onContractMismatch?: (error: Error) => void
}

export interface TypedSocket {
  socket: Socket
  emitEvent: <E extends InboundEvent>(event: E, data?: Record<string, unknown>) => Promise<AckResponse>
  on: <E extends OutboundEvent>(event: E, handler: (payload: Record<string, unknown>) => void) => () => void
  checkContract: () => Promise<boolean>
  connect: () => void
  disconnect: () => void
}

export function createTypedSocket(options: TypedSocketOptions = {}): TypedSocket {
  const socket = io(options.url, {
    autoConnect: options.autoConnect ?? false,
    withCredentials: true,
    transports: ['websocket', 'polling'],
  })
  const ackTimeoutMs = options.ackTimeoutMs ?? 8000

  function emitEvent<E extends InboundEvent>(
    event: E,
    data: Record<string, unknown> = {},
  ): Promise<AckResponse> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`ack timeout after ${ackTimeoutMs}ms: ${event}`))
      }, ackTimeoutMs)
      socket.emit(event, data, (response: AckResponse) => {
        clearTimeout(timer)
        resolve(response)
      })
    })
  }

  // socket.io-client's typed `on` overloads cannot express "arbitrary outbound
  // event name with a single payload object"; the event union is still enforced
  // by the generic signature and by the build-time contract hash check.
  type RawListener = (payload: Record<string, unknown>) => void
  const raw = socket as unknown as {
    on: (event: string, listener: RawListener) => void
    off: (event: string, listener: RawListener) => void
  }

  function on<E extends OutboundEvent>(
    event: E,
    handler: (payload: Record<string, unknown>) => void,
  ): () => void {
    raw.on(event, handler)
    return () => raw.off(event, handler)
  }

  async function checkContract(): Promise<boolean> {
    try {
      verifyContractHash(await fetchRemoteContractHash())
      return true
    } catch (error) {
      const wrapped = error instanceof Error ? error : new Error(String(error))
      console.error('[socket] contract check failed', wrapped)
      options.onContractMismatch?.(wrapped)
      return false
    }
  }

  socket.on('connect', () => {
    void checkContract()
  })

  return {
    socket,
    emitEvent,
    on,
    checkContract,
    connect: () => socket.connect(),
    disconnect: () => socket.disconnect(),
  }
}
