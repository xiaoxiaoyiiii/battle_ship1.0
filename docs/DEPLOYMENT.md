# 部署说明（DEPLOYMENT）

> 目标：让任何人（或 AI）接手时，**不会因为漏配环境变量把线上搞挂**。
> 本文档只记录**配置要求**，不含任何密钥值。

---

## 1. 线上环境

| 项 | 值 |
| --- | --- |
| 地址 | http://8.133.180.159:5000/ |
| 服务器 | 阿里云 ECS（Alibaba Cloud Linux） |
| 部署目录 | `/opt/battleship` |
| 启动方式 | systemd 服务 `battleship.service` |
| 运行命令 | `/opt/battleship/venv/bin/python /opt/battleship/run_prod.py` |
| 数据库 | `/opt/battleship/data/battleship.db`（SQLite，WAL） |
| 生产服务器 | eventlet（单进程协程） |

> ⚠️ `run_prod.py` **只存在于服务器，不在仓库里**（它含绝对路径，属部署专属文件）。

---

## 2. ⚠️ 必需的环境变量（最容易踩坑的地方）

**`server.py` / `api.py` 会读取以下环境变量。缺失时的默认值大多「仅适合本地开发」，直接上生产会出问题。**

| 变量 | 默认值 | 生产必须设置？ | 说明 |
| --- | --- | --- | --- |
| `CORS_ORIGINS` | `http://localhost:5000,http://127.0.0.1:5000` | ✅ **必须** | 逗号分隔的放行来源。**默认不含线上域名 → Socket.IO 连接被拒 → 所有操作卡十几秒**（见第 5 节事故记录） |
| `SECRET_KEY` | 每次启动随机生成 | ✅ **必须** | 固定值。不设置则**每次重启所有人登录态失效** |
| `ENABLE_TEST_EVENTS` | 关闭（非 `'1'` 即关） | 保持关闭 | 为 `'1'` 时启用 12 个 `test_*` 调试事件（可改船数/判胜负），**生产严禁开启** |
| `FLASK_DEBUG` | 关闭 | 保持关闭 | 为 `'1'` 时开 debug |
| `PORT` | `5000` | 按需 | 监听端口 |
| `TURN_TIMEOUT_SECONDS` | `90` | 按需 | 回合思考超时（秒）。超时只做一次**保底动作**、不判负：准备阶段→进战斗；战斗→随机开火一发；结束→交出回合。`0` = 关闭。人机房、连锁窗口、等待点选、有人掉线宽限期间都不会触发 |

### 正确的 systemd 配置

`/etc/systemd/system/battleship.service`：

```ini
[Unit]
Description=BattleShip game server
After=network.target

[Service]
WorkingDirectory=/opt/battleship
# CORS：必须放行线上地址，否则 Socket.IO 连接被拒（表现为操作卡十几秒）
Environment="CORS_ORIGINS=http://8.133.180.159:5000"
# SECRET_KEY：固定值，避免每次重启后所有登录态失效
Environment="SECRET_KEY=<在此填入固定随机串>"
# 调试事件默认关闭（生产安全）
Environment="ENABLE_TEST_EVENTS=0"
ExecStart=/opt/battleship/venv/bin/python /opt/battleship/run_prod.py
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
```

改完后必须：

```bash
systemctl daemon-reload
systemctl restart battleship
```

> 💡 新增多个域名时用逗号分隔，例如：
> `Environment="CORS_ORIGINS=http://8.133.180.159:5000,https://yourdomain.com"`

---

## 3. 代码更新流程

```bash
cd /opt/battleship
git fetch origin main
git reset --hard origin/main          # 用 reset 而非 pull，避免服务器本地改动干扰
systemctl restart battleship
curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/   # 应为 200
```

**部署前建议**：先在有 pytest 的环境跑 `python -m pytest tests/ -q`。

### 服务器上的 git 保护规则

`/opt/battleship/.git/info/exclude` 中已列出**不允许被 git 覆盖**的文件：

```
venv/          # 虚拟环境
data/          # 数据库
*.bak-*        # 历史备份
run_prod.py    # 部署专属启动脚本（不在仓库中）
CODE_WIKI.md   # 旧文档残留
```

> ⚠️ 这些用 `.git/info/exclude`（本地专属）而非仓库 `.gitignore`——后者会被 `git reset --hard` 覆盖失效。

---

## 4. 部署前检查清单

每次部署前逐项确认：

- [ ] `git fetch` 看过远端有无他人提交，**读完再动手**
- [ ] 本地测试全绿
- [ ] 若代码新增了 `os.environ.get('XXX')`，**同步更新服务器的 systemd `Environment=`**
- [ ] 数据库已备份（部署脚本会自动备份到 `/root/deploy-backups/`）
- [ ] 重启后做健康检查
- [ ] 查日志有无 `not an accepted origin` / `Traceback`

---

## 5. 事故记录：操作卡十几秒（2026-09-12）

**现象**：线上每个按钮都要等十几秒才响应；怀疑服务器内存耗尽。

**排查结果**：**不是内存问题**。内存 1.8G 用 1.0G（可用 843M）、CPU 负载 0.05，均正常。

**真因**：一次安全修复把 CORS 从全放行改成白名单：

```python
# 修复前
socketio = SocketIO(app, cors_allowed_origins="*")
# 修复后
socketio = SocketIO(app, cors_allowed_origins=os.environ.get('CORS_ORIGINS', 'http://localhost:5000,...'))
```

但**服务器上没有设置 `CORS_ORIGINS`**，默认值只含 localhost，线上地址不在白名单：

```
engineio.server - ERROR - http://8.133.180.159:5000 is not an accepted origin.
```

Socket.IO 连接被拒 → 前端退回 HTTP 长轮询反复重试 → 表现为「每个操作卡十几秒」。

**修复**：给 systemd 补上 `CORS_ORIGINS`（顺带固定 `SECRET_KEY`），`daemon-reload` + `restart`。

**验证**：`not an accepted origin` 错误归零；HTTP 响应从十几秒降到 **0.003 秒**。

**教训**：
> 代码改动如果**改变了配置需求**（新增/收紧环境变量），**部署时必须同步更新服务器配置**。
> 只拉代码重启是不够的 —— 服务能起来，但会带着错误的默认值运行。

---

## 6. 日常运维

```bash
systemctl status battleship              # 服务状态
journalctl -u battleship -n 50 --no-pager   # 最近日志
journalctl -u battleship -f              # 实时跟踪
free -h                                  # 内存
df -h /                                  # 磁盘
```

**备份位置**：`/root/deploy-backups/`（每次部署自动备份数据库，保留最近 10 份）
