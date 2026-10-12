// Phase 8：从 game.js 原样迁出；作为经典脚本共享页面作用域。
// 加入房间
// 设置Socket监听器
function setupSocketListeners() {
    const socket = gameState.socket;

    socket.on('connect', () => {
        console.log('Connected to server');
        // 重连后服务端的猜拳状态可能已经推进（对家出完、甚至已经判定完），
        // 本地那个「已出拳」锁定只会变成一副点不动的死锁 —— 收干净，等 room_sync / rps_result 说话。
        if (typeof resetRPSChoiceLock === 'function') resetRPSChoiceLock();
    });

    // 断线同样不能把「已出拳」留在页面上：连接断了，ack 永远不会回来，
    // 不收的话回来时会发现三个手势全点不动（而且没有任何提示）。
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        if (typeof resetRPSChoiceLock === 'function') resetRPSChoiceLock();
    });

    // 匹配相关事件处理
    socket.on('match_queued', (response) => {
        console.log('已加入匹配队列:', response);
        // ⚠️ 排位与休闲**共用这一个事件**，靠 payload 里的 `mode` 区分：
        //    排位时不能再显示「正在寻找匹配...」（那会让玩家以为点的是休闲），
        //    两条状态互斥，进一个就清另一个。
        const isRanked = !!(response && response.mode === 'ranked');
        if (isRanked) {
            rankedQueuePending = true;
            if (matchStatus) matchStatus.classList.add('hidden');
            if (findMatchBtn) findMatchBtn.classList.remove('hidden');
            if (rankedStatus) rankedStatus.classList.remove('hidden');
            if (cancelRankedBtn) cancelRankedBtn.classList.remove('hidden');
            if (rankedMatchBtn) rankedMatchBtn.classList.add('hidden');
        } else {
            matchStatus.classList.remove('hidden');
            resetRankedQueueUI();
        }
        // 大厅按钮同步（服务端没有 lobby_joined/lobby_left 这类事件）
        if (joinLobbyBtn) joinLobbyBtn.classList.add('hidden');
        if (lobbyRankedBtn) lobbyRankedBtn.classList.add('hidden');
        if (leaveLobbyBtn) leaveLobbyBtn.classList.remove('hidden');
    });

    socket.on('match_canceled', (response) => {
        console.log('匹配已取消:', response);
        matchStatus.classList.add('hidden');
        resetRankedQueueUI();          // 排位那套也要复位（否则按钮永远回不来）
        if (joinLobbyBtn) joinLobbyBtn.classList.remove('hidden');
        if (leaveLobbyBtn) leaveLobbyBtn.classList.add('hidden');
        if (lobbyRankedBtn) lobbyRankedBtn.classList.remove('hidden');
    });

    // ---- 大厅（2026-09-18 大厅批，契约见 docs/LOBBY_2026_09_18.md §1.2）----
    // lobby_hello 只发给刚订阅的那个连接，带的是**我自己的身份键**。
    // lobby_state 是一条广播（服务端不可能逐人改 is_me），所以"我"由前端比对。
    socket.on('lobby_hello', (data) => {
        gameState.lobbyKey = (data && data.key) ? String(data.key) : null;
        gameState.lobbySubscribed = true;
        if (gameState.lobbyState) renderLobbyState(gameState.lobbyState);
    });
    socket.on('lobby_state', (state) => {
        renderLobbyState(state);
    });
    socket.on('lobby_chat_history', (data) => {
        // ⚠️ 用合并（只补缺的）而不是"清空重铺"：实时消息可能已经先到了
        applyLobbyChatHistory((data && data.messages) || []);
    });
    socket.on('lobby_chat', (item) => {
        appendLobbyChat(item);
    });

    socket.on('game_state', (data) => {
        console.log('Game state received:', data);
        // 这一局是不是排位（段位批）：服务端在 `game_state` 里带 `ranked` / `mode`，
        // 重连快照也带（否则重连之后不知道自己在打排位）。前端只用它做展示判断，
        // 加减分的门槛完全在服务端。
        gameState.ranked = !!data.ranked;
        gameState.mode = String(data.mode || (data.ranked ? 'ranked' : 'casual'));
        // 隐藏所有屏幕和信息面板
        customRoomInfo.classList.add('hidden');
        customRoomIdInput.classList.add('hidden');
        // 新一局开始：清掉上一局记下的回放 id（否则上一局的入口会挂到这一局的结算屏上）。
        // 只清"要开始新对局"的那些状态分支，见下面 `placing_ships` 那段。

        // 屏清单一律走 hideAllScreens()（唯一来源）。这里原先是手抄的，漏了
        // lobbyScreen / leaderboardScreen —— 在大厅点人机对战会两个屏同时 active。
        hideAllScreens();

        // 保存玩家名称和对手名称（支持多种字段名）
        const playerNameFromData = data.player_name || data.playerName || data.player || null;
        if (playerNameFromData) {
            gameState.playerName = playerNameFromData;
            if (myUsernameInfo) myUsernameInfo.textContent = playerNameFromData;
        }

        const oppNameFromData = data.opponent_name || data.opponentName || data.opponent || null;
        if (oppNameFromData) {
            gameState.opponentName = oppNameFromData;
            if (opponentUsernameInfo) {
                opponentUsernameInfo.textContent = oppNameFromData;
                showOpponentStatsBtn && (showOpponentStatsBtn.style.display = 'inline-block');
            }
            updateMyAvatarInGame();
            updateOpponentAvatarInGame(oppNameFromData);
        } else {
            // 如果没有从当前数据里获得对手名，尝试从 gameState 中恢复（有可能之前已设置）
            if (gameState.opponentName) {
                if (opponentUsernameInfo) opponentUsernameInfo.textContent = gameState.opponentName;
                showOpponentStatsBtn && (showOpponentStatsBtn.style.display = 'inline-block');
            } else {
                if (opponentUsernameInfo) opponentUsernameInfo.textContent = '';
                showOpponentStatsBtn && (showOpponentStatsBtn.style.display = 'none');
            }
        }

        // 设置玩家ID
        if (data.player_id) {
            gameState.playerId = data.player_id;
            console.log('设置playerId为:', gameState.playerId);
        }
        if (data.player_seat === 'p1' || data.player_seat === 'p2') {
            gameState.playerSeat = data.player_seat;
        }

        /* 好友房：对手进房那一刻席位要变（服务端在 `len(room.players)==2` 时逐人 emit
           `game_state`，里面带 `opponent_name`）。挂在既有链路的收尾位上，
           不新开监听；房间信息没显示时它自己会跳过。 */
        if (typeof refreshCustomRoomInfo === 'function') refreshCustomRoomInfo();

        // 掉线重连准备：记录对局上下文并按需领取重连 token
        if (data.room_id && data.player_id) {
            gameState.inRoom = true;
            saveActiveGame(data.room_id, data.player_id);
            if (!gameState.reconnectToken) requestReconnectToken(data.room_id, data.player_id);
        }

        // 显示对手战绩弹窗并请求数据
        // 2026-09-17：改为走统一的个人信息面板（头像 / 个性签名 / 排行榜名次 /
        // 胜率 / 历史战绩 + 对局详情），而不是原来那 5 行裸表格。
        function showOpponentStats() {
            if (!gameState.opponentName) return;
            if (typeof window.showUserProfile === 'function') {
                window.showUserProfile(gameState.opponentName);
            }
        }

        // 将 showOpponentStats 暴露为全局，供 bindEventListeners 引用（修复作用域崩溃）
        window.showOpponentStats = showOpponentStats;

        switch (data.state) {
            case 'waiting':
                // 只有当游戏是从自定义房间创建或加入时，才显示自定义房间游戏界面
                // 匹配游戏不应该显示这个界面
                // 显示导航栏
                if (gameNav) gameNav.style.display = 'block';
                break;
            case 'placing_ships':
                console.log('Switching to ship placement screen');
                clearGameLogs();   // 新一局：日志从零开始

                // 设置playerId（使用socket.id）
                if (gameState.socket && !gameState.playerId) {
                    gameState.playerId = gameState.socket.id;
                    console.log('设置playerId为:', gameState.playerId);
                }

                // 隐藏导航栏
                if (gameNav) gameNav.style.display = 'none';

                // 显示匹配成功界面
                matchSuccessScreen.classList.add('active');

                // 显示对手信息
                opponentInfo.textContent = gameState.opponentName;
                // 顺手把对手的称号 / 标签 / 等级 / 段位显示出来（异步取公开的 /user_stats，
                // 与名片同一份数据源；取不到就留空，绝不影响开局倒计时）
                showOpponentChips(gameState.opponentName);
                // 自己的段位（页面加载时已经取过一次并缓存，这里不新拉接口）
                showMyRankChip();

                // 开始5秒倒计时
                let countdown = 5;
                countdownTimer.textContent = countdown;

                // 初始进度为100%
                const countdownFill = countdownBar.querySelector('.countdown-fill');
                countdownFill.style.width = '100%';

                // 每秒更新一次，确保数字和进度条完全同步
                const countdownInterval = setInterval(() => {
                    countdown--;
                    countdownTimer.textContent = countdown;

                    // 直接设置进度条宽度，与当前倒计时数字完全对应
                    const progress = (countdown / 5) * 100;
                    countdownFill.style.width = `${progress}%`;

                    // 倒计时结束，进入战舰放置界面
                    if (countdown <= 0) {
                        clearInterval(countdownInterval);

                        // 直接进入放置战舰界面
                        matchSuccessScreen.classList.remove('active');
                        shipPlacementScreen.classList.add('active');
                        // ⚠️ 这里是**直接加 active**、没走 switchScreen（屏走 active，
                        //    只有面板类容器用 hidden）——所以「用时」的起点必须在这里也打一次，
                        //    否则正常开局（匹配成功 → 5 秒倒计时）这条路径永远量不到用时。
                        markMatchStart();
                        initBoard(playerBoard, true);
                        // 确保界面正确切换。屏走 active，只有面板类容器用 hidden。
                        startScreen.classList.remove('active');
                        customRoomScreen.classList.remove('active');
                        matchStatus.classList.add('hidden');
                        // 保存房间ID
                        if (data.room_id) {
                            gameState.roomId = data.room_id;
                        }
                    }
                }, 1000);
                break;
            case 'rock_paper_scissors':
                // 隐藏导航栏
                if (gameNav) gameNav.style.display = 'none';
                rpsScreen.classList.add('active');
                rpsRound.textContent = data.round || 1;
                // 新一回合的猜拳：把上一轮的锁定 / 选中 / 平局提示一并收干净。
                // 服务端在平局后会重新广播这个 state，只清 rpsResult 的话，
                // `is-tie` 和三个按钮的 `.picked` 会带着上一轮的残留状态进新回合。
                if (typeof resetRPSChoiceLock === 'function') resetRPSChoiceLock();
                else rpsResult.classList.add('hidden');
                break;
            // 在setupSocketListeners的game_state事件处理中添加
            case 'attacking':
                // 隐藏导航栏
                if (gameNav) gameNav.style.display = 'none';
                gameScreen.classList.add('active');
                gameRound.textContent = data.round || 1;
                gameState.currentPhase = data.current_phase || 'preparation';
                gameState.currentAttacker = data.current_attacker;
                // 记录攻击顺序（[先手, 后手]），供「是否先手」类判定使用
                if (Array.isArray(data.attack_order) && data.attack_order.length) {
                    gameState.attackOrder = data.attack_order;
                }
                initGameBoards();
                updateTurnIndicator(data.current_attacker, data.attacks_remaining);
                updatePhaseUI(); // 确保调用阶段UI更新
                break;
            case 'game_over':
                // 显示导航栏
                if (gameNav) gameNav.style.display = 'block';
                gameOverScreen.classList.add('active');
                // 结算展示（判定头 + 本局数据）只有一份实现 —— 与 socket 事件那条路径共用
                renderGameOverHead(data);
                /* 重连落在一个**已经结束**的对局上时也要有「本局回放」入口。
                   这条载荷来自 `game_state`（服务端的 game_over 分支），它**不带**
                   `match_id`（那是 `game_over` 事件专有的）⇒ 这里只能清空入口。
                   ⚠️ 刻意**不去** fetch 战绩挑最新一条来补 —— 那正是任务书禁止的猜法
                      （可能挑到别人的局或上一局）。重连场景下入口消失是**如实**的：
                      这一条路径上没有权威 id。 */
                rememberGameOverMatchId(data);
                clearActiveGame();
                break;
            default:
                console.error('Unknown game state:', data.state);
                // 显示导航栏
                if (gameNav) gameNav.style.display = 'block';
                roomInfo.classList.remove('hidden');
                currentRoomId.textContent = gameState.roomId;
                roomInfo.querySelector('.waiting-message').textContent = '未知游戏状态，请刷新页面';
        }
    });

    // ===== 掉线/重连（2026-09-07 新增）=====
    socket.on('connect', () => {
        // 重连 = 一个新的部署阶段（A04）：掉线时那条在飞的 place_ships ack 永远不会来了，
        // 不重置的话界面会带着"正在提交，等待对手…"的锁回到重连后的页面。
        // 权威状态由下面的 rejoin_room + room_sync 拿回来（重连落在布船阶段时，
        // applyRoomSync 会把屏切回布船并有 initBoard 重画棋盘）。
        newDeployPhase('socket_connect');
        const active = loadActiveGame();
        if (active && active.room_id && active.player_id) {
            console.log('尝试自动重连对局:', active.room_id);
            socket.emit('rejoin_room', {
                room_id: active.room_id,
                player_id: active.player_id,
                token: gameState.reconnectToken || active.token || ''
            }, (resp) => {
                if (resp && resp.status === 'error') console.log('重连失败:', resp.message);
            });
        }
    });
    socket.on('resume_game', (data) => {
        console.log('服务端提示恢复对局:', data);
        if (data && data.room_id && data.player_id) {
            saveActiveGame(data.room_id, data.player_id);
            socket.emit('rejoin_room', {
                room_id: data.room_id,
                player_id: data.player_id,
                token: (gameState.reconnectToken || (loadActiveGame() && loadActiveGame().token) || '')
            }, (resp) => {
                if (resp && resp.status === 'error') console.log('恢复对局失败:', resp.message);
            });
        }
    });
    socket.on('reconnect_token', (data) => {
        if (data && data.token) {
            gameState.reconnectToken = data.token;
            const g = loadActiveGame();
            if (g && g.room_id) saveActiveGame(g.room_id, g.player_id);
        }
    });
    socket.on('opponent_disconnected', (data) => {
        console.log('对手掉线:', data);
        showOpponentGoneBanner(data.deadline || (Date.now() / 1000 + (data.seconds || 30)));
        showMessage('对手已掉线，等待重连…');
    });
    socket.on('opponent_reconnected', () => {
        console.log('对手重连');
        hideOpponentGoneBanner();
        showMessage('对手已重连，对局继续');
    });
    socket.on('game_canceled', (data) => {
        console.log('对局取消:', data);
        /* ⚠️ 房间身份核对（2026-09-29 修，实测竞态）：
           这条是房间级广播，可能属于**上一个已经解散的房间**。原样认下的话，
           一个刚进新房间的玩家会被上一条迟到的取消踢回首页
           —— `friend_invite_battle_check.mjs` 的 ★9s/★9t 就是这么红的
           （同一命令换次运行又全绿）。
           判据：两边都有 room_id 且不相等 ⇒ 这条与我无关，忽略。
           只有一边有（旧服务端载荷 / 还没进房）→ 照旧认下，不改变原有行为。 */
        if (data && data.room_id && gameState.roomId
            && String(data.room_id) !== String(gameState.roomId)) {
            console.log('忽略：这条取消属于别的房间', data.room_id, '当前', gameState.roomId);
            return;
        }
        hideOpponentGoneBanner();
        clearActiveGame();
        if (data && data.message) showAlert(data.message);
        setTimeout(() => resetGame(), 1500);
    });
    socket.on('reconnect_warning', (data) => {
        console.log('掉线警告:', data);
        clearActiveGame();
        if (data && data.message) showAlert(data.message);
        setTimeout(() => resetGame(), 2000);
    });
    socket.on('room_sync', (data) => {
        console.log('对局快照恢复:', data);
        applyRoomSync(data);
    });

    socket.on('rps_result', (result) => {
        console.log('RPS result:', result);
        // 结果到达 = 这一次判定结束：先把这一轮的令牌作废（还在路上的 ack 从此失效），
        // 再收回「已出拳」锁定。平局时服务端已经清空 rps_choices 等双方重出，
        // 所以这里必须真的解锁，否则玩家会卡在"三个手势都点不动"。
        rpsChoiceRound++;
        rpsChoicePending = false;
        if (rpsChoiceAckTimer) { clearTimeout(rpsChoiceAckTimer); rpsChoiceAckTimer = null; }
        rpsResult.classList.remove('hidden');
        setRPSWaiting(false);
        if (result.status === 'tie') {
            // 服务端文案是「平局，重新猜拳」；这一屏要给的是一句"接下来做什么"的准话，
            // 服务端原文里「平局」二字已经在标题里说过了，就不再重复。
            const detail = String(result.message || '');
            rpsResult.textContent = '平局，请重新选择一种手势'
                + (detail && detail.indexOf('平局') === -1 ? '：' + detail : '');
            rpsResult.classList.add('is-tie');
        } else {
            rpsResult.classList.remove('is-tie');
            const winnerName = result.winner === gameState.playerId ? '你' : '对手';
            rpsResult.textContent = `猜拳结果：你选择了${getRPSName(result.choices[gameState.playerId])}, 对手选择了${getRPSName(result.choices[Object.keys(result.choices).find(k => k !== gameState.playerId)])}。${winnerName}获胜，先攻击！`;
        }
    });

    socket.on('attack_result', (result) => {
        console.log('Attack result:', result);
        // 击沉 > 命中 > 落空，优先级从高到低
        if (result.ship_sunk) playSfx('sunk');
        else if (result.hit) playSfx('hit');
        else playSfx('miss');
        updateAttackDisplay(result);
        attacksRemaining.textContent = result.remaining_attacks;

        // 更新攻击次数后，重新检查阶段UI，确保按钮显示正确
        updatePhaseUI();

        // 攻击日志由服务端 game_log 事件统一推送，避免前后端重复
    });

    // 添加处理攻击次数更新事件
    socket.on('attacks_updated', (data) => {
        console.log('Attacks updated:', data);
        attacksRemaining.textContent = data.attacks_remaining;
        updatePhaseUI();
    });

    socket.on('turn_change', (data) => {
        console.log('Turn change:', data);
        if (data.current_attacker === gameState.playerId) playSfx('turn');
        gameState.currentPhase = data.phase;  // 添加阶段更新
        updateTurnIndicator(data.current_attacker, data.attacks_remaining);
        updatePhaseUI();  // 更新阶段UI
    });

    socket.on('game_over', (data) => {
        console.log('Game over:', data);
        playSfx(data.winner === gameState.playerId ? 'win' : 'lose');

        // 隐藏状态显示栏中的所有效果
        document.getElementById('reinforcement-status')?.classList.add('hidden');
        document.getElementById('holy-heart-status')?.classList.add('hidden');
        renderActiveEffects({ self: [], opponent: [] });   // 结算界面不该再挂着「生效中」的角标
        // 绝处逢生的两个门禁标记也要一起清：它们只用于"出牌门禁/提示"，对局结束
        // 就没有意义了，留着会让下一局的出牌门禁带着上一局的结论。
        gameState.lastStandLock = false;
        gameState.lastStandWin = false;
        hidePriorityWaitingBanner();                        // 对局结束：等待横幅一并撤掉
        hideShenjiWaitingBanner();
        // 对局结束：连锁区域预览一并清掉（结算屏上不该还画着"某某卡要打这几格"）
        if (typeof clearChainPreview === 'function') clearChainPreview();
        // 对局结束也必须收掉桃园的全屏等待浮层：对方在选择中掉线被判负时，
        // 等着的这一方否则会被那层浮层一直挡住（同 handle_cancel_magic_selection 那个病灶）
        dismissTaoyuanWaitingOverlay();
        // 对局结束，手牌选中态一并清掉
        gameState.selectedCardIndex = -1;
        gameState.selectedCardKey = null;
        if (typeof updateHandUI === 'function') updateHandUI();

        switchScreen(gameOverScreen);
        // 本局新解锁的徽章：服务端在结算时**只发给本人**一条 achievements_unlocked，
        // 它比 game_over 先到（_finalize_match 在 emit game_over 之前），所以这里做一次
        // 兜底刷新 —— 无论事件先后，结算界面上都会出现「本局刚解锁 …」。
        renderAchievementUnlockPanel();
        // 根据胜利原因显示不同的提示（判定头 + 本局数据，与 room_sync 那条路径共用一份实现）
        renderGameOverHead(data);
        // 本局回放入口（W5）：只认服务端给的权威 match_id，没有就隐藏入口
        rememberGameOverMatchId(data);
        // 好友批：结算界面把对手那一行的「加好友」按钮补上。
        // ⚠️ 触发它的是 socket 事件 `recent_opponent`（服务端结算时**双方各收一条**），
        //    那条事件的到达顺序不保证 —— 可能在 game_over **之前**也可能在之后
        //    （本项目的经验：`_finalize_match` 系列事件常排在 game_over 之前，
        //    但 `rank_changed` 那种走 background task 的排在之后）。
        //    所以两处都兜一次，名字取"这局那个对手"：
        //    优先用 recent_opponent 给的名字（服务端权威），没有就用对局期间记下的对手名。
        renderRecentOpponentAdd(recentOpponentState.name || gameState.opponentName || '',
            recentOpponentState.relation);
    });

    // =======================================================================
    // ★ 实时观战（第 3 批）：观众侧的实时流
    // -----------------------------------------------------------------------
    // 这里的监听器**都带 `spectateActive()` 门禁**，因为 socket 是同一个：
    // 对局屏与观战屏共用一条连接，但**两块屏的状态是分开的**。
    // 不加门禁就会出两种事：
    //   ① 观众收到对局事件时，对局屏的处理函数拿 undefined 的 playerId 去比
    //      （正是本批要避开的"两块棋盘全反"）；
    //   ② 打过一局的人再去看别人，上一局的状态会串到观战屏上。
    // 事件名是**服务端已净化的白名单**（spectate.SPECTATE_EVENTS），
    // 所以观众收到的那一份里没有坐标字段、座位一律是 p1/p2。
    // =======================================================================
    const spectateActive = () => !!(gameState.spectate && gameState.spectate.active);

    socket.on('spectate_sync', (data) => {
        const sp = gameState.spectate;
        if (!sp.active) {
            // ack 还没回来，但快照先到了 —— 存起来，joinSpectate 会用它切屏。
            // （丢掉它就会出现"ack 成功、屏幕空白"这种最难查的假成功。）
            sp.pendingSync = data;
            return;
        }
        applySpectateSnapshot(data);
    });
    socket.on('spectate_count_changed', (data) => {
        if (!spectateActive()) return;
        gameState.spectate.count = spectateInt(data && data.count, gameState.spectate.count);
        renderSpectateCounts();
    });
    // ★ 第 4 批：观战席名单（**只有观众收得到**这条事件）。
    //   服务端把它只发进 `spectate:<room_id>` —— 对局双方不在那个收件人集合里，
    //   所以"玩家收不到名单"是结构性的，前端这里不需要、也不该做任何过滤。
    socket.on('spectate_roster', (data) => {
        if (!spectateActive()) return;
        applySpectateRoster(data);
    });
    // 观众自己叫什么（单发给本人，只含显示名）—— 名单里据此标出"我"。
    socket.on('spectate_you', (data) => {
        if (!spectateActive()) return;
        gameState.spectate.me = (data && data.name) ? String(data.name) : null;
        renderSpectateRoster();
    });
    // "谁来了 / 谁走了" —— 作为系统提示出现在聊天区（**不是**一条真人发言）。
    socket.on('spectate_joined', (data) => {
        if (!spectateActive()) return;
        spectateChatNotice(spectateDisplayName(data && data.name) + ' 来到了观战席');
    });
    socket.on('spectate_left', (data) => {
        if (!spectateActive()) return;
        spectateChatNotice(spectateDisplayName(data && data.name) + ' 离开了观战席');
    });
    // ★★ 观战席聊天：**对局双方永远收不到这条**（同上，只发观战通道）。
    socket.on('spectate_chat', (data) => {
        if (!spectateActive()) return;
        appendSpectateChat(data);
    });
    // 玩家之间的聊天（第 1 批就登记在 `SPECTATE_EVENTS` 里）。
    // ⚠️ 第 4 批修的**真缺陷**：服务端那条 `chat_message` 原本是 `to=<sid>` 单发，
    //    而观战第三条腿只对广播类生效 → 观众一个字节都收不到。现在服务端改成
    //    房间级广播，于是这里收到了。它与「观战席聊天」是两个方向、两种颜色：
    //    这条是**在对局里说话的人**，观众只能看、不能回。
    //    ⚠️ 必须带门禁：**观战屏激活时**才记进观战聊天区，否则观众会把这句
    //       同时塞进对局屏的聊天框（两块屏的状态是分开的，见本段开头那条铁律）。
    socket.on('chat_message', (data) => {
        if (!spectateActive()) return;
        appendSpectatePlayerChat(data);
    });
    socket.on('spectate_ended', (data) => {
        if (!spectateActive()) return;
        spectateOnEnded(data);
    });
    // ★ 第 5 批：观战棋盘帧（棋盘真的变了的时候服务端推的权威数据）。
    //   覆盖两种以前**完全没有更新路径**的情况：疗愈原地复活、棋盘整块重置
    //   （回光返照 / 灵气复苏 / 败者食尘）。见 `applySpectateBoardFrame`。
    socket.on('spectate_board', (data) => {
        if (!spectateActive()) return;
        applySpectateBoardFrame(data);
    });
    socket.on('attack_result', (result) => {
        if (!spectateActive()) return;
        spectateOnAttackResult(result);
    });
    socket.on('magic_chain_updated', (data) => {
        if (!spectateActive()) return;
        spectateOnChainUpdated(data);
    });
    socket.on('chain_resolved', (data) => {
        if (!spectateActive()) return;
        // 连锁结算完 → 栈空了。服务端这条 payload 里带的是**结算结果**（卡名/成功与否），
        // 不是新的栈，所以这里只把栈清空（画面上的"当前连锁"归零）。
        spectateOnChainUpdated({ chain: [], chain_len: 0 });
        if (data && data.message) showMessage(String(data.message));
    });
    socket.on('game_log', (entry) => {
        if (!spectateActive()) return;
        appendSpectateLog(entry);
    });
    socket.on('turn_change', (data) => {
        if (!spectateActive()) return;
        spectateOnTurnChange(data);
    });
    socket.on('phase_updated', (data) => {
        if (!spectateActive()) return;
        spectateOnPhaseUpdated(data);
    });
    socket.on('field_magic_updated', (data) => {
        if (!spectateActive()) return;
        const snap = gameState.spectate.snapshot;
        if (!snap) return;
        // ★ 第 5 批修的**真缺陷**：服务端这条 payload 的形状是
        //   `{'player_id': …, 'card': <MagicCard 实例序列化后的 {name,speed,type,…}> | None}`
        //   —— 卡名在 **`data.card.name`** 上。这里原先读的是 `data.name` /
        //   `data.field_magic`（两个都不存在）⇒ 恒为 `undefined` ⇒ `snap.field_magic`
        //   被**清成空串** ⇒ 观战屏永远显示「无」，而对局双方看到的是正确卡名
        //   （玩家侧 `updateFieldMagicUI(data.player_id, data.card)` 读的就是 card.name）。
        //   `card` 为 `None` 表示场地被拆除 / 顶替 → 如实清空。
        const card = data && data.card;
        const name = (card && card.name) ? String(card.name)
            : ((data && data.field_magic) ? String(data.field_magic) : '');
        snap.field_magic = name;
        renderSpectateHeader();
    });
    socket.on('game_over', (data) => {
        if (!spectateActive()) return;
        spectateOnGameOver(data);
    });

    socket.on('achievements_unlocked', (data) => {
        // 只发给本人的结算反馈。缓冲 + 立刻渲染（那块面板长在结算屏里，
        // 此刻可能还没切过去，但内容先填好，切屏后就能直接看到）。
        const items = (data && Array.isArray(data.items)) ? data.items : [];
        if (!items.length) return;
        pendingUnlockBadges = items.slice();
        renderAchievementUnlockPanel();
        // 对局日志里也留一行（玩家翻日志时能看到是哪局解锁的）
        const names = items.map(b => b.name || b.id).join('、');
        addGameLog('<span class="log-badge log-badge-info">成就</span>'
            + '<span class="log-text">本局解锁了新徽章：' + escapeHtml(names) + '</span>', 'info');
    });

    socket.on('xp_gained', (data) => {
        // 结算经验：只发给本人（服务端按 sid 单发）。面板长在结算屏里，
        // 事件比 game_over 先到，所以这里直接开播；game_over 那边再兜一次。
        try {
            showXpPanel(data);
            // 顺手把首页的等级条更新成"这一局之后"的状态（不用再打一次接口）
            if (data && data.after) refreshMyLevelStrip(data.after);
        } catch (e) {
            console.warn('经验动画失败（不影响结算）:', e && e.message);
        }
    });

    socket.on('rank_changed', (data) => {
        // 排位结算：**逐人单发**（服务端按 sid 发，对手看到的是他自己那份）。
        // 休闲局永远收不到这个事件 —— 所以 `#rank-gain-panel` 在休闲对局里不显示，
        // 前端**不需要**再用 mode 判一次。
        // 事件顺序：服务端把它排在 `game_over` 之后（它甚至走 background task 脱离请求上下文），
        // 所以到达时结算屏已经切好了。
        try {
            showRankGainPanel(data);
        } catch (e) {
            console.warn('段位动画失败（不影响结算）:', e && e.message);
        }
    });

    // ==================== 好友批：四个服务端 → 客户端的 socket 事件 ====================
    // 事件名与 payload 是**冻结契约**，一个字母都不能改（后端在并行实现）：
    //   friend_request  {from_user_id, from_username, from_avatar}
    //   friend_accepted {user_id, username, avatar}
    //   friend_invite   {room_id, from_user_id, from_username}
    //   recent_opponent {user_id, username, avatar, relation}
    // ⚠️ 每个 handler 都整块 try/catch：这四条都是"顺带提示"类事件，
    //    任何一条抛异常都不该把当前这局对局搅黄（同 xp_gained / rank_changed 的处理）。

    socket.on('friend_request', (data) => {
        try {
            handleFriendRequestEvent(data);
        } catch (e) {
            console.warn('好友申请提示失败（不影响对局）:', e && e.message);
        }
    });

    socket.on('friend_accepted', (data) => {
        try {
            handleFriendAcceptedEvent(data);
        } catch (e) {
            console.warn('好友通过提示失败（不影响对局）:', e && e.message);
        }
    });

    socket.on('friend_invite', (data) => {
        try {
            handleFriendInviteEvent(data);
        } catch (e) {
            console.warn('处理好友邀战失败（不影响对局）:', e && e.message);
        }
    });

    socket.on('recent_opponent', (data) => {
        try {
            handleRecentOpponentEvent(data);
        } catch (e) {
            console.warn('处理最近对手失败（不影响结算）:', e && e.message);
        }
    });

    // 好友私聊：收到一条私聊（私聊批，2026-09-19）。
    // payload 恰好 7 个字段（dm.PUSH_PAYLOAD_KEYS 是唯一一份清单）：
    //   {id, from_uid, from_username, from_avatar, body, created_at, stamp}
    // ⚠️ **没有 `mine`** —— 服务端有意不下发"发送方视角"的字段（§4 的坑 4），
    //    所以这条事件永远只可能是"别人发给我的"，渲染时一律 data-mine="0"。
    // ⚠️ 与本批三条好友事件一样整块 try/catch：它在对局中随时可能到，
    //    抛异常不该把当前这局搅黄。
    socket.on('friend_message', (data) => {
        try {
            handleFriendMessageEvent(data);
        } catch (e) {
            console.warn('处理好友私聊失败（不影响对局）:', e && e.message);
        }
    });

    // 添加阶段更新监听
    socket.on('phase_updated', (data) => {
        gameState.currentPhase = data.current_phase;
        gameState.currentAttacker = data.current_attacker;
        updatePhaseUI();
    });

    // 极限增援相关事件处理
    // ⚠️ 这两张卡原先各有两条显示路径：「大倒计时横幅」+「状态栏胶囊」。横幅的 DOM 已在
    //    2026-10-03 删除 —— 它与顶部那三颗回合胶囊被分到同一个网格格，生效时整块盖住
    //    顶部状态条，还把棋盘行挤矮。现在只剩胶囊这一条路径，剩余回合仍然写进
    //    `#*-status-remaining`。服务端的计时 / 判定 / 结算逻辑没有任何变化。
    socket.on('reinforcement_activated', (data) => {
        console.log('极限增援激活:', data);
        const statusElement = document.getElementById('reinforcement-status');
        const statusRemainingElement = document.getElementById('reinforcement-status-remaining');

        if (statusElement && statusRemainingElement) {
            statusRemainingElement.textContent = data.remaining_turns;
            statusElement.classList.remove('hidden');
        }
    });

    socket.on('reinforcement_turn_updated', (data) => {
        console.log('极限增援回合更新:', data);
        const statusRemainingElement = document.getElementById('reinforcement-status-remaining');

        if (statusRemainingElement) {
            statusRemainingElement.textContent = data.remaining_turns;
        }
    });

    // 无暇圣心激活监听
    socket.on('holy_heart_activated', (data) => {
        console.log('无暇圣心激活:', data);
        const statusElement = document.getElementById('holy-heart-status');
        const statusRemainingElement = document.getElementById('holy-heart-status-remaining');

        if (statusElement && statusRemainingElement) {
            statusRemainingElement.textContent = data.remaining_turns;
            statusElement.classList.remove('hidden');
        }
    });

    // 无暇圣心回合更新监听
    socket.on('holy_heart_turn_updated', (data) => {
        console.log('无暇圣心回合更新:', data);
        const statusRemainingElement = document.getElementById('holy-heart-status-remaining');

        if (statusRemainingElement) {
            statusRemainingElement.textContent = data.remaining_turns;
        }
    });

    // 无暇圣心中断监听
    socket.on('holy_heart_interrupted', (data) => {
        console.log('无暇圣心中断:', data);
        const statusElement = document.getElementById('holy-heart-status');

        if (statusElement) {
            statusElement.classList.add('hidden');
        }
        // 显示中断原因
        showMessage(data.reason);
    });

    // 极限增援结束监听

    // 添加场地魔法更新监听
    socket.on('field_magic_updated', function (data) {
        console.log('场地魔法更新:', data);
        updateFieldMagicUI(data.player_id, data.card);
    });

    // 添加魔法卡连锁相关事件监听
    socket.on('magic_chain_updated', (data) => {
        // 服务端下发的是**净化过的**链路：{chain:[{card,seat,negated,preview}], chain_len}
        // （`card` 是卡名字符串、`preview` 是公开区域预览）。
        gameState.chain = (data && Array.isArray(data.chain)) ? data.chain : [];
        updateChainUI();       // 内部先刷新预览层（多区域并存、各标卡名）
    });

    socket.on('chain_resolved', function (data) {
        console.log('连锁结算完成', data.results);
        // 服务端结算后只发 chain_resolved，不再发 magic_chain_updated，
        // 这里必须自己清空连锁栈 —— 否则「当前连锁 (N)」会一直挂着旧内容。
        // ★ 区域预览同理：不清就会在结算后继续把「这张卡要打这几格」画在棋盘上
        //   （效果已经落地了，那块高亮就是假的）。`updateChainUI` 内部会清预览层。
        gameState.chain = [];
        if (typeof updateChainUI === 'function') updateChainUI();
        // 应用连锁结算结果
        data.results.forEach(result => {
            // ⚠️ 结算失败的卡不能再说「效果生效」。
            // 例如平等条约现在无法无效化炮击造成的击沉，服务端会回 success=false；
            // 若照旧调用 applyCardEffect，双方都会看到「船数改变效果被无效化」的假消息，
            // 而实际上船根本没回来。
            //
            // 另外要分清两种 success=false，它们的含义完全不同：
            //   · negated_skip —— 这张牌【被别人康掉了】，不是它自己不行
            //   · 其它          —— 这张牌【发动条件不满足】，是它自己的问题
            // 混用同一句「X未能生效：…」会让玩家误以为康没成功（实测踩过）。
            if (result.success === false) {
                if (result.negated_skip) {
                    const by = result.negated_by || '对方的无效化效果';
                    showMessage(`【${result.card.name}】被${by}无效化了`,
                                { type: 'warning' });
                } else {
                    showMessage(`${result.card.name}未能生效：${result.message || '条件不满足'}`,
                                { type: 'warning' });
                }
            } else {
                applyCardEffect(result.card, result.caster);
            }
            // 将使用过的卡牌加入弃牌堆
            gameState.discardPile.push(result.card);
            renderArenaRail();   // 三区操作列的「弃牌堆」计数（第 37 节）

            // 魔法卡日志由服务端 game_log 事件统一推送，避免前后端重复

            // 处理需要选择的魔法卡效果
            if (result.temp_data_id) {
                if (result.temp_data_id === 'taoyuan_choice') {
                    // 只有当施法者是当前玩家时，才显示桃园结义选择UI
                    if (result.caster === gameState.playerId) {
                        // 桃园结义选择UI
                        showTaoyuanChoice(result);
                    }
                } else if (result.temp_data_id === 'divine_decree') {
                    // 神之宣告的「选两艘船 + 选效果」都在出牌链路里问完了
                    // （own_ships 选船 → promptDivineDecreeChoice 选效果）。
                    // 这里仅作兼容兜底：不再调用不存在的函数，避免中断整个连锁结算。
                    console.warn('收到 divine_decree 选择请求，选择已在出牌链路完成，忽略');
                } else if (result.temp_data_id === 'lingqi_choice') {
                    // 只有当施法者是当前玩家时，才显示灵气复苏选择UI
                    if (result.caster === gameState.playerId) {
                        // 灵气复苏选择UI
                        showLingqiChoice(result);
                    }
                } else if (result.temp_data_id === 'bury_choice') {
                    // 只有当施法者是当前玩家时，才显示明智埋葬选择UI
                    if (result.caster === gameState.playerId) {
                        // 明智埋葬选择UI
                        showBuryChoice(result);
                    }
                } else if (result.temp_data_id === 'wangyang_choice') {
                    // 只有当施法者是当前玩家时，才显示亡羊补牢选择UI
                    if (result.caster === gameState.playerId) {
                        showWangYangChoice(result);
                    }
                } else if (result.temp_data_id === 'shenji_declare') {
                    // 神机妙算宣言：仅施法者需要输入
                    if (result.caster === gameState.playerId) {
                        showShenjiDeclarePrompt(result);
                    }
                } else if (result.temp_data_id === 'shield_choice') {
                    // 仁王之盾：选择至多3艘自己的船
                    if (result.caster === gameState.playerId) {
                        showRenwangChoice();
                    }
                }
            }
        });
        // 更新游戏状态
        updateHandUI();
        // 如果是攻击阶段，恢复攻击状态
        if (gameState.currentPhase === 'battle') {
            if (typeof enableAttack === 'function') enableAttack();
        }
    });

    // 等待神之宣告选择的通知

    // 神之宣告结算完成通知

    // 弃牌堆更新通知


    socket.on('chain_request', function (data) { showChainRequestPrompt(data); });

    // 阶段转换的「优先权询问」：对方要推进阶段（进战斗 / 进结束）时，
    // 先问我要不要打出一张速阶3。参照游戏王 YGO 的优先权确认。
    socket.on('priority_request', function (data) { showPriorityPrompt(data); });
    // 我发起的阶段转换被拦下了：显示"等待对方响应"+倒计时，并把阶段按钮全部禁用。
    // 后端同一时刻也在冻结我的攻击/出牌/交回合（_priority_wait_reason），
    // 两边口径必须一致 —— 否则玩家会看到"按钮能点但服务端拒绝"的割裂。
    socket.on('priority_waiting', function (data) {
        data = data || {};
        const actionText = data.action_text || '阶段转换';
        const secs = Number(data.countdown) || 10;
        showPriorityWaitingBanner(actionText, Date.now() / 1000 + secs);
    });
    // 等待结束（对方响应了 / 超时了 / 被取消）：解冻
    socket.on('priority_waiting_end', function () { hidePriorityWaitingBanner(); });

    // 对方正在宣言神机妙算：显示等待横幅 + 冻结我的行动（服务端同时会拒绝）。
    socket.on('shenji_waiting', function (data) {
        showShenjiWaitingBanner(data && data.text);
    });
    socket.on('shenji_waiting_end', function () { hideShenjiWaitingBanner(); });
    // 拒绝开关的状态回执
    socket.on('priority_setting_updated', function (data) {
        gameState.declinePriority = !!(data && data.decline);
        syncDeclinePriorityUI();
    });

    // 连锁响应弹窗（10 秒倒计时 + 点选速阶 3 卡）。
    // 抽成具名函数是为了让「重连正好落在响应窗口内」也能把弹窗补回来。
    let activeChainPromptCleanup = null;
    function showChainRequestPrompt(data) {
        if (activeChainPromptCleanup) activeChainPromptCleanup();
        // 绝处逢生生效中：自己的其余魔法卡全部无效，连锁响应同样打不出去。
        // 服务端（chain_response → can_play_magic_card）一定会拒绝，所以别弹这个
        // 窗口让玩家白点一次 —— 那会让窗口凭空消失、也没有任何解释。
        // 直接替玩家放弃，并把原因说清楚。
        if (isLastStandActive()) {
            showMessage('绝处逢生生效中，本回合你的其余魔法卡全部无效，已自动放弃连锁', { type: 'warning' });
            gameState.socket.emit('chain_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                chain: false
            });
            return;
        }
        playSfx('chain');

        const cards = Array.isArray(data.speed3_cards) ? data.speed3_cards : [];
        const total = data.countdown || 10;
        let left = total;
        // 桌面有 hover 就「移上去看效果」；触摸设备没有 hover，改成「点一次看、再点一次打出」。
        // 与日志卡名同一套判据（game.js 的 initGameLogCardRefs）。
        const canHover = !window.matchMedia || window.matchMedia('(hover: hover)').matches;
        // 效果描述来自前端卡面数据（window.magicCards），服务端 payload 里只有 name/speed
        const fullOf = (c) => lookupCard(c && c.name) || c || {};

        let cardsHTML = '';
        if (cards.length) {
            cardsHTML = cards.map((c, index) => {
                const desc = String(fullOf(c).description || '');
                const brief = desc.length > 46 ? desc.slice(0, 46) + '…' : desc;
                return `<button type="button" class="priority-card chain-request-card" data-card-index="${index}">
                    <span class="priority-card-name chain-request-card-name">${escapeHtml(String(c.name))}</span>
                    <span class="priority-card-speed chain-request-card-speed">速阶 ${escapeHtml(String(c.speed))}</span>
                    ${brief ? `<span class="chain-request-card-desc">${escapeHtml(brief)}</span>` : ''}
                </button>`;
            }).join('');
        } else {
            cardsHTML = '<p class="priority-empty chain-request-empty">你手上没有速阶3的魔法卡</p>';
        }

        // 对方（或自己）刚发动的那张卡：卡名做成可预览的锚点。
        // 作者要求：连锁窗口里必须能看"对方发动的是什么效果"，只给个卡名等于让人猜。
        // 与手牌同一套判据：桌面悬停出浮层，触摸设备点一下出详情小窗。
        const activatedName = String((data.card && data.card.name) || '未知卡');
        const activatedCard = fullOf(data.card);

        const cardsHint = canHover
            ? '把鼠标移到卡上可以看效果，点一下即打出；上面的卡名也能看对方那张卡。不响应请点「不响应」。'
            : '点一下先看效果，再点一下才打出；上面的卡名可以看对方那张卡。不响应请点「不响应」。';

        // 清掉可能残留的旧弹窗（重连 / 连续连锁时不叠加），并收掉可能还挂着的悬停浮层
        document.querySelectorAll('.chain-request-prompt').forEach(el => el.remove());
        hideCardTooltip();

        // 结构与 class 与阶段转换的优先权弹窗同源：
        // **外层**只用 `chain-request-prompt`（它是"这是哪个弹窗"的语义锚点 ——
        //   `.priority-prompt` 会被 showPriorityPrompt 的清理逻辑删掉，共用它会误删连锁弹窗）；
        // **内层**复用 `priority-*` 作视觉基类（面板/徽标/圆环/卡牌/按钮，深色主题与
        //   "剩余 3 秒变红"都自动继承），`chain-request-*` 只放连锁专属差异（蓝色 accent、描述行）。
        // 改整体质感只需改 .priority-* 一处，两个弹窗同时生效。
        const chainPrompt = document.createElement('div');
        chainPrompt.className = 'chain-request-prompt';
        chainPrompt.innerHTML = `
            <div class="priority-panel chain-request-panel">
                <div class="priority-head chain-request-head">
                    <span class="priority-badge chain-request-badge">连锁</span>
                    <h3>${data.caster && data.caster === gameState.playerId ? '你发动了' : '对方发动了'}魔法卡<button type="button" class="chain-request-card-ref" id="chain-request-activated">【${escapeHtml(activatedName)}】</button></h3>
                </div>
                <div class="priority-ring chain-request-ring" id="chain-request-ring">
                    <span id="chain-countdown-time">${total}</span>
                </div>
                <p class="priority-hint chain-request-hint">${cardsHint}</p>
                <div class="priority-cards chain-request-cards">${cardsHTML}</div>
                <div class="priority-actions chain-request-actions">
                    <button type="button" id="chain-collapse" class="priority-cancel-btn chain-request-collapse">暂时收起 · 查看棋盘</button>
                    <button type="button" id="chain-cancel" class="priority-cancel-btn chain-request-cancel">不响应</button>
                </div>
            </div>
        `;
        document.body.appendChild(chainPrompt);
        const reopenButton = document.createElement('button');
        reopenButton.type = 'button';
        reopenButton.className = 'chain-request-reopen';
        reopenButton.innerHTML = '连锁响应 <span class="chain-request-reopen-time"></span> 秒 · 展开';

        // 倒计时圆环：与优先权弹窗同一个 --ring-deg 机制，≤3 秒变红
        const ring = chainPrompt.querySelector('#chain-request-ring');
        const tick = () => {
            const el = chainPrompt.querySelector('#chain-countdown-time');
            if (el) el.textContent = left;
            const reopenTime = reopenButton.querySelector('.chain-request-reopen-time');
            if (reopenTime) reopenTime.textContent = left;
            if (ring) {
                const deg = Math.max(0, Math.min(360, (left / total) * 360));
                ring.style.setProperty('--ring-deg', deg + 'deg');
                ring.classList.toggle('urgent', left <= 3);
            }
        };
        tick();

        let countdownTimer = null;
        const closePrompt = () => {
            clearInterval(countdownTimer);
            hideCardTooltip();
            if (chainPrompt.parentNode) chainPrompt.parentNode.removeChild(chainPrompt);
            if (reopenButton.parentNode) reopenButton.parentNode.removeChild(reopenButton);
            if (activeChainPromptCleanup === closePrompt) activeChainPromptCleanup = null;
        };
        activeChainPromptCleanup = closePrompt;

        const collapseButton = chainPrompt.querySelector('#chain-collapse');
        collapseButton.addEventListener('click', () => {
            hideCardTooltip();
            chainPrompt.classList.add('is-collapsed');
            document.body.appendChild(reopenButton);
            const chainSlot = document.getElementById('arena-chain-slot');
            if (chainSlot) {
                const rect = chainSlot.getBoundingClientRect();
                if (rect.width > 0) {
                    reopenButton.style.left = `${Math.round(rect.left - reopenButton.offsetWidth - 2)}px`;
                    reopenButton.style.top = `${Math.round(rect.top - 7)}px`;
                }
            }
            reopenButton.focus({ preventScroll: true });
        });
        reopenButton.addEventListener('click', () => {
            if (reopenButton.parentNode) reopenButton.parentNode.removeChild(reopenButton);
            chainPrompt.classList.remove('is-collapsed');
            collapseButton.focus({ preventScroll: true });
        });

        // 倒计时结束 → 自动「不响应」（与旧行为一致）
        countdownTimer = setInterval(() => {
            left -= 1;
            tick();
            if (left <= 0) {
                gameState.socket.emit('chain_response', {
                    room_id: gameState.roomId,
                    player_id: gameState.playerId,
                    chain: false
                });
                closePrompt();
            }
        }, 1000);

        // 对方刚发动的那张卡：桌面悬停看效果，触摸设备点一下出详情。
        // 只做"看"，不改变响应行为（点它不等于打出、也不等于不响应）。
        const activatedRef = chainPrompt.querySelector('#chain-request-activated');
        if (activatedRef) {
            if (canHover) {
                activatedRef.addEventListener('mouseenter', () => showCardTooltip(activatedRef, activatedCard));
                activatedRef.addEventListener('mouseleave', hideCardTooltip);
            }
            activatedRef.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault();
                hideCardTooltip();
                showCardDetail(activatedCard);
            });
        }

        // 不响应
        const cancelButton = chainPrompt.querySelector('#chain-cancel');
        if (cancelButton) {
            cancelButton.addEventListener('click', () => {
                gameState.socket.emit('chain_response', {
                    room_id: gameState.roomId,
                    player_id: gameState.playerId,
                    chain: false
                });
                closePrompt();
            });
        }

        const respondWith = (cardIndex, selectedCard) => {
            closePrompt();

            // 需要目标的速阶3卡（神威！/轰炸/冻结/硫磺火焰/探测雷达）此前
            // 一律发 targets: []，服务端缺目标直接失败 —— 等于这些卡在连锁
            // 响应窗口里根本打不出来。改为先走目标选择器，再回填 targets。
            if (needsTargetSelection(selectedCard.name)) {
                gameState.pendingChainCard = { card: selectedCard, index: cardIndex };
                gameState.currentMagicCard = selectedCard;
                gameState.currentCardIndex = cardIndex;
                // 神之宣告（速阶3）也走这个入口：先在自己棋盘上点选两艘要牺牲的船，
                // 确认后再问效果，最后一起回填给 chain_response。
                showMagicTargetSelection(selectedCard, cardIndex);
                return;
            }

            // 无需目标的卡：直接响应连锁
            gameState.socket.emit('chain_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                chain: true,
                card: selectedCard,
                targets: []
            });
        };

        // 触摸设备：第一次点只弹「卡牌详情」，第二次点同一张才真的打出去，
        // 免得"想看效果"被当成"确认出牌"。
        let detailShownIndex = -1;
        chainPrompt.querySelectorAll('.chain-request-card').forEach((cardElement) => {
            const cardIndex = parseInt(cardElement.dataset.cardIndex, 10);
            const selectedCard = cards[cardIndex];
            if (!selectedCard) return;

            if (canHover) {
                cardElement.addEventListener('mouseenter', () => showCardTooltip(cardElement, fullOf(selectedCard)));
                cardElement.addEventListener('mouseleave', hideCardTooltip);
            }

            cardElement.addEventListener('click', () => {
                if (!canHover && detailShownIndex !== cardIndex) {
                    detailShownIndex = cardIndex;
                    chainPrompt.querySelectorAll('.chain-request-card')
                        .forEach(el => el.classList.remove('detail-shown'));
                    cardElement.classList.add('detail-shown');
                    showCardDetail(fullOf(selectedCard));
                    return;
                }
                respondWith(cardIndex, selectedCard);
            });
        });
    }

    // ── 阶段转换的优先权询问（速阶3抢时点的仲裁）────────────────────────
    // 对方要「进入战斗阶段」或「进入结束阶段」时，先问我要不要打出一张速阶3。
    // 参照游戏王 YGO 的优先权确认：即使我手上没有速阶3也会问（只有「取消」），
    // 因为作者要求"玩家要有选择权"。
    // 弹窗底部有「拒绝所有阶段转换时点」开关 —— 勾上后本局不再弹（可随时取消勾选）。
    function showPriorityPrompt(data) {
        data = data || {};
        const actionText = data.action === 'enter_end' ? '进入结束阶段' : '进入战斗阶段';
        const cards = Array.isArray(data.speed3_cards) ? data.speed3_cards : [];
        const countdown = data.countdown || 10;

        // 清掉可能残留的旧弹窗（重连 / 连续询问时不叠加）
        document.querySelectorAll('.priority-prompt').forEach(el => el.remove());
        playSfx('chain');

        let cardsHTML = '';
        if (cards.length) {
            cardsHTML = cards.map((card, index) => `
                <button type="button" class="priority-card" data-card-index="${index}">
                    <span class="priority-card-name">${escapeHtml(card.name)}</span>
                    <span class="priority-card-speed">速阶 ${escapeHtml(String(card.speed))}</span>
                </button>`).join('');
        } else {
            cardsHTML = '<p class="priority-empty">你手上没有速阶3的魔法卡</p>';
        }

        const prompt = document.createElement('div');
        prompt.className = 'priority-prompt';
        prompt.innerHTML = `
            <div class="priority-panel">
                <div class="priority-head">
                    <span class="priority-badge">优先权</span>
                    <h3>对方即将${actionText}</h3>
                </div>
                <div class="priority-ring" id="priority-ring">
                    <span id="priority-countdown">${countdown}</span>
                </div>
                <p class="priority-hint">你可以打出一张速阶3卡牌后再让对方继续；不打就点「取消」。</p>
                <div class="priority-cards">${cardsHTML}</div>
                <label class="priority-toggle">
                    <input type="checkbox" id="decline-priority-toggle"${gameState.declinePriority ? ' checked' : ''}>
                    <span>拒绝所有阶段转换时点</span>
                    <em>勾上后本局不再询问（可随时取消）</em>
                </label>
                <div class="priority-actions">
                    <button type="button" id="priority-cancel" class="priority-cancel-btn">取消</button>
                </div>
            </div>
        `;
        document.body.appendChild(prompt);

        let left = countdown;
        const ring = prompt.querySelector('#priority-ring');
        const tick = () => {
            const el = prompt.querySelector('#priority-countdown');
            if (el) el.textContent = left;
            // 圆环按剩余比例收缩；少于 3 秒变红提醒
            if (ring) {
                const deg = Math.max(0, Math.min(360, (left / countdown) * 360));
                ring.style.setProperty('--ring-deg', deg + 'deg');
                ring.classList.toggle('urgent', left <= 3);
            }
        };
        tick();
        const timer = setInterval(() => {
            left -= 1;
            tick();
            if (left <= 0) {
                clearInterval(timer);
                answer(false);
            }
        }, 1000);

        function answer(respond, card) {
            clearInterval(timer);
            const toggle = prompt.querySelector('#decline-priority-toggle');
            const declineAll = !!(toggle && toggle.checked);
            // 顺手在这里改的也要记住：本局（服务端）+ 以后各局（本地偏好）
            gameState.declinePriority = declineAll;
            saveDeclinePriorityPref(declineAll);
            gameState.socket.emit('priority_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                respond: respond,
                card: card || null,
                targets: [],
                decline_all: declineAll,
            });
            prompt.remove();
        }

        prompt.querySelector('#priority-cancel')
            .addEventListener('click', () => answer(false));

        prompt.querySelectorAll('.priority-card').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.cardIndex, 10);
                const card = cards[idx];
                if (!card) return;
                // 需要目标的速阶3：先走目标选择器，确认后回填给 priority_response
                // （与连锁响应窗口同一套处理，见 pendingChainCard）
                if (needsTargetSelection(card.name)) {
                    clearInterval(timer);
                    prompt.remove();
                    gameState.pendingPriorityCard = { card: card, index: idx };
                    gameState.currentMagicCard = card;
                    gameState.currentCardIndex = -1;
                    showMagicTargetSelection(card, -1);
                    return;
                }
                answer(true, card);
            });
        });
    }

    // 灵气复苏相关事件
    socket.on('lingqi_waiting', function (data) {
        // 显示等待提示
        showMessage(data.message, { type: 'info' });
    });

    socket.on('lingqi_complete', function (data) {
        // 显示完成提示
        showMessage(data.message, { type: 'info' });
    });

    socket.on('reset_gameboard', function (data) {
        // 重置游戏棋盘，进入重新摆放阶段
        showMessage(data.message, { type: 'warning' });

        // 完全重置游戏状态，确保棋盘干净
        gameState.ships = [];
        gameState.attacks = [];
        gameState.myAttacks = [];
        gameState.opponentAttacks = [];
        gameState.revealedCells = [];   // 服务端在重开棋盘时也会清空已显形记录，本地同步
        gameState.opponentShieldedShips = [];
        gameState.lastStandOwner = null;   // 归属也要一起清，免得重开后又高亮错棋盘
        gameState.frozenArea = null;       // 冻结区域同理
        dismissTaoyuanWaitingOverlay();    // 重开棋盘：桃园全屏等待浮层一并收掉
        // 重开一局：手牌虽然保留，但选中态要清掉（下标含义随时可能变）
        gameState.selectedCardIndex = -1;
        gameState.selectedCardKey = null;
        gameState.remainingShips = 0;
        gameState.opponentRemainingShips = 0;
        gameState.maxShips = data.new_max_ships;
        // ⚠️ 防线：服务端若漏给 `new_max_ships`（或给了 null），这里必须有个数。
        //    `gameState.maxShips` 为 null/0 时，`handleCellClick` 的
        //    `if (gameState.placedShips >= gameState.maxShips) return;` **恒成立**
        //    → 点格子完全没反应，且 ships 一直为空 → 确认时报「布船数据无效」。
        //    （作者实测就是这两个症状。服务端那边也已补成显式 6，这里是第二道防线。）
        if (!Number.isFinite(Number(gameState.maxShips)) || Number(gameState.maxShips) <= 0) {
            console.warn('[placement] new_max_ships 缺失或非法，回退为 6：', data.new_max_ships);
            gameState.maxShips = 6;
        }
        gameState.placedShips = 0;

        // 隐藏所有其他屏幕（唯一来源，见 hideAllScreens）
        hideAllScreens();

        // 直接进入放置战舰界面
        shipPlacementScreen.classList.add('active');
        markMatchStart();          // 同上：这处也是直接加 active，不经 switchScreen
        initBoard(playerBoard, true);

        // 确保界面正确切换（同上：屏不加 hidden）
        startScreen.classList.remove('active');
        customRoomScreen.classList.remove('active');
        matchStatus.classList.add('hidden');

        // 更新可摆放船数显示
        // 注意：shipsPlaced 是 <p> 容器，直接写 textContent 会抹掉内部的
        // <span id="placed-count">，导致之后"已放置 x/y"再也不更新。
        const placedCountEl = document.getElementById('placed-count');
        const totalShips = document.getElementById('total-ships');
        if (totalShips) {
            totalShips.textContent = data.new_max_ships;
        }
        if (placedCountEl) {
            placedCountEl.textContent = 0;
        }

        // 重置已放置船数
        gameState.placedShips = 0;
        // 新的一次部署阶段：清掉上一次的 pending / 已提交标记，并刷新六槽与状态行。
        // ⚠️ 必须在这里（而不是在初始化时一次性）—— 卡牌重摆（绝处逢生、回光返照）
        //    会**再来一次** `reset_gameboard`，那是一个新的部署阶段，
        //    不能被"已经提交过"的标记锁死（A04 明确要求 handle_place_ships
        //    同时服务开局与重摆）。放在 `placedShips = 0` 之后：
        //    updateDeployControls 读的是这一刻的状态。
        newDeployPhase('reset_gameboard');
    });


    // 显示桃园结义选择界面
    function showTaoyuanChoice(result) {
        // 创建选择界面
        const taoyuanChoiceDiv = document.createElement('div');
        taoyuanChoiceDiv.className = 'taoyuan-choice-overlay';
        taoyuanChoiceDiv.style.zIndex = '10000'; // 设置最高优先级
        taoyuanChoiceDiv.innerHTML = `
            <div class="taoyuan-choice-container">
                <div class="taoyuan-choice-header">
                    <h3>桃园结义 - 卡牌选择</h3>
                    <p id="taoyuan-choice-message">${result.message}</p>
                    <div id="taoyuan-selection-result" style="margin-top: 8px; padding: 8px; background-color: rgba(25, 118, 210, 0.1); border-radius: 4px;"></div>
                </div>
                <div class="taoyuan-choice-step">
                    <h4 id="taoyuan-step-title">第一步：选择一张卡牌给自己</h4>
                </div>
                <div class="taoyuan-cards-container"></div>
                <div style="text-align:center;margin-top:10px;">
                    <button id="taoyuan-cancel-btn" class="secondary">取消（把牌放回牌堆）</button>
                </div>
            </div>
        `;
        document.body.appendChild(taoyuanChoiceDiv);

        // 获取卡片容器和选择结果区域
        const cardsContainer = taoyuanChoiceDiv.querySelector('.taoyuan-cards-container');
        const selectionResultDiv = document.getElementById('taoyuan-selection-result');

        // 存储选择状态
        let selectedCards = { caster: null, opponent: null };
        let step = 1; // 1: 选择自己的卡, 2: 选择对方的卡
        let cards = [];

        const renderTaoyuanCards = (response) => {
            if (response.status === 'success' && response.data && response.data.cards) {
                cards = response.data.cards;

                // 显示卡牌
                cards.forEach((card, index) => {
                    const cardElement = document.createElement('div');
                    cardElement.className = 'taoyuan-card-item';
                    cardElement.dataset.index = index;
                    cardElement.innerHTML = `
                        <div class="taoyuan-card-name">${card.name}</div>
                        <div class="taoyuan-card-type">${card.type}·速阶${card.speed}</div>
                        <div class="taoyuan-card-desc">${card.description}</div>
                    `;
                    cardsContainer.appendChild(cardElement);

                    // 添加点击事件
                    cardElement.addEventListener('click', () => {
                        if (step === 1) {
                            // 第一步：选择自己的卡
                            selectedCards.caster = index;

                            // 更新界面
                            cardElement.classList.add('selected');

                            // 更新选择结果提示
                            selectionResultDiv.innerHTML = `
                                <strong>选择结果：</strong><br>
                                已为自己选择卡牌：<span style="color: #1976d2; font-weight: bold;">${card.name}</span><br>
                                该卡牌已加入你的手牌库
                            `;

                            // 检查是否需要第二步
                            if (cards.length > 1) {
                                // 进入第二步
                                step = 2;
                                document.getElementById('taoyuan-step-title').textContent = '第二步：选择一张卡牌给对方';

                                // 禁用已选择的卡
                                cardElement.classList.add('disabled');
                            } else {
                                // 只有一张卡，直接确认
                                selectionResultDiv.innerHTML += '<br><strong style="color: #10b981;">选择完成！</strong>';
                                setTimeout(() => {
                                    confirmTaoyuanChoice(selectedCards, cards);
                                    document.body.removeChild(taoyuanChoiceDiv);
                                }, 1000);
                            }
                        } else if (step === 2) {
                            // 第二步：选择对方的卡
                            if (index !== selectedCards.caster) {
                                selectedCards.opponent = index;

                                // 更新选择结果提示
                                const opponentCard = cards[index];
                                selectionResultDiv.innerHTML = `
                                    <strong>选择结果：</strong><br>
                                    已为自己选择卡牌：<span style="color: #1976d2; font-weight: bold;">${cards[selectedCards.caster].name}</span><br>
                                    已为对方选择卡牌：<span style="color: #f57c00; font-weight: bold;">${opponentCard.name}</span><br>
                                    卡牌已分别加入双方手牌库
                                    <br><strong style="color: #10b981;">选择完成！</strong>
                                `;

                                // 确认选择
                                setTimeout(() => {
                                    confirmTaoyuanChoice(selectedCards, cards);
                                    document.body.removeChild(taoyuanChoiceDiv);
                                }, 1000);
                            }
                        }
                    });
                });
            }
        };
        if (result.cards && Array.isArray(result.cards) && result.cards.length) {
            renderTaoyuanCards({ status: 'success', data: { cards: result.cards } });
        } else {
            gameState.socket.emit('get_magic_temp_data', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            }, renderTaoyuanCards);
        }

        // 取消按钮事件（元素可能不存在时跳过，避免崩溃）
        const cancelBtn = document.getElementById('taoyuan-cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                // 通知服务端放弃选择（把抽出的牌放回牌堆），再关闭浮窗
                if (gameState.socket) {
                    gameState.socket.emit('cancel_magic_selection', {
                        room_id: gameState.roomId, player_id: gameState.playerId,
                    });
                }
                try { document.body.removeChild(taoyuanChoiceDiv); } catch (e) {}
            });
        }
    }

    // 确认桃园结义选择
    function confirmTaoyuanChoice(selectedCards, cards) {
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'taoyuan_choice',
            target_data: {
                caster_choice: selectedCards.caster,
                opponent_choice: selectedCards.opponent || -1
            }
        }, (response) => {
            if (response.status === 'success') {
                showMessage('桃园结义选择完成');
                updateHandUI();
            } else {
                showMessage(`选择失败：${response.message}`, { type: 'error' });
            }
        });
    }

    // 显示灵气复苏船数选择界面
    function showLingqiChoice(result) {
        // 创建选择界面，使用与桃园结义相同的UI样式
        const lingqiChoiceDiv = document.createElement('div');
        lingqiChoiceDiv.className = 'taoyuan-choice-overlay';
        lingqiChoiceDiv.style.zIndex = '10000'; // 设置最高优先级
        lingqiChoiceDiv.innerHTML = `
            <div class="taoyuan-choice-container">
                <div class="taoyuan-choice-header">
                    <h3>灵气复苏 - 船数选择</h3>
                    <p id="taoyuan-choice-message">灵气复苏船数选择 选择后双方的船数都会变为你选择的数目</p>
                </div>
                <div class="taoyuan-cards-container" style="display: flex; flex-wrap: wrap; gap: 12px; justify-content: center;"></div>
            </div>
        `;
        document.body.appendChild(lingqiChoiceDiv);

        // 获取卡片容器
        const cardsContainer = lingqiChoiceDiv.querySelector('.taoyuan-cards-container');

        // 获取最大船数
        let maxShips = result.max_ships;

        // 如果maxShips未在result中返回，请求服务器获取
        if (!maxShips) {
            gameState.socket.emit('get_magic_temp_data', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            }, (response) => {
                if (response.status === 'success' && response.data && response.data.max_ships) {
                    maxShips = response.data.max_ships;
                    renderShipButtons(maxShips);
                }
            });
        } else {
            renderShipButtons(maxShips);
        }

        // 渲染船数按钮
        function renderShipButtons(maxShips) {
            cardsContainer.innerHTML = '';

            // 创建1到maxShips的按钮，使用与桃园结义卡牌相同的样式
            for (let i = 1; i <= maxShips; i++) {
                const buttonElement = document.createElement('div');
                buttonElement.className = 'taoyuan-card-item';
                buttonElement.dataset.shipCount = i;
                buttonElement.innerHTML = `
                    <div class="taoyuan-card-name" style="text-align: center;">${i}艘</div>
                    <div class="taoyuan-card-type" style="text-align: center;">选择此船数</div>
                    <div class="taoyuan-card-desc" style="text-align: center;">双方船数将调整为${i}艘</div>
                `;

                // 添加点击事件
                buttonElement.addEventListener('click', () => {
                    const selectedShipCount = parseInt(buttonElement.dataset.shipCount);
                    confirmLingqiChoice(selectedShipCount);
                    document.body.removeChild(lingqiChoiceDiv);
                });

                cardsContainer.appendChild(buttonElement);
            }
        }
    }

    // 确认灵气复苏选择
    function confirmLingqiChoice(targetShips) {
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'lingqi_choice',
            target_data: {
                target_ships: targetShips
            }
        }, (response) => {
            if (response.status === 'success') {
                showMessage(response.message);
            } else {
                showMessage(`选择失败：${response.message}`, { type: 'error' });
            }
        });
    }

    function showBuryChoice(result) {
        // 创建选择界面，使用与桃园结义相同的UI样式
        const buryChoiceDiv = document.createElement('div');
        buryChoiceDiv.className = 'taoyuan-choice-overlay';
        buryChoiceDiv.style.zIndex = '10000'; // 设置最高优先级
        buryChoiceDiv.innerHTML = `
            <div class="taoyuan-choice-container">
                <div class="taoyuan-choice-header">
                    <h3>明智埋葬 - 卡牌选择</h3>
                    <p id="taoyuan-choice-message">${result.message}</p>
                </div>
                <div class="taoyuan-cards-container"></div>
            </div>
        `;
        document.body.appendChild(buryChoiceDiv);

        // 获取卡片容器
        const cardsContainer = buryChoiceDiv.querySelector('.taoyuan-cards-container');

        // 存储选择状态
        let selectedCard = null;
        let cards = [];

        const renderBuryCards = (response) => {
            if (!response || response.status !== 'success' || !response.data) return;
            // 主链路（chain_resolved 结果）用 data.cards；
            // 兜底查询 get_magic_temp_data 时服务端返回的是 data.candidates（纯数据）
            const list = response.data.cards || response.data.candidates;
            if (Array.isArray(list) && list.length) {
                cards = list;

                // 显示卡牌（来源可能是牌堆或对方手牌）
                cards.forEach((card, index) => {
                    const cardElement = document.createElement('div');
                    cardElement.className = 'taoyuan-card-item';
                    cardElement.dataset.index = index;
                    cardElement.dataset.source = card.source || 'deck';

                    const sourceLabel = (card.source === 'opponent_hand') ? '对方手牌' : '牌堆';
                    cardElement.innerHTML = `
                        <div class="taoyuan-card-name">${card.name}</div>
                        <div class="taoyuan-card-type">${card.type}·速阶${card.speed} · ${sourceLabel}</div>
                        <div class="taoyuan-card-desc">${card.description}</div>
                    `;
                    cardsContainer.appendChild(cardElement);

                    // 添加点击事件
                    cardElement.addEventListener('click', () => {
                        // 移除其他卡牌的选中状态
                        cardsContainer.querySelectorAll('.taoyuan-card-item').forEach(item => {
                            item.classList.remove('selected');
                        });

                        // 选中当前卡牌
                        cardElement.classList.add('selected');

                        // 确认选择（带上来源 + 该卡在来源列表内的下标）
                        confirmBuryChoice(index, card.source || 'deck', card.index);
                        document.body.removeChild(buryChoiceDiv);
                    });
                });
            }
        };
        if (result.cards && Array.isArray(result.cards) && result.cards.length) {
            renderBuryCards({ status: 'success', data: { cards: result.cards } });
        } else {
            gameState.socket.emit('get_magic_temp_data', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            }, renderBuryCards);
        }
    }

    // 确认明智埋葬选择
    // cardIndex 是候选总表（牌堆在前、对方手牌在后）里的扁平下标，
    // sourceIndex 是该卡在自己来源列表内的下标 —— 服务端优先用后者精确定位。
    function confirmBuryChoice(cardIndex, source, sourceIndex) {
        const targetData = {
            card_index: cardIndex,
            source: source || 'deck'
        };
        if (typeof sourceIndex === 'number') {
            targetData.source_index = sourceIndex;
        }
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'bury_choice',
            target_data: targetData
        }, (response) => {
            if (response.status === 'success') {
                showMessage(response.message);
            } else {
                showMessage(`选择失败：${response.message}`, { type: 'error' });
            }
        });
    }

    // 亡羊补牢：从弃牌区最新 n 张里挑 1 张加入手牌
    // 候选牌的顺序由服务端给出（最新那张在末尾），UI 顺序就是候选数组的顺序。
    function showWangYangChoice(result) {
        const overlay = document.createElement('div');
        overlay.className = 'taoyuan-choice-overlay';
        overlay.style.zIndex = '10000';
        overlay.innerHTML = `
            <div class="taoyuan-choice-container">
                <div class="taoyuan-choice-header">
                    <h3>亡羊补牢 - 从弃牌区选 1 张</h3>
                    <p id="taoyuan-choice-message">${result.message || ''}</p>
                    <div id="taoyuan-selection-result" style="margin-top: 8px; padding: 8px; background-color: rgba(25, 118, 210, 0.1); border-radius: 4px;"></div>
                </div>
                <div class="taoyuan-cards-container"></div>
                <div style="text-align:center;margin-top:10px;">
                    <button id="wangyang-cancel-btn" class="secondary">取消（弃牌区还原）</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const cardsContainer = overlay.querySelector('.taoyuan-cards-container');
        const selectionResultDiv = overlay.querySelector('#taoyuan-selection-result');
        let cards = [];

        const renderWangYangCards = (response) => {
            if (!response || response.status !== 'success' || !response.data) return;
            const list = response.data.cards;
            if (!Array.isArray(list) || !list.length) return;
            cards = list;

            cards.forEach((card, index) => {
                const cardElement = document.createElement('div');
                cardElement.className = 'taoyuan-card-item';
                cardElement.dataset.index = index;
                cardElement.innerHTML = `
                    <div class="taoyuan-card-name">${card.name}</div>
                    <div class="taoyuan-card-type">${card.type}·速阶${card.speed}</div>
                    <div class="taoyuan-card-desc">${card.description}</div>
                `;
                cardsContainer.appendChild(cardElement);

                cardElement.addEventListener('click', () => {
                    cardsContainer.querySelectorAll('.taoyuan-card-item').forEach(item => {
                        item.classList.remove('selected');
                    });
                    cardElement.classList.add('selected');
                    selectionResultDiv.innerHTML = `
                        <strong>已选择：</strong>
                        <span style="color: #1976d2; font-weight: bold;">${card.name}</span>
                        <br>该卡将加入你的手牌，其余回归弃牌堆
                    `;
                    setTimeout(() => {
                        confirmWangYangChoice(index);
                        try { document.body.removeChild(overlay); } catch (e) {}
                    }, 600);
                });
            });
        };

        if (result.cards && Array.isArray(result.cards) && result.cards.length) {
            renderWangYangCards({ status: 'success', data: { cards: result.cards } });
        } else {
            gameState.socket.emit('get_magic_temp_data', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            }, renderWangYangCards);
        }

        const cancelBtn = overlay.querySelector('#wangyang-cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                if (gameState.socket) {
                    gameState.socket.emit('cancel_magic_selection', {
                        room_id: gameState.roomId, player_id: gameState.playerId,
                    });
                }
                try { document.body.removeChild(overlay); } catch (e) {}
            });
        }
    }

    function confirmWangYangChoice(chosenIndex) {
        gameState.socket.emit('confirm_magic_target', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            temp_data_id: 'wangyang_choice',
            target_data: { chosen_index: chosenIndex }
        }, (response) => {
            if (response.status === 'success') {
                showMessage(response.message);
                updateHandUI();
            } else {
                showMessage(`选择失败：${response.message}`, { type: 'error' });
            }
        });
    }

    // 说明：服务端从来没有 lobby_update / lobby_joined / lobby_left / match_found
    // 这些事件（历史遗留空壳，已删除）。大厅按钮状态改由上面真实的
    // match_queued / match_canceled 处理器同步。

    // 新增：监听手牌更新事件
    //
    // ⚠️ 这个 handler 以前直接 `gameState.hand = data.hand;`，没有任何校验。
    // 只要有一次 payload 不带 hand（结构不符 / 前端是旧缓存版本 / 某条新路径
    // 忘了带字段），gameState.hand 就变成 undefined —— 而 updateHandUI 是在
    // 清空容器之后才遍历 hand 的，于是整块手牌区域变成空白，并且**此后每一次
    // 刷新手牌都会抛异常，永远保持空白，只有刷新页面才能恢复**。
    // 这正是作者反馈的「打完一张，剩下的手牌莫名消失，刷新又回来」。
    // 服务端是手牌的唯一权威：结构不对就忽略它并要求重同步，绝不拿它覆盖。
    socket.on('hand_updated', (data) => {
        applyHandPayload(data, 'hand_updated');
    });

    // 神威！：扣掉 / 恢复 3x3 区域
    socket.on('shenwei_hole', (data) => {
        gameState.shenweiHoles = (gameState.shenweiHoles || []).filter(
            h => !(h.player === data.player && h.x1 === data.area.x1 && h.y1 === data.area.y1));
        gameState.shenweiHoles.push(Object.assign({ player: data.player }, data.area));
        applyShenweiHoles();
        showMessage(data.player === gameState.playerId
            ? '你的棋盘被神威！扣掉了一块 3x3 区域'
            : '对方棋盘被神威！扣掉了一块 3x3 区域');
    });
    socket.on('shenwei_hole_restored', (data) => {
        gameState.shenweiHoles = (gameState.shenweiHoles || []).filter(h => h.player !== data.player);
        applyShenweiHoles();
        showMessage('神威！区域已恢复，战舰回归原位');
    });

    // 恶魔契约：服务端要求选择一艘自己的战舰牺牲（在自己棋盘上点选，无额外弹窗）
    socket.on('sacrifice_request', (data) => {
        showSacrificePrompt(data);
    });

    // ⚠️ 2026-09-21：服务端撤回某个等待点船的效果（通常是该效果整体作废，
    //    例如恶魔契约场地被顶替）。前端必须撤回 sacrifice 弹窗，否则
    //    `selectingOnBoard` 一直挂着，后续 createBoardAreaPicker 等点选器
    //    会被"请先完成恶魔契约的点选"提示反复挡住。
    socket.on('sacrifice_cancelled', (data) => {
        const reason = (data && data.reason) || '';
        // 当前弹窗的 reason 跟被撤回的 reason 不一致就不动它（可能是别的效果在等）
        const cur = gameState.pendingSacrifice;
        if (cur && reason && cur.reason !== reason) return;
        // ★ 必须先调 selectionCleanup（它会 removeEventListener 把 onClick 真正解绑），
        //    再调 clearSacrificeSelection。直接 clearSacrificeSelection 只把
        //    selectionCleanup 置空而不调用它 → showSacrificePrompt 绑的那个 onClick
        //    监听器会一直挂在 gamePlayerBoard 上，下次仁王之盾 / 别的选区弹窗
        //    开起来时它就跟新 handler 同时活着，点船格会双触发：
        //    一边走 bindRenwangBoardClick 切 picked，一边走 onClick emit confirm_sacrifice
        //    → 服务端走 _do_demon_contract_sacrifice → 船被错误牺牲
        //    （作者报的"第一次点击直接让自己的船牺牲了"）。
        if (typeof gameState.selectionCleanup === 'function') {
            try { gameState.selectionCleanup(); } catch (_) { }
        }
        clearSacrificeSelection();
        // 给玩家一句解释，避免"弹窗突然消失"看起来像 bug
        const label = SACRIFICE_LABELS[reason] || '一个等待点选的效果';
        showMessage(`「${label}」已不再生效，点选已撤回`, { type: 'info' });
        // 队列里可能还有别的低优先级待选 —— 让服务端继续 dispatch 下一项
        // （这里不主动重新打开下一条 prompt：服务端 _clear_ship_picks_by_reason
        //    没有自动 _dispatch_ship_pick，因为顶替场地的常见场景里那个待选
        //    本来就是不该再存在的。如果有别的待选，下个相关动作会自己触发）
    });

    // 某艘船因效果被牺牲 —— 公开事件，双方都能看到这艘船沉没
    socket.on('ship_sacrificed', (data) => {
        const positions = (data && data.positions) || [];
        if (!positions.length) return;
        const mine = data.player === gameState.playerId;
        if (!mine) clearOpponentShieldedShips(positions);

        // ⚠️ 绝处逢生的自牺牲【不画叉】。
        // 它的六个格子是"唯一一艘新船可能落点"，对方必须能打；画成红叉
        // （玩家眼里等于"已打过、别再点"）会让人以为这几格打不了（作者实测反馈）。
        // 改成由 last_stand_cells 事件下发候选格，前端画成高亮。
        if (data.reason === 'last_stand') {
            if (mine) {
                // 自己的船全没了：本地棋盘记录一并清掉
                const keys = new Set(positions.map(p => p.x + ',' + p.y));
                gameState.ships = (gameState.ships || [])
                    .map(ship => Object.assign({}, ship, {
                        positions: (ship.positions || []).filter(p => !keys.has(p.x + ',' + p.y))
                    }))
                    .filter(ship => (ship.positions || []).length > 0);
            }
            if (typeof initGameBoards === 'function') initGameBoards();
            return;   // 文案交给 last_stand_cells 那条统一播报
        }

        const sink = mine ? gameState.sacrificedSelf : gameState.sacrificedOpponent;

        positions.forEach(p => sink.push({ x: p.x, y: p.y }));

        if (mine) {
            // 自己的船死了：从本地棋盘记录里移除这艘船
            const keys = new Set(positions.map(p => p.x + ',' + p.y));
            gameState.ships = (gameState.ships || [])
                .map(ship => Object.assign({}, ship, {
                    positions: (ship.positions || []).filter(p => !keys.has(p.x + ',' + p.y))
                }))
                .filter(ship => (ship.positions || []).length > 0);
        }

        if (typeof initGameBoards === 'function') initGameBoards();
        // 卡片名按来源显示：恶魔契约 / 神之宣告 / 命运骰子 都走这条公开事件
        const reasonText = ({divine_decree: '神之宣告', dice_sacrifice: '命运骰子'})[data.reason] || '恶魔契约';
        showMessage(mine ? `${reasonText}：你牺牲了一艘战舰` : `${reasonText}：对方牺牲了一艘战舰`,
                    { type: 'warning' });
    });

    // 绝处逢生：牺牲前原本有战舰的格子（唯一一艘新船必在其中）。
    // 双方都要高亮 —— 对方据此知道该往哪儿打，而且这些格子照样能点。
    socket.on('last_stand_cells', (data) => {
        const cells = (data && Array.isArray(data.cells)) ? data.cells : [];
        gameState.lastStandCells = cells.filter(c => c && typeof c.x === 'number' && typeof c.y === 'number');
        // 归属：这批格子是【谁棋盘上的】。没有它就只能瞎猜棋盘，实测会画到对手棋盘上。
        gameState.lastStandOwner = (data && data.owner) || null;
        if (typeof initGameBoards === 'function') initGameBoards();
        if (gameState.lastStandCells.length) {
            const mine = gameState.playerId && gameState.lastStandOwner === gameState.playerId;
            showMessage(mine
                ? '绝处逢生：唯一一艘会放在高亮的格子之一（点一格放置）'
                : '绝处逢生：对方牺牲了全部战舰，唯一一艘会在高亮的格子之一（这些格子可以打）',
                { type: 'warning' });
        }
    });

    // 冻结的 3×3 区域：双方都要看到（施法方原先什么都收不到，过一会儿就忘了冻的是哪片）
    socket.on('frozen_area', (data) => {
        gameState.frozenArea = (data && !data.cleared) ? data : null;
        if (typeof initGameBoards === 'function') initGameBoards();
    });

    // 命运骰子：摇骰子动画 + 结果播报（双方都能看到）
    // 无忧梦呓（判定拼点）**复用同一个事件**：payload 多带 `opponent_roll`（对方的点数）
    // 与 `card`（卡名），前端据此把两颗骰子一起报出来 —— 不新增事件、不新增 CSS 类。
    socket.on('dice_rolled', (data) => {
        showDiceRollAnimation(data && data.roll, data && data.effect_text,
                              data && data.caster, data && data.opponent_roll,
                              data && data.card);
    });

    // 命运骰子摇到3 / 无忧梦呓拼点判负：要求我弃一张手牌
    socket.on('dice_discard_request', (data) => {
        showDiceDiscardPrompt(data && data.message);
    });

    // 双方都弃完：关掉选牌浮层（如果还开着）
    socket.on('dice_discard_complete', () => {
        hideDiceDiscardPrompt();
    });

    // 服务端统一推送的局内日志
    socket.on('game_log', (entry) => {
        renderServerLog(entry);
    });

    // 局内快捷语（第 4 批）：只写日志 + 轻提示，不动棋盘 / 手牌 / 阶段 / 连锁
    socket.on('quick_chat', (payload) => {
        handleQuickChatReceived(payload);
    });

    // 日志里的卡名支持悬停查看 / 点击详情（幂等，只绑一次）
    initGameLogCardRefs();

    // 增援 / 复活：服务端请求选择部署位置
    socket.on('placement_request', (data) => {
        showPlacementPrompt(data);
    });
    socket.on('placement_done', (data) => {
        const p = document.getElementById('placement-prompt');
        if (p) p.remove();
        const doneMsg = (data && data.kind === 'lanyu') ? '滥竽充数·补充部署完成（大回合结束时收回）'
            : (data && data.kind === 'revive') ? '复活部署完成'
            : '增援部署完成';
        showMessage(doneMsg);
        if (typeof initGameBoards === 'function') initGameBoards();
    });
    // 自己棋盘上的战舰变化（复活/增援后同步显示）
    socket.on('player_ships_updated', (data) => {
        if (data && Array.isArray(data.ships)) {
            gameState.ships = data.ships;
            if (typeof initGameBoards === 'function') initGameBoards();
        }
    });

    // 盾牌挡下一击：必须明确提示，否则双方只看到一次普通"命中"，
    // 防守方会以为自己的船挨了一炮（其实毫发无伤）。
    socket.on('shield_absorbed', (data) => {
        const mine = data && data.player === gameState.playerId;
        if (!mine && data && Array.isArray(data.positions)) {
            clearOpponentShieldedShips(data.positions);
            if (typeof initGameBoards === 'function') initGameBoards();
        }
        showMessage(mine ? '你的战舰用护盾挡下了这次攻击'
                         : '对方的战舰用护盾挡下了这次攻击',
                    { type: 'info' });
    });

    // 新增：监听战舰数更新事件
    socket.on('ships_updated', (data) => {
        // 更新双方剩余战舰数
        yourShips.textContent = data.player_remaining_ships;
        opponentShips.textContent = data.opponent_remaining_ships;
    });

    // 「谁打过哪些格子」的全量重发：复活 / 增援 / 重新部署把格子从服务端
    // 攻击历史里清掉之后，必须用它刷新本地缓存，否则那个格子会一直画着 ✕
    // 并且【没有绑定点击监听】（initGameBoards 只在 !alreadyAttacked 时才绑），
    // 对手就永远点不动它。
    socket.on('board_attacks_updated', (data) => {
        const norm = (list) => (Array.isArray(list) ? list : []).map((a) => ({
            x: a.x, y: a.y, hit: !!a.hit, shipSunk: !!a.ship_sunk,
        }));
        if (data && Array.isArray(data.my_attacks)) {
            gameState.myAttacks = norm(data.my_attacks);
        }
        if (data && Array.isArray(data.opponent_attacks)) {
            gameState.opponentAttacks = norm(data.opponent_attacks);
        }
        initGameBoards();
    });

    // 当前生效效果角标：完全由服务端广播驱动（服务端是唯一真相）。
    // 服务端按收件人视角分别下发 self / opponent —— 双方都能看到对方挂着什么。
    socket.on('active_effects', (data) => {
        renderActiveEffects(data || { self: [], opponent: [] });
    });

    // 服务器推送的通用消息
    socket.on('message', (data) => {
        if (data && data.text) showMessage(data.text);
    });

    // 显示服务端通用消息 / 错误（此前未监听导致提示不可见）
    socket.on('game_message', (data) => {
        if (data && (data.message || data.text)) showMessage(data.message || data.text);
    });
    socket.on('error', (data) => {
        const msg = (data && (data.message || data.msg || data)) || '发生错误';
        // 排位排队被服务端拒绝（未登录 → 「排位模式需要先登录」）时必须**恢复按钮状态**，
        // 否则按一次就永远卡在「正在寻找排位对手…」。
        if (rankedQueuePending) resetRankedQueueUI();
        showMessage(typeof msg === 'string' ? msg : JSON.stringify(msg));
    });

    // 对手桃园结义结算等待提示
    socket.on('taoyuan_waiting', (data) => {
        // 创建等待提示界面
        const waitingDiv = document.createElement('div');
        waitingDiv.className = 'taoyuan-waiting-overlay';
        waitingDiv.style.zIndex = '10000';
        waitingDiv.style.position = 'fixed';
        waitingDiv.style.top = '0';
        waitingDiv.style.left = '0';
        waitingDiv.style.width = '100%';
        waitingDiv.style.height = '100%';
        waitingDiv.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
        waitingDiv.style.display = 'flex';
        waitingDiv.style.alignItems = 'center';
        waitingDiv.style.justifyContent = 'center';
        waitingDiv.style.color = 'white';
        waitingDiv.innerHTML = `
            <div style="background: rgba(25, 118, 210, 0.9); padding: 20px; border-radius: 10px; text-align: center;">
                <h3>${data.message}</h3>
            </div>
        `;
        document.body.appendChild(waitingDiv);
    });

    // 桃园结义结算完成提示
    socket.on('taoyuan_complete', (data) => {
        // 移除等待提示（取消时服务端也会发这个事件，见 handle_cancel_magic_selection）
        dismissTaoyuanWaitingOverlay();
        showMessage(data.message);
    });

    // 亡羊补牢结算完成提示（仅施法者选完/取消后通知对手）
    socket.on('wangyang_complete', (data) => {
        showMessage(data.message);
    });

    // 守株待兔：陷阱标记已打上（施法者自己 + 对方都能看到，所以 room 广播）
    socket.on('trap_set', (data) => {
        const isMine = data && data.player === gameState.playerId;
        const msg = isMine
            ? '已为一艘战舰设置陷阱（本回合该船被击沉时对方需牺牲两艘）'
            : '对方为一艘战舰设置了陷阱';
        showMessage(msg, { type: isMine ? 'success' : 'warning' });
    });

    // 守株待兔：陷阱被踩中
    socket.on('trap_triggered', (data) => {
        showMessage((data && data.message) || '陷阱触发', { type: 'warning' });
    });

    // 守株待兔：陷阱过期（新大回合开始）
    socket.on('trap_expired', (data) => {
        if (data && data.player === gameState.playerId) {
            showMessage('你的陷阱已过期', { type: 'info' });
        } else if (data && data.player) {
            showMessage('对方的陷阱已过期', { type: 'info' });
        }
    });

    // 卧薪尝胆：双方只知道加盾数量；船位仍只在施法者自己的棋盘同步。
    socket.on('shields_added', (data) => {
        const isMine = data && data.player === gameState.playerId;
        const cnt = (data && data.count) || 0;
        if (!isMine && data) {
            // 不读取 positions/ships：旧版本曾在这里把对方所有活船坐标画到
            // 对手棋盘，卧薪尝胆因此变成了主动泄露舰队位置的卡。
        }
        const msg = isMine
            ? `已为${cnt}艘战舰添加护盾`
            : `对方为${cnt}艘战舰添加了护盾`;
        showMessage(msg, { type: isMine ? 'success' : 'warning' });
    });

    // 滥竽充数：大回合结束时强制收回临时船（不显示沉没）
    socket.on('lanyu_recalled', (data) => {
        const isMine = data && data.player === gameState.playerId;
        const cnt = (data && data.count) || 0;
        const msg = isMine
            ? `滥竽充数：${cnt}艘临时战舰已收回`
            : `对方的滥竽充数临时战舰已收回${cnt}艘`;
        showMessage(msg, { type: 'info' });
        if (typeof initGameBoards === 'function') initGameBoards();
    });

    // 服务器返回的被揭示的位置（仅对触发方发送）
    socket.on('revealed_positions', (data) => {
        if (!data || !Array.isArray(data.positions)) return;
        // kind：'heal' = 疗愈原地复活（对方该知道船又回到这一格了）；
        // 缺省 = 旧的通用显形（探测雷达 / 克苏鲁之眼等），行为不变。
        const kind = data.kind || null;
        data.positions.forEach(pos => {
            let entry = gameState.revealedCells.find(c => c.x === pos.x && c.y === pos.y);
            if (!entry) {
                entry = { x: pos.x, y: pos.y, kind: kind };
                gameState.revealedCells.push(entry);
            } else if (kind && !entry.kind) {
                entry.kind = kind;          // 后到的更具体来源，覆盖"通用显形"
            }
            const cell = opponentBoard.querySelector(`.cell[data-x='${pos.x}'][data-y='${pos.y}']`);
            if (cell) {
                cell.classList.add('revealed');
                if (entry.kind === 'heal') {
                    cell.classList.add('revealed-heal');
                    cell.title = '疗愈：这艘战舰原地复活，仍在这一格';
                }
            }
        });
    });

}
