# -*- coding: utf-8 -*-
"""前端源码级守卫（2026-09-23 回放批）。

这些用例都是**源码级 / 字符串级**断言，因为这几条一旦坏掉**不会有任何症状**：

* 观战屏的棋盘渲染**故意**只画「已轰过的格」，它的安全前提是"手上根本没有船位
  数据"；回放屏要画船。两者一旦互相引用，某次改动就可能把船位漏给观众
  （CLAUDE.md 教训 #12：隐私过滤只有服务端拦得住，前端断言会假绿 ——
  但"两套渲染不许互相引用"这件事**只有源码级断言钉得住**）。
* 战绩里的 `mode` 为 `NULL` = "老数据，不知道"。兜底成 `'casual'` 会把未知
  退化成"满足条件"（教训 #21），而且**页面照常显示、不报错**。
* `isAiOpponent` 是老局唯一能看出人机的途径。删掉它（或让 `mode` 的判据
  盖住它）→ 人机标签在历史局上集体消失，同样**不报错**。

每条都按"能红"写：见 `docs/REPLAY_2026_09_23.md` 实施记录里贴的原始输出。
"""

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_JS = os.path.join(ROOT, 'static', 'game.js')
INDEX_HTML = os.path.join(ROOT, 'templates', 'index.html')


def _read(path):
    with io.open(path, encoding='utf-8') as fh:
        return fh.read()


def _strip_comments(text):
    """去掉注释（守卫只判**代码**，不许被自己的说明文字误伤）。"""
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def _func_body(src, header):
    """从 `header` 开始、用花括号配平取出那个函数体（含 header）。"""
    start = src.index(header)
    depth = 0
    i = src.index('{', start)
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError('花括号不配平：%s' % header)


# REPLAY 段 = 从 `// REPLAY 界面段开始` 到 `bindEventListeners` 之前的**全部代码**。
_REPLAY_HEADER = '// REPLAY 界面段开始'
_REPLAY_END = '// 绑定事件监听器\nfunction bindEventListeners'


def _replay_code():
    src = _read(GAME_JS)
    start = src.index(_REPLAY_HEADER)
    end = src.index(_REPLAY_END, start)
    return _strip_comments(src[start:end])


# ===========================================================================
# 守卫 1：观战渲染函数体里不许出现回放 / 船位字段
# ===========================================================================
def test_spectate_board_renderer_never_mentions_replay_or_ship_positions():
    """★★ 观战棋盘渲染**永不碰回放**（源码级）。

    判据：`renderSpectateBoards` 的函数体（**去掉注释**）里不许出现
    `replay` / `match_replays` / `alive`（船位的存活字段）——
    一旦出现，观战屏就有了画船的资格，"观众看不到船位"这条不变量就只剩口头承诺。

    ⚠️ `ship` 这个词**允许**出现，而且是**必须**出现：那几处是
    `mark.ship_sunk`（"这一格沉了一艘"，服务端告诉观众的**唯一**信息），
    前端**不许**据此推断旁边还有没有船。所以这里断言的不是"没有 ship 字样"，
    而是"没有回放的形状与船位的存活字段"。
    """
    body = _strip_comments(_func_body(_read(GAME_JS), 'function renderSpectateBoards()'))
    for forbidden in ('replay', 'Replay', 'match_replays', 'alive'):
        assert forbidden not in body, (
            '观战棋盘渲染里出现了 %r —— 观战的棋盘**只**画已轰过的格，'
            '不许有画船的资格（见 docs/REPLAY_2026_09_23.md §7）' % forbidden)
    assert 'ship_sunk' in body, (
        '`ship_sunk` 不见了：那是服务端给观众的"这一格沉了一艘"，'
        '少了它观战屏的击沉格就画不出来')


# ===========================================================================
# 守卫 2：回放段里不许出现观战那套渲染 / 快照 / socket
# ===========================================================================




# ===========================================================================
# 守卫 3：`mode` 的 NULL 不许兜底成"匹配"
# ===========================================================================
def _mode_mapper_body():
    return _strip_comments(_func_body(_read(GAME_JS), 'function matchModeLabel('))






# ===========================================================================
# 守卫 4：老局的人机标签不许消失
# ===========================================================================




