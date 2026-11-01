import type { ChatMessage, QuickChatMessage } from '../../stores/match'

export interface ChatTimelineEntry {
  key: string
  name: string
  text: string
  mine: boolean
}

/**
 * One conversation, oldest first. Free-text and quick phrases stay in their
 * own stores; this only merges them for the in-game chat panel.
 * Same-second lines keep arrival order (`order`).
 */
export function mergeChatTimeline(
  chat: readonly ChatMessage[],
  quickChat: readonly QuickChatMessage[],
  selfName: string,
  selfPlayerId: string,
): ChatTimelineEntry[] {
  const lines = [
    ...chat.map((message) => ({
      key: 'chat-' + String(message.order),
      name: message.username,
      text: message.message,
      ts: message.ts,
      order: message.order,
      mine: message.username === selfName,
    })),
    ...quickChat.map((message) => ({
      key: 'quick-' + String(message.order),
      name: message.name,
      text: message.text,
      ts: message.ts,
      order: message.order,
      mine:
        message.name === selfName || (selfPlayerId !== '' && message.playerId === selfPlayerId),
    })),
  ]
  lines.sort((left, right) => left.ts - right.ts || left.order - right.order)
  return lines.map(({ key, name, text, mine }) => ({ key, name, text, mine }))
}
