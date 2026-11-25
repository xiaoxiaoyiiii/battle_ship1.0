# 战舰棋微信小游戏

首版使用原生 Canvas 和 Socket.IO，和网页版共用服务端规则。打开后可创建私密好友房，分享小游戏卡片或复制邀请码。玩家入房后各布置六艘战舰，猜拳决定先手，再进行攻防、魔法响应和结算。掉线时按原房间、原座位恢复。

试玩版接入了「火力全开」「八方来财」「五险一金」和连锁响应「失灵！」。其他牌可查看效果。需要选目标的牌、指挥官技能、神秘科技、观战和抽卡需要对应的微信界面。用户名是在当前设备上保存的游客代号。

## 生成微信开发者工具工程

在本目录运行：

```powershell
npm ci
npm run build
```

默认产物 `dist` 连接 `http://127.0.0.1:5489`。在微信开发者工具中导入 `dist`，项目类型选小游戏。本机调试使用独立后端和数据库。可以在仓库根目录用以下命令启动后端，其中 `$dist` 指向已构建的网页前端目录。

```powershell
$env:SECRET_KEY = [Guid]::NewGuid().ToString('N')
$env:CORS_ORIGINS = 'http://127.0.0.1:5489'
$env:ENABLE_TEST_EVENTS = '0'
$db = Join-Path $env:TEMP ('battleship-wx-' + [Guid]::NewGuid().ToString('N') + '.db')
python -B ops/run_stack.py --host 127.0.0.1 --port 5489 --db $db --frontend-dist $dist
```

## 真机测试

登录微信开发者工具，使用本人的小游戏测试号 AppID，并为两台测试手机配置可访问的同一台测试服务。正式域名使用 HTTPS，部署反向代理时需要转发 `/socket.io/` 的 WebSocket 升级请求，并在微信后台配置合法域名。手机上的 `127.0.0.1` 指手机自身。局域网调试使用局域网测试服务，并在微信真机调试中核实域名及端口访问。

```powershell
$env:BATTLESHIP_MINIGAME_APPID = '<小游戏测试号 AppID>'
$env:BATTLESHIP_MINIGAME_ORIGIN = 'https://<测试域名>'
npm run build
```

重新导入或刷新 `dist` 后，在微信开发者工具点击预览并扫码。用两部手机验证好友邀请、六舰布阵、猜拳、开炮、切后台重进和结算。公开版本按联机小游戏配置实名防沉迷、隐私说明、资质与备案，再提交发布审核。

[微信小游戏测试号说明](https://developers.weixin.qq.com/minigame/dev/devtools/sandbox.html) · [微信网络配置](https://developers.weixin.qq.com/minigame/dev/guide/base-ability/network.html) · [微信小游戏备案](https://developers.weixin.qq.com/minigame/introduction/guide/nrjs.html)
