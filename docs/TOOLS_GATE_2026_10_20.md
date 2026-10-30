# 无头门禁重标定（票 #29，仓外运行）

> 本票只把 **CLAUDE.md 列为门禁**的那批无头工具从 DOM id 改为 `data-testid`，
> 并把截图基线统一为指纹 + 容差（D33）。工具、夹具、截图基线全部在仓外（D4）。

## 位置

* 工具：`D:/develop/battleship-verify/tools/web/`（22 个入口，含 `run_all.py`）
* 交付说明：`D:/develop/battleship-verify/cases/29-tools/README.md`
* 截图基线：`tools/web/baselines/manifest.json`（14 项）
* C+ 旧/新对照：`cases/29-tools/cplus-diff/REPORT.md`

## 运行

```powershell
cd D:/develop/battleship-verify
$env:PYTHONIOENCODING = 'utf-8'
& .venv/Scripts/python.exe tools/web/run_all.py `
    --worktree D:/develop/battleship-worktrees/integration
```

默认对 `integration` 跑（D7）；实现期用 `--worktree <impl worktree>`。
退出码 0 = 无失败；有失败返回 1；SKIP 在汇总里单独列出（不代表通过）。

## 口径

* 选择器只认 `data-testid`；旧 DOM id 不再是契约。
* 端口 5420 段（避开 5000/5060/5061），CDP profile 在
  `cases/29-tools/.profiles` 且每轮清理。
* 截图用 160×112 灰度指纹：平均差 ≤1 且 >10/255 通道占比 ≤0.2% 通过。
* 未迁移的屏/控件（help、sfx、bgm、仁王选择、壁纸应用、room/collection）
  以 SKIP + 归因出现，不伪装成绿色；C+ 视觉差异逐屏写在交付说明里。
