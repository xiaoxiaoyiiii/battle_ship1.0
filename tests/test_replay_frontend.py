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
def test_replay_section_never_mentions_spectate_rendering_or_socket():
    """★★ 回放段**永不碰观战**，也**不碰 socket**（源码级）。

    三条一起判：
      ① 不许出现观战的渲染/快照名字（`spectate` 家族）；
      ② 不许出现 `emit(`（回放数据里有双方船位，一旦 emit 进对局房间就是灾难级泄露）；
      ③ 不许出现 `socketio`。

    ⚠️ 判据是**去掉注释后**的代码：本段的说明注释里当然解释过"不许出现 spectate"，
      那是文档不是耦合 —— 如果连注释都不许提，这条守卫就会被自己的说明书误伤。
    """
    code = _replay_code()
    names = re.findall(r'[\w.]*spectate[\w.]*', code, re.I)
    assert names == [], '回放段里出现了观战那套的名字：%s' % names
    assert 'emit(' not in code, '回放段里出现了 emit( —— 回放绝不发任何 socket 事件'
    assert 'socketio' not in code, '回放段里出现了 socketio'


def test_replay_board_renderer_is_not_the_spectate_one():
    """★ 回放棋盘渲染是**新写的一份**，不是改观战那份。

    判据：`renderReplayBoard` 必须真的存在，且它**不**调用观战的渲染函数。
    这条与守卫 2 是两条腿：守卫 2 判"回放段里没有观战"，这条判"回放确实有自己
    的渲染函数"—— 否则有人可以把回放屏的棋盘改成观战那份（守卫 2 照样绿）。
    """
    src = _read(GAME_JS)
    assert 'function renderReplayBoard(' in src, '回放棋盘渲染函数不见了'
    body = _strip_comments(_func_body(src, 'function renderReplayBoard('))
    assert 'renderSpectateBoards' not in body
    assert 'applySpectateSnapshot' not in body
    # 自己的 DOM id，别蹭观战那两块
    html = _read(INDEX_HTML)
    assert 'id="replay-board-1"' in html and 'id="replay-board-2"' in html, \
        '回放屏的两块棋盘 id 必须存在（#replay-board-1/2）'


# ===========================================================================
# 守卫 3：`mode` 的 NULL 不许兜底成"匹配"
# ===========================================================================
def _mode_mapper_body():
    return _strip_comments(_func_body(_read(GAME_JS), 'function matchModeLabel('))


def test_match_mode_never_falls_back_to_casual():
    """★★ `mode` 为 NULL（老数据）时**不许兜底成"匹配"**（教训 #21）。

    判据（源码级）：`matchModeLabel` 的函数体里**一个 `'casual'` 字面量都不许
    出现在 `mode ===` 判据之外** —— 做法更直接：把每个分支拆开，要求
    `'casual'` 只与 `=== 'casual'` 同行出现。

    改坏的样子（必须让本用例变红）：把最后那行
    `if (isAiOpponent(...)) return {...ai...}` 前面加一句
    `return { key: 'casual', text: '匹配', ... }`（或写成 `mode || 'casual'`）。
    """
    body = _mode_mapper_body()
    casual_lines = [ln.strip() for ln in body.split('\n') if "'casual'" in ln]
    assert casual_lines, "matchModeLabel 里连 'casual' 都没有了 —— 匹配标签画不出来"
    for line in casual_lines:
        assert "=== 'casual'" in line or "== 'casual'" in line, (
            "`'casual'` 出现在非 `mode ===` 判据的位置上 —— 那正是"
            '"未知退化成匹配"的写法：%s' % line)
    # 未知必须**明确**走"人机猜测"或"空标签"这两条出口之一
    assert 'isAiOpponent(matchData, myId)' in body, (
        '未知模式必须退回 isAiOpponent 猜人机（老局唯一的途径）')


def test_unknown_mode_returns_empty_label_not_a_mode():
    """★ 未知模式返回**空标签**（不是"匹配"、也不是"自定义房"）。

    判据：`matchModeLabel` 的最后一条出口 `return { key: 'unknown', text: '' ... }`
    必须存在且 `text` 为空字符串。
    """
    body = _mode_mapper_body()
    m = re.search(r"return \{\s*key: 'unknown'[^}]*\}", body)
    assert m, "未知模式那条出口（key: 'unknown'）不见了"
    assert re.search(r"text: ''", m.group(0)), (
        "未知模式的 text 必须是空串：填充任何文案都等于给老局编了一个模式")
    # 渲染层：空文案必须**不占位**
    tag = _strip_comments(_func_body(_read(GAME_JS), 'function matchModeTagHTML('))
    assert 'if (!info.text) return' in tag, '空文案必须返回空串（不占位）'


