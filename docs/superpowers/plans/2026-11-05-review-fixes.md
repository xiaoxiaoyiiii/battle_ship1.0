# 审验问题修复计划

> 执行方式：在当前会话逐项实现并验证，最后进行一次独立代码审查。

**目标：** 修复 cfa60b9 审验报告的五项功能问题与三项约定问题。

**实现：** 连接异常明确拒绝握手；客户端登录沿用现有邮件幂等编号补投；推广提示保留等待状态；下载入口识别未支持系统；桌面壳仅给官方页面开放 HTTP(S) 外链。共用日期函数，翻译本次新增说明，版本判断测试移至仓外。

**技术：** Python、Socket.IO、Vue 3、TypeScript、Tauri 2、Rust。

**规格：** `D:/Codex workspace/战舰棋只读审验报告-20261105-cfa60b9.md`。

## 全局约束

- 沿用 `codex/post-launch-maintenance-20261104`，按用户本轮授权提交并推送 `origin/codex/tidebound`。
- 不合并、不部署、不操作生产及试玩数据，不重发内测奖励。
- 所有测试与证据位于 `D:/develop/battleship-verify/cases/review-fixes-20261105/`。
- 回复、说明、注释、提交和公告使用简体中文。
- 前端构建与依赖同一 dist 的隔离 HTTP 验证串行。

## 审查重点

- 鉴权仓储暂时失效时必须拒绝连接，正常游客仍保留来源 IP。
- 奖励恢复补投不得重复送信、重复入账，也不得重发已领取邮件。
- 弹窗等待期间不发请求，空位后仅显示一次，关闭后不再重新触发。
- iOS、macOS、Linux 不应被默认为 Windows；Android 和 Windows 仍正常下载。
- 外链权限仅限主窗口和官方、本地调试来源，不允许文件、路径或任意网站调用。

### Task 1: 修复审验问题并交付

**修改文件：** `backend/src/battleship/realtime/server.py`、`services/client_promo.py`、隐私相关新增英文说明所在文件；`frontend/src/components/ClientPromoPrompt.vue`、`ClientDownloadLink.vue`、`support/clientPromo.ts`；`desktop/src-tauri/src/lib.rs`、新增 `version.rs` 和 `capabilities/main.json`；玩家公告。

**接口：** `record_client_login(user_id, ua, now=...) -> bool` 保持首次记录语义；邮件沿用 `admin:system:client-voyage-v1:{uid}` 幂等编号。既有 Socket 事件、下载路径、日期键与版本比较行为不变。

- [ ] 编写仓外回归：鉴权异常拒绝；奖励失败恢复补投；占位弹窗后显示；未支持系统无默认下载；实际 Tauri 权限解析放行官方 HTTP(S) 外链。
- [ ] 在旧实现运行并确认这些断言因已发现的缺陷失败，记录失败输出。
- [ ] 实现上述最小修复；日期共用、注释翻译及 Rust 测试迁出一起完成。
- [ ] 新回归全部通过；前端类型检查和构建通过；版本判断仓外四项通过；桌面壳离线构建通过；原九组 144 项回归通过。
- [ ] 独立审查本轮差异，处理重要发现，核对 UTF-8、公告、秘密与工作树范围。
- [ ] 提交中文说明并显式推送 `HEAD:refs/heads/codex/tidebound`，核对远端提交一致。

**自查：** 八项问题均有对应修改。后端与前端互不新增协议；桌面外链配置只服务现有 opener。无新依赖、无迁移、无补发生产脚本。
