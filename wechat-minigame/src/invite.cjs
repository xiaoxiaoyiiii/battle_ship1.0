const ROOM_ID = /^[a-f0-9]{6}$/i
const ROOM_TOKEN = /^[A-Za-z0-9_-]{22,128}$/

function parseInvite(input) {
  let parts = input
  if (typeof input === 'string') {
    const text = input.trim()
    if (text.includes('=')) {
      parts = Object.create(null)
      for (const item of text.split('&')) {
        const pair = item.split('=')
        const key = pair[0]
        if (pair.length !== 2 || !['roomId', 'inviteToken'].includes(key) || key in parts) return null
        try {
          parts[key] = decodeURIComponent(pair[1])
        } catch {
          return null
        }
      }
    } else {
      const match = text.match(/^([a-f0-9]{6})(?:\.([A-Za-z0-9_-]+))?$/i)
      if (!match) return null
      parts = { roomId: match[1], inviteToken: match[2] }
    }
  }
  if (!parts || typeof parts.roomId !== 'string' || !ROOM_ID.test(parts.roomId)) return null
  const inviteToken = parts.inviteToken ?? ''
  if (inviteToken !== '' && (typeof inviteToken !== 'string' || !ROOM_TOKEN.test(inviteToken))) return null
  return { roomId: parts.roomId.toLowerCase(), inviteToken }
}

function createInviteCode(invite) {
  const parsed = parseInvite(invite)
  return parsed?.inviteToken ? parsed.roomId + '.' + parsed.inviteToken : parsed?.roomId || ''
}

function buildShare(invite) {
  const parsed = parseInvite(invite)
  if (!parsed?.inviteToken) return { title: '战舰棋 · 深海作战室' }
  return {
    title: '来战舰棋，和我打场海战',
    query: 'roomId=' + parsed.roomId + '&inviteToken=' + encodeURIComponent(parsed.inviteToken),
  }
}

module.exports = { parseInvite, createInviteCode, buildShare }
