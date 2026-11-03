# 每日挑战 v1

大厅“每日挑战”进入固定残局，使用原有对局界面。每个注册账号按北京时间自然日仅有一次机会，失败、投降、掉线超时都用掉机会；刷新只能继续尚未结束的原局。零点后旧关不可补打、不可补领奖励。

挑战固定大师 AI，无突变、无 Ban，不进匹配、排位、普通对局任务与普通成长结算，不允许观战。通关独立发放潮汐徽记 +30 和通行证 XP +40。数据库按账号+日期唯一认领，奖励和结果同事务。赛季空档的40XP保留为待兑付权益，下次查看通行证且已有活跃赛季时兑付一次。失败奖励为0。挑战结算页不提供“再来一局”。

## 运营配置

`DAILY_PUZZLES_PATH` 指向私有的 `daily_puzzles.json`；默认 `config/daily_puzzles.json` 是空目录，因此没有真实合格关卡时显示“今日暂无”。每周至多7条，文件原子替换后下次查询生效，不影响已注入的开局。每条包含 `puzzle_id`、`date`（YYYY-MM-DD）、`name`、相对于清单目录的 `snapshot` 文件路径、`sha256`、`reviewed:false` 和自动质量结果 `quality`。

完整快照与候选报告含隐藏船位、手牌、牌堆，仅放私有目录，**不要提交Git、不要放进frontend/dist或通过静态服务发布**。客户端不能上传快照或指定日期，只能查询今天的展示信息并通过现有 `create_ai_room` 事件的 `daily_challenge:true` 分支启动。

## 从真实败局产生候选

先在项目根目录设置 `PYTHONPATH=backend/src`，运行：

```powershell
python -m battleship.services.daily_candidates --db "D:/Codex workspace/battle-ship-local-play/.tmp/preview.db" --out "D:/Codex workspace/bridge/daily-challenge-v1-20261103/candidates" --week 2026-11-02 --verify
```

命令以SQLite只读URI打开源库，不迁移、不写回用户数据。仅选择注册玩家败给大师AI的普通无突变、无Ban对局，保留终局前最后5个可完整还原的真人行动点。双方都至少1舰、船差不超过2；链、选牌、重摆或无法还原的回调订阅尚未稳定时跳过。标记类效果租约包含在快照中，仍按原有阶段边界过期。

旧观看录像没有完整牌堆与引擎态时不会猜补。`daily_challenge_sources` 为本功能更新后新对局记录独立私有快照；关闭录像的对局不落库此来源。原有对局录像与存档不改变。

`--verify` 对每个候选执行：最多20个种子的策略搜索；找到胜利后按同种子、同动作轨迹再跑一次；再执行50局随机合法模拟。实际伤害、卡牌、重摆、胜负与AI均调用生产用例。随机基线在合法动作中随机挑选，牌目标/后续选择使用master合法解析器，含启发式，属于偏强基线。任何超时、无效动作或未结束的模拟均使本次质量审核失败，绝不算作败局压低胜率。随机通关率超过10%的候选不发布。

同一玩家同一源局每周最多选1个点；不足7关就留缺天。产物 `candidate-report.json` 含样本数、过滤理由、局面摘要、可解动作轨迹和随机结果，`daily_puzzles.json` 仅含通过自动门槛的候选，仍标记 `reviewed:false`，由用户人工微调、盲玩验收。

## 数据与验收

迁移 `0007_daily_challenge` 仅新增尝试表和来源表；原有比赛、录像与通行证流水不重建、不清空。更新试玩服务前使用原有迁移程序的在线备份与行数校验。测试资产统一位于仓外 `D:/develop/battleship-verify/cases/daily-challenge-v1`；隔离库的演示残局不是正式关卡来源。