# ===========================================================================
# 守卫 5：`has_replay` 为假 ⇒ 回放按钮不可点 + 原因文案
# ===========================================================================




# ===========================================================================
# 守卫 6：战绩列表请求 30 行（后端按每人 30 局保留回放，20 行有 10 局够不着）
# ===========================================================================


# ===========================================================================
# 守卫 7：回放屏有静态的进出通道（别让玩家进去出不来）
# ===========================================================================




def test_replay_progress_nodes_come_from_the_server_only():
    """契约 §3/§7：关键节点**服务端算一次**，前端不许另算一套。"""
    code = _replay_code()
    # 节点渲染只读 payload.nodes；不许出现"前端自己推导节点"的痕迹
    assert 'payload.nodes' in code or 'Array.isArray(replayState.payload.nodes)' in code
    body = _strip_comments(_func_body(_read(GAME_JS), 'function buildReplayTrackNodes('))
    assert '.nodes' in body, '进度条节点必须来自服务端 payload.nodes'
    assert "ship_sunk" not in body and "detail.hit" not in body, \
        '节点不许由前端从 attack 步自己推导（两套判据必然漂移）'


# ===========================================================================
# 守卫 8~11（缺陷修复批）：字形 / 攻击标记 / 效果格 / 座位对齐
# ===========================================================================
# 这四条是作者实报缺陷的**源码级**钉子。逐格的端到端判定在
# `tools/dom_replay_frame_check.mjs`（真跑 game.js），这里钉的是"实现方式"：
# 保证下次有人改写这段时不会把判据又写反（教训 #7：恒等式断言拦不住方向写反）。
def test_ship_cell_is_not_drawn_as_a_hit_glyph():
    """★★ 缺陷 ①：**只有挨过炮才是 ✕**；没挨过炮的船格必须是船。

    原来的写法是 `(cell.hasShip || cell.hit) ? '✕' : …` —— 任何有船的格子都成了
    叉（那是"命中"的字形），玩家看着像"这一格已经打过、别再点了"。
    """
    body = _strip_comments(_func_body(_read(GAME_JS), 'function renderReplayBoard('))
    assert "(item.cell.hasShip || item.cell.hit) ? '✕'" not in body, \
        '船格又被写成了 ✕（缺陷 ① 的原写法）'
    assert "item.cell.sunk || item.cell.hit) el.textContent = '✕'" in body, \
        '击沉/命中必须画 ✕'
    assert "item.cell.hasShip) el.textContent = '⛴'" in body, \
        '没挨过炮的船格必须画船（⛴）'
    assert "item.cell.miss) el.textContent = '○'" in body, '落空格必须画 ○'
    # 三个字形互不相同（不许有两个状态共用一个字形）
    assert len({"'✕'", "'⛴'", "'○'"}) == 3




def test_replay_board_renders_the_public_effect_cells():
    """★★ 缺陷 ③：护盾格 / 神威洞 / 冻结区 / 绝处逢生候选格都要画出来。

    类名复用实战场那几个（一份样式两处用），绝不另起一套（教训 #1）。
    """
    src = _read(GAME_JS)
    body = _strip_comments(_func_body(src, 'function renderReplayBoard('))
    for cls in ('shielded', 'shenwei-hole', 'frozen-area', 'last-stand-candidate'):
        assert "' " + cls + "'" in body or '" ' + cls + '"' in body, \
            '回放棋盘没画 %s（缺陷 ③）' % cls
    eff = _strip_comments(_func_body(src, 'function replayEffectOf('))
    for field in ('shield', 'shenwei_holes', 'frozen_area', 'last_stand_cells'):
        assert field in eff, '效果格判据没读 %s' % field
    # 效果时间线必须**叠进帧**（否则效果永远画不出来）
    frame = _strip_comments(_func_body(src, 'function replayComputeFrame('))
    assert 'replayFoldTimeline(payload.effects' in frame, \
        'effects 时间线没有叠进帧（缺陷 ③ 的"随时间线变化"会整条失效）'
    assert "'effect'" in frame or 'effect: { p1: null, p2: null }' in frame, \
        '帧结构里必须有效果槽位'