# ===========================================================================
# 守卫 4：老局的人机标签不许消失
# ===========================================================================
def test_ai_label_still_shown_for_legacy_rows_without_mode():
    """★★ `mode` 为 null 且对手 id 是 `ai-*` 时**仍然**显示人机标签。

    这是"删了 isAiOpponent 就集体消失、而且不报错"那条教训的守卫。
    判据（源码级）：`matchModeLabel` 里
      ① `isAiOpponent` 仍然被调用；
      ② 它的返回值就是人机那一档（`key: 'ai'`、`text: '人机'`）。
    """
    body = _mode_mapper_body()
    assert re.search(r'isAiOpponent\(matchData,\s*myId\)', body), \
        'isAiOpponent 不再兜底 —— 老局（mode 为 NULL）的人机标签会集体消失'
    line = [ln for ln in body.split('\n') if 'isAiOpponent(' in ln and 'if (' in ln]
    assert line, 'isAiOpponent 不在判据里用'
    # 紧接着那一条 return 必须是"人机"
    idx = body.index(line[0])
    tail = body[idx:idx + 260]
    assert "key: 'ai'" in tail and "text: '人机'" in tail, (
        'isAiOpponent 命中后必须返回人机标签，实际上下文：%s' % tail[:120])


def test_is_ai_opponent_still_exists_and_still_used_by_mode_mapper():
    """★ `isAiOpponent` 本体还在（**不许删**），且口径只有一处。"""
    src = _read(GAME_JS)
    assert 'function isAiOpponent(' in src, (
        'isAiOpponent 被删了 —— 它是老局唯一能看出人机的途径（教训：不报错，'
        '只是人机标签在历史局上集体消失）')
    # 战绩列表与详情页都必须走**同一个** mode 标签出口（不许各写一套判据）
    for consumer, header in (
            ('战绩列表', 'function buildHistoryList('),
            ('对局详情页', 'function renderMatchDetailHTML(')):
        body = _strip_comments(_func_body(src, header))
        assert 'matchModeTagHTML(' in body, '%s 没走统一的 mode 标签出口' % consumer
        assert "hist-tag-dark" not in body, (
            '%s 里还留着旧的那份"人机"标签写法（两份判据必然漂移）' % consumer)


# ===========================================================================
# 守卫 5：`has_replay` 为假 ⇒ 回放按钮不可点 + 原因文案
# ===========================================================================
def test_replay_button_disabled_with_reason_when_has_replay_is_false():
    """★ `has_replay` 为假时按钮**置灰**，并且**写明原因**（教训 #32：不许静默）。

    生产库实测真有 0 步的对局（契约 §9）：那时 `has_replay=false`，
    按钮点了什么都不发生 = 玩家眼里的"坏了"。
    """
    body = _strip_comments(
        _func_body(_read(GAME_JS), 'function renderMatchDetailHTML('))
    assert 'matchData.has_replay === true' in body, \
        '按钮的可用性必须以 has_replay 为准'
    assert 'disabled' in body, 'has_replay 为假时必须置灰'
    assert '这局没有可回放的行动' in body, '置灰必须写明原因（不许静默）'
    # 点击侧：置灰的按钮点了真的什么都不做（而不是照样发请求）
    entry = _strip_comments(_func_body(_read(GAME_JS), 'function bindReplayEntryPoints('))
    assert 'btn.disabled === true' in entry, '置灰按钮的点击必须被拦掉'
    assert '.match-replay-btn' in entry, '入口必须用事件委托绑在 .match-replay-btn 上'


def test_replay_entry_is_bound_by_delegation_on_a_container_that_is_not_rebuilt():
    """★ 入口用**事件委托**绑在不被重建的容器上（逐行绑必漏）。

    对局详情的内容每次点开都会被 `innerHTML` 整段换掉 —— 绑在
    `#match-detail-content` 上会被换掉，绑行上更是必漏（大厅/排行榜踩过同一个坑）。
    """
    entry = _strip_comments(_func_body(_read(GAME_JS), 'function bindReplayEntryPoints('))
    assert 'matchDetailModal.addEventListener' in entry, \
        '必须委托在 #match-detail-modal（它不会被重建），不是 #match-detail-content'
    assert 'matchDetailContent.addEventListener' not in entry


