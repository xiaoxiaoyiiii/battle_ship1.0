// 邀请链接纯逻辑回归（TDD：先跑这支脚本看它失败，再实现 inviteLink.ts）。
// 运行：node frontend/scripts/check-invite.mjs
import { buildInviteUrl, readInviteRoomId, inviteFeedback, inviteManualPrompt } from '../src/screens/lobby/inviteLink.ts'

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

console.log(`\nRESULT: ${failed ? `FAIL (${failed})` : 'PASS'}`)
process.exit(failed ? 1 : 0)
