const { build } = require('esbuild')
const { copyFile, mkdir, stat, writeFile } = require('node:fs/promises')
const path = require('node:path')

async function main() {
  const raw = process.env.BATTLESHIP_MINIGAME_ORIGIN || 'http://127.0.0.1:5489'
  const url = new URL(raw)
  const local = /^127(?:\.\d{1,3}){3}$/.test(url.hostname) || url.hostname === 'localhost' ||
    /^(?:192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}$/.test(url.hostname) ||
    /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(url.hostname)
  if (url.pathname !== '/' || url.search || url.hash || url.username || url.password ||
      (url.protocol !== 'https:' && !(local && url.protocol === 'http:'))) {
    throw new Error('填写仅包含协议和域名的服务器地址。公网使用 HTTPS，本地调试可用 HTTP。')
  }
  const appid = process.env.BATTLESHIP_MINIGAME_APPID || 'touristappid'
  if (appid !== 'touristappid' && !/^wx[a-f0-9]{16}$/i.test(appid)) throw new Error('小游戏 AppID 格式不正确。')
  const output = path.join(__dirname, 'dist')
  await mkdir(output, { recursive: true })
  await build({
    entryPoints: [path.join(__dirname, 'src/game.cjs')],
    outfile: path.join(output, 'game.js'),
    bundle: true,
    platform: 'browser',
    format: 'iife',
    target: 'es2020',
    minify: true,
    legalComments: 'external',
    // Engine.IO 在无 window 的小游戏环境使用 self 获取计时器。
    banner: { js: 'var self = globalThis;' },
    define: { __BATTLESHIP_ORIGIN__: JSON.stringify(url.origin) },
  })
  await copyFile(path.join(__dirname, 'game.json'), path.join(output, 'game.json'))
  await writeFile(path.join(output, 'project.config.json'), JSON.stringify({
    appid,
    compileType: 'game',
    libVersion: '3.5.0',
    projectname: '战舰棋',
    setting: { urlCheck: url.protocol === 'https:', es6: true, minified: true },
  }, null, 2) + '\n', 'utf8')
  const bytes = (await stat(path.join(output, 'game.js'))).size
  console.log('小游戏构建完成，game.js ' + Math.ceil(bytes / 1024) + ' KiB')
  console.log(output)
}

main().catch(error => {
  console.error(error.message)
  process.exitCode = 1
})
