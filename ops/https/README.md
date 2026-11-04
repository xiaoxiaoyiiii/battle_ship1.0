# HTTPS 切换准备

本目录是待审阅方案，尚未安装代理、申请证书、改防火墙或切换生产服务。执行需用户当次部署授权。

## 已核对的部署边界

2026-11-04 的只读核对确认服务从独立 `/opt/battleship-releases/` 下运行，真库仍为 `/opt/battleship/data/battleship.db`。执行前重新读取 systemd 的实际 WorkingDirectory、ExecStart 和进程 cwd；不要拿 `ops/systemd/battleship.service` 的旧目录模板覆盖现网。HTTPS 不需要搬库、搬头像或改变 release 目录。

先确定可公开访问的正式域名与证书方案、域名解析、80/443 端口和已有代理的占用情况。示例选择 Caddy 自动管理证书与 HTTP 到 HTTPS 跳转；它的反向代理原生支持 WebSocket，无需把 Socket.IO 走另一条上游。依据：[自动 HTTPS](https://caddyserver.com/docs/automatic-https)、[反向代理](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)、[环境变量](https://caddyserver.com/docs/caddyfile/concepts#environment-variables)。

## 审阅与校验顺序

1. 将示例中的 `BATTLESHIP_DOMAIN` 设为实际域名；先使用 `caddy adapt --config <配置路径> --adapter caddyfile --validate` 核对配置，确认它代理 `127.0.0.1:5000`。本机没有 Caddy，本轮未声称已通过其官方验证器。
2. 在获准的切换窗口准备证书和代理，保持应用数据路径不动。应用 Uvicorn 的实际启动参数改为仅监听 `127.0.0.1:5000`，显式使用 `--proxy-headers --forwarded-allow-ips=127.0.0.1`；保留实际 runtime Python、release app-dir 和服务用户，不复制旧模板中的路径。
3. 将真实 `CORS_ORIGINS` 改为正式 HTTPS 来源；确认 Socket.IO 使用同一来源。不要把任意来源或所有代理加入信任列表。
4. 应用只从经过受信 Uvicorn 代理中间件处理后的请求 scheme 决定 Secure Cookie，不直接信任外部客户端提交的 X-Forwarded-Proto。现有 HTTP 测试入口不能单独强制 Secure，否则浏览器无法携带登录 Cookie。
5. 上游回环与代理验收通过后，撤下公网直连 5000 的入口；防火墙和云安全组分别现场核对。不要仅开 443 而遗留 HTTP 登录旁路。
6. 示例 HSTS 先设一天，验证域名 HTTPS 长期可用后再评估延长；此批不申请 preload，也不影响其它子域。

## 切换后的实际验收

- 普通 HTTP 页面跳转到同站 HTTPS；证书链和域名正确。
- 登录、注册、刷新、退出、改密可用；HTTPS Cookie 含 HttpOnly、SameSite=Lax、Secure。不要在终端打印 Cookie 值。
- Socket.IO polling 与 WebSocket 均可连通；公开房、有效私密邀请、人机和重连各验一次。
- 后端 `/health` 正常，前端哈希资源一致；浏览器没有混合内容；公网 5000 无法绕过 HTTPS。
- 上线会话迁移后旧版本 Cookie 需要重新登录；这不是账号数据丢失。数据库迁移与代码切换另按现有独立 release、停写、备份流程执行。

## 撤回边界

若代理配置或证书失败，先保留服务及数据，撤回这次代理/启动参数修改；不要使用会恢复历史数据库的回滚脚本处理 HTTPS。Cookie 的 Secure 标记由请求 scheme 决定，必须结合入口恢复一起验证。
