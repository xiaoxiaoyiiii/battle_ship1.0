# Phase 7：SQLite 仓储边界与基础设施评估

对应 `docs/superpowers/specs/2026-10-12-battleship-refactor-design.md` 的 Phase 7。本阶段没有改数据库表结构。

## 已实施

- `server.py`、`api.py` 共用 `infrastructure.persistence.repository`。仓储只允许已登记的操作；直接连接和游标不可从这两个入口取得。此前三个直接 SQL 查询迁入 `db.py`，保持原有参数化查询和返回形状。
- `Database(db_path=...)` 支持显式副本路径，不依赖模块级数据库路径，供隔离测试和迁移副本演练。
- `tools/db_maintenance.py` 提供完整性检查、SQLite backup API 一致性备份、在备份副本运行当前建表/加列逻辑。备份目标必须是新路径，避免覆盖已有备份。
- 测试覆盖 HTTP/Socket 层仓储操作白名单、替换 backend、三个查询、WAL 下的已提交记录备份和副本迁移对原库的隔离。

## 连接、事务、迁移和扩展评估

| 项目 | 当前事实 | 后续条件 |
| --- | --- | --- |
| 连接 | 每进程一个 `sqlite3` 连接，`check_same_thread=False`，DAO 用 `RLock`；WAL 和 5000 ms busy timeout 已启用。 | 并发量上升前先测写入等待、锁竞争和备份耗时；目前没有连接池。 |
| 事务 | `record_match` 将对局、回放和统计放在同一连接事务里提交；大量其他 DAO 方法各自提交。 | 跨多个仓储操作的业务流程需要显式工作单元，不能靠调用方拼接“看似原子”的序列。 |
| 迁移 | 启动时的 `_migrate_schema` 用 `PRAGMA table_info` 幂等加列；失败只记日志，没有版本表或自动向下迁移。 | 下一次实际 schema 变更前，先引入版本化迁移与失败即停的预检，再在副本上验证升级和回退。 |
| 横向扩展 | SQLite 文件和内存中的房间、匹配状态均绑定本机进程。 | 多实例需要共享数据库、会话/房间状态及 Socket 广播通道；仅换数据库不足以横向扩展。 |

## 验证与回滚

- 最终全量回归：1057 passed，1 warning；新增边界测试定向运行 7 passed。
- 在临时目录创建独立数据库后，实际运行 `check`、`backup`、`validate-copy` 三个 CLI 动作，均退出码 0；备份与副本完整性为 `ok`。演练未读取或修改用户的生产数据库。
- 本阶段无 schema 变更，代码回退为回退本阶段提交。未来有 schema 变更时，先暂停写入，使用 backup API 保存已命名快照，验证副本迁移；上线失败后停进程、从快照恢复数据库，再启动旧版本。不得在运行中的 WAL 数据库上直接复制主 `.db` 文件当作备份。
- 还没有做生产库迁移或多实例部署；当前单连接 SQLite 架构的扩展限制是评估结论，不是已解决项。