# ===========================================================================
# 守卫 6：战绩列表请求 30 行（后端按每人 30 局保留回放，20 行有 10 局够不着）
# ===========================================================================
def test_stats_page_size_is_thirty():
    """契约 §1/§4：后端按"每人最近 30 局"保留回放 ⟹ 前端列表必须请求 30。"""
    src = _read(GAME_JS)
    m = re.search(r'const STATS_PAGE_SIZE = (\d+);', src)
    assert m, 'STATS_PAGE_SIZE 不见了'
    assert m.group(1) == '30', (
        'STATS_PAGE_SIZE 必须是 30（后端按每人 30 局保留回放），实际 %s' % m.group(1))


# ===========================================================================
# 守卫 7：回放屏有静态的进出通道（别让玩家进去出不来）
# ===========================================================================
def test_replay_screen_is_registered_and_has_an_exit():
    """★ 回放屏登记进 `allScreens()`，并且有退出路径。"""
    src = _read(GAME_JS)
    screens = _strip_comments(_func_body(src, 'function allScreens()'))
    assert 'replayScreen' in screens, \
        '回放屏没登记进 allScreens()：switchScreen 切走时它的 active 摘不掉'
    leave = _strip_comments(_func_body(src, 'function leaveReplayScreen('))
    assert 'switchScreen(' in leave, '退出回放必须走 switchScreen（否则玩家出不来）'
    assert 'resetReplayState(' in leave, '退出必须清理回放状态（定时器/节点/tooltip）'


def test_replay_timer_is_a_timeout_chain_not_an_interval():
    """契约 §7：**固定速度、无思考时间** —— 用 setTimeout 链，不用 setInterval。"""
    code = _replay_code()
    assert 'setInterval' not in code, \
        'setInterval 会累积漂移、暂停时也容易残留残留定时器 —— 契约要求 setTimeout 链'
    assert 'setTimeout(' in code and 'clearTimeout(' in code
    assert 'REPLAY_STEP_MS = 900' in code, '每步固定 900ms 是契约给的默认值'
    assert 'REPLAY_SPEEDS = [1, 2, 4]' in code, '倍速档位必须是 1× / 2× / 4×'


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


def test_attack_marks_are_not_gated_on_having_a_reset():
    """★★★ 缺陷 ②：攻击标记**不许**被"必须存在一个 ≤ i 的重置"挡住。

    原写法 `var after = false; … if (!after) continue;` 在 `board_resets` 为空的局里
    （**绝大多数局**）把每一炮都丢掉 ⇒ 一个"已轰过的格"都看不到，而且**不报错**。
    正确语义是"取该侧**最后一次**重置"（没有则 -1），只丢"最后重置之前"的那些炮。
    """
    body = _strip_comments(_func_body(_read(GAME_JS), 'function replayComputeFrame('))
    assert 'var after = false;' not in body, \
        '又出现了 `after` 那个把无重置局全丢掉的判据（缺陷 ② 的原写法）'
    assert 'lastReset' in body, '必须用"该侧最后一次重置"（lastReset）作为判据'
    assert "if (i <= lastReset[boardSide]) continue;" in body, \
        '判据必须是 `i <= lastReset[boardSide]`（重置之前才丢；用 ≤ 不是 <）'
    # "取最大"必须是显式比较（写成 min/首次命中都会让方向反过来）
    assert 'if (list[n] > lastReset[rside]) lastReset[rside] = list[n];' in body, \
        'lastReset 必须取**最大值**（该侧最后一次重置），不是第一次'


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


def test_replay_slot_index_and_seat_side_stay_aligned():
    """★★ 缺陷 ④ 的前端一侧：**槽位下标**与**座位代号**只能有一处映射。

    棋盘 / 名字 / 手牌 / 标题全部经 `replaySeatOf(i)` 取座位，索引数组（`names`）
    一律**按座位**取（`names[side]`），不许写成 `names[i]` —— 那就是"下标口径 vs
    座位口径"交叉（第 6 批"棋盘方向对调"同族）。
    """
    body = _strip_comments(_func_body(_read(GAME_JS), 'function renderReplayPlayers('))
    assert 'var side = replaySeatOf(i);' in body, '槽位 → 座位必须过 replaySeatOf'
    assert 'names[side]' in body, '显示名必须**按座位**取（names[side]）'
    assert 'names[i]' not in body, \
        'names[i]（下标口径）与 side（座位口径）交叉 ⇒ 名字与（你）会张冠李戴'
    assert 'replayState.youAre === side' in body, '（你）必须按座位代号判'
    # 映射只有一处实现
    src = _read(GAME_JS)
    assert src.count('function replaySeatOf(') == 1, 'replaySeatOf 必须只有一份实现'
