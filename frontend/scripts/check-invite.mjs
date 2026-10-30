// 邀请链接纯逻辑回归（TDD：先跑这支脚本看它失败，再实现 inviteLink.ts）。
// 运行：node frontend/scripts/check-invite.mjs
import {
  buildInviteUrl,
  readInviteRoomId,
  inviteFeedback,
  inviteManualPrompt,
  classifyJoinAck,
  inviteJoinStep,
  commitInviteJoin,
} from '../src/screens/lobby/inviteLink.ts'

let failed = 0
function check(ok, name, detail = '') {
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? ' — ' + detail : ''}`)
  if (!ok) failed += 1
}

const url = buildInviteUrl('https://play.example.com', '/lobby', 'R7x9Qa')
check(url === 'https://play.example.com/lobby?room=R7x9Qa', '生成 origin + 房间参数', url)
check(!/token|password|passwd|user|uid|name=/i.test(url), 'URL 不含敏感字段', url)
check(buildInviteUrl('https://play.example.com/', '/lobby', 'ABC') === 'https://play.example.com/lobby?room=ABC', 'origin 末尾斜杠不重复')
check(buildInviteUrl('https://play.example.com', '/', 'ABC') === 'https://play.example.com/?room=ABC', '根路径也可用')
check(buildInviteUrl('https://play.example.com', '/lobby', ' A B ') === 'https://play.example.com/lobby?room=A%20B', '房间号做 URL 编码')

check(readInviteRoomId({ room: '  abC_9 ' }) === 'abC_9', '读取并裁剪房间号')
check(readInviteRoomId({ room: ['R1', 'R2'] }) === 'R1', '数组取第一个')
check(readInviteRoomId({ room: 'a b' }) === '', '含空格视为无效')
check(readInviteRoomId({ room: 'x'.repeat(40) }) === '', '超长视为无效')
check(readInviteRoomId({}) === '' && readInviteRoomId(undefined) === '', '缺省安全返回空串')

const okText = inviteFeedback(true)
const failText = inviteFeedback(false)
check(okText.length > 0 && failText.length > 0 && okText !== failText, '复制反馈文案成对且不同', `${okText} | ${failText}`)
check(typeof inviteManualPrompt('https://x/lobby?room=1') === 'string' && inviteManualPrompt('https://x/lobby?room=1').includes('https://x/lobby?room=1'), '手动复制回退提示包含链接')

// ── 加入失败不写「已加入」标记：失败后可重试（复核问题回归） ─────────────────
const successAck = classifyJoinAck({ status: 'success' })
check(successAck.ok === true, 'ack=success 归类为成功')

for (const message of ['房间不存在', '房间已满', '对局已经开始', '你没有加入这间房的权限']) {
  const result = classifyJoinAck({ status: 'error', message })
  check(result.ok === false && result.message === message, '失败保留服务端文案：' + message)
}
const missingAck = classifyJoinAck(undefined)
check(missingAck.ok === false && missingAck.message.length > 0, '没有 ack 时也判失败并给兜底文案')
const blankAck = classifyJoinAck({ status: 'error' })
check(blankAck.ok === false && blankAck.message.length > 0, '服务端没给文案时用兜底文案')

// 用普通对象模拟 sessionStorage，验证「只有成功才写标记」这条生产逻辑。
function makeStore() {
  const data = new Map()
  return {
    data,
    mark: (roomId) => data.set('battleship.lobby.inviteJoined.' + roomId, '1'),
    has: (roomId) => data.get('battleship.lobby.inviteJoined.' + roomId) === '1',
  }
}

const failedStore = makeStore()
commitInviteJoin(classifyJoinAck({ status: 'error', message: '房间不存在' }), 'ROOM_A', failedStore.mark)
check(failedStore.data.size === 0 && !failedStore.has('ROOM_A'), '失败（房间不存在）不写已加入标记')

for (const message of ['房间已满', '对局已经开始', '你没有加入这间房的权限']) {
  const store = makeStore()
  commitInviteJoin(classifyJoinAck({ status: 'error', message }), 'ROOM_B', store.mark)
  check(!store.has('ROOM_B'), '失败（' + message + '）不写已加入标记')
}

const netErrStore = makeStore()
commitInviteJoin(classifyJoinAck(null), 'ROOM_C', netErrStore.mark)
check(!netErrStore.has('ROOM_C'), '网络异常/无 ack 不写已加入标记')

const afterFailure = inviteJoinStep({ roomId: 'ROOM_A', attempted: false, alreadyJoined: failedStore.has('ROOM_A') })
check(afterFailure === 'join', '失败后刷新可以再次尝试加入', afterFailure)

const successStore = makeStore()
const successResult = commitInviteJoin(classifyJoinAck({ status: 'success' }), 'ROOM_D', successStore.mark)
check(successResult.ok === true && successStore.has('ROOM_D'), '成功才写已加入标记')
const afterSuccess = inviteJoinStep({ roomId: 'ROOM_D', attempted: false, alreadyJoined: successStore.has('ROOM_D') })
check(afterSuccess === 'skip-joined', '成功后同一标签页不再重复加入', afterSuccess)

check(inviteJoinStep({ roomId: '', attempted: false, alreadyJoined: false }) === 'skip-no-room', '没有房号时不动作')
check(inviteJoinStep({ roomId: 'R', attempted: true, alreadyJoined: false }) === 'skip-attempted', '本次已尝试过时不重复发 join_room')

console.log(`\nRESULT: ${failed ? `FAIL (${failed})` : 'PASS'}`)
process.exit(failed ? 1 : 0)
