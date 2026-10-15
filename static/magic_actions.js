/* Magic-card play, target confirmation, and chain-response routing. */

function playMagicCard(index) {
    console.log('playMagicCard called with index:', index);
    const card = gameState.hand[index];
    if (!card) return;
    if (freezeAlert()) { clearCardSelection(); return; }

    // 检查卡牌是否可以在当前阶段使用
    if (!canPlayCard(card)) {
        // 出牌被拒：必须清掉选中态，否则下一次单击会被当成
        // 「同一张已选中的卡」立刻重试 —— 玩家看到提示弹两遍。
        clearCardSelection();
        if (isLastStandActive()) {
            // 绝处逢生生效中，跟「阶段 / 回合」毫无关系。
            // 旧实现会一路掉到最后一个 else，弹出「当前阶段battle不允许使用
            // 速阶1的魔法卡」—— 阶段明明是对的，玩家据此以为游戏坏了。
            showAlert(`无法使用${card.name}：绝处逢生生效中，本回合你的其余魔法卡全部无效`);
        } else if (END_PHASE_PLAYABLE_CARDS.indexOf(card.name) >= 0) {
            // 这类卡有专属的条件提示，别让玩家看到「速阶2」这种内部术语
            const reasons = [];
            if (!isFirstPlayer()) reasons.push('你这一局是后手');
            if (gameState.currentAttacker !== gameState.playerId) reasons.push('不是你的回合');
            if (gameState.currentPhase !== 'end') reasons.push('不是结束阶段');
            showAlert(`${card.name}只能在自己先手回合的结束阶段发动（${reasons.join('；') || '条件不满足'}）`);
        } else if (gameState.currentAttacker !== gameState.playerId) {
            // 另一种同样常见的原因：不是你的回合。旧文案一律甩锅给「阶段」，
            // 玩家在准备阶段拿着速阶2的卡会看到「当前阶段preparation不允许使用速阶2」，
            // 完全是误导（服务端本来就允许准备阶段用速阶2）。
            showAlert(`无法使用${card.name}：现在不是你的回合`);
        } else {
            const phaseName = gameState.currentPhase || '未开始';
            showAlert(`无法使用${card.name}：当前阶段${phaseName}不允许使用速阶${card.speed}的魔法卡`);
        }
        return;
    }

    // 特殊限制：饮血 / 溅射 / 雷达子弹 都需要「自己上一发攻击」满足各自条件。
    // 必须在这里拦下 —— 否则牌会被服务端扣掉，结算时才告诉你条件不满足，
    // 而那时牌已经进了弃牌堆、不会退还（玩家实测过）。
    const afterHitReason = afterHitBlockReason(card);
    if (afterHitReason) {
        clearCardSelection();
        showAlert(`无法使用${card.name}：${afterHitReason}`);
        return;
    }
    if (gameState.fieldMagic === "禁忌果实") {
        if (!(card.name === "失灵！" || card.type === "场地")) {
            clearCardSelection();
            showAlert(`无法使用${card.name}：场地魔法“禁忌果实”生效，非场地及失灵类魔法卡无法使用`);
            return;
        }
    }

    // 神之宣告：卡面顺序是「先选定自己两艘船死亡，再选择要发动的效果」。
    // 两步都走完才算出牌 —— 第一步由 needsTargetSelection 的 own_ships 收集，
    // 第二步在 confirmMagicTarget 里接着问（见 promptDivineDecreeChoice）。

    // 检查是否需要目标选择
    if (needsTargetSelection(card.name)) {
        showMagicTargetSelection(card, index);
    } else {
        // 不需要目标，直接发送
        sendMagicCard(index, []);
    }
}

// 添加发送魔法卡的辅助函数
function sendMagicCard(index, targets) {
    const card = gameState.hand[index];
    if (!card) return;
    playSfx('play_card');

    // ⚠️ 先记下这张牌的【身份】和出牌那一刻它在手牌里的位置。
    // 服务器响应是异步的，回来之前可能已经收到 hand_updated
    // （对方打无中生有 / 自己因效果摸牌 / 连锁里别人改手牌…），
    // 那时 gameState.hand 已经是新数组，旧下标指向的完全是另一张牌。
    // 实测（tools/repro_splice_index.mjs）：手牌 ["饮血","冻结"] 打出饮血，
    // 期间摸到一张「八方来财」插到 0 号位，回调里 splice(0,1) 删掉的是
    // 【八方来财】—— 打出去的饮血还留在手上，玩家看到的是"手牌被莫名吞掉"。
    const sentKey = cardSelectionKey(card);
    const sentIndex = index;

    console.log('发送魔法卡:', card.name);
    gameState.socket.emit('use_magic_card', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        card: card,
        targets: targets
    }, (response) => {
        // 只有在服务器确认成功后才更新本地状态
        if (response && response.status === 'success') {
            console.log('魔法卡使用成功');
            // 从手牌中移除：只按身份找，找不到就什么都不删。
            //
            // ⚠️ 这里以前有一个"找不到就按下标兜底"的分支：
            //     removeAt = (gameState.hand.length === sentIndex + 1) ? sentIndex : -1
            // 它是**永远错的**：能走到这个分支，就说明打出的那张牌已经不在手牌里了
            // （手牌里没有任何一张的 name+speed 和它相同），也就是说服务端早已推过
            // 新手牌；这时再按旧下标删一张，删掉的必然是【别的牌】。
            //
            // 实测（tools/hand_play_check.mjs，真实浏览器 + 真服务端）：
            //   手牌 ["五险一金","看破！"]，点第 0 张打出。
            //   handle_use_magic_card 扣牌后会走 _advance_chain_window，
            //   对方手上没有速阶3 → 它【在同一个请求里同步 resolve_chain】，
            //   而 resolve_chain 收尾会向双方各推一次 hand_updated（此时只剩 "看破！"）。
            //   所以真实时序是 "hand_updated(1 张)" 先到、ack 后到（工具里有断言守这条）。
            //   ack 里按身份找不到 → 兜底条件 1 === 0+1 成立 → 把 "看破！" 删掉
            //   → 界面手牌变成 0 张，而服务端还有 1 张。玩家看到的就是
            //   「打完一张，剩下的手牌莫名其妙全没了，刷新页面又回来」。
            //
            // 同名同速阶的卡（如 3 张「失灵！」）会有多张命中，这时仍用
            // "出牌时它在第几位"来消歧 —— 取第 sentIndex 个命中项。
            const hits = [];
            for (let i = 0; i < gameState.hand.length; i++) {
                if (cardSelectionKey(gameState.hand[i]) === sentKey) hits.push(i);
            }
            if (hits.length) {
                gameState.hand.splice(hits[Math.min(sentIndex, hits.length - 1)], 1);
            } else {
                // 牌已经不在手牌里了 —— 服务端才是权威，等它的 hand_updated，
                // 绝不按下标猜着删一张。
                console.log('打出的牌已不在本地手牌中（服务端已同步），不本地删除');
            }
            // 添加到弃牌堆
            gameState.discardPile.push(card);
            renderArenaRail();   // 三区操作列的「弃牌堆」计数（第 37 节）
            // 手牌少了一张，旧下标会落到别的牌上 —— 先清选中态再刷新
            gameState.selectedCardIndex = -1;
            gameState.selectedCardKey = null;
            // 更新UI
            updateHandUI();
        } else {
            // 出牌失败同样要清选中态：否则这张卡还挂着「已选中」，
            // 玩家下一次单击就会立刻重试，提示连弹两遍。
            clearCardSelection();
            console.error('魔法卡使用失败:', response && response.message);
            showAlert(`使用魔法卡失败：${(response && response.message) || '未知错误'}`);
        }
    });
}

// 神之宣告：第二步 —— 两艘要牺牲的船选完之后，选择要触发的效果
// （1=摧毁对方一艘战舰，2=跳过对方本回合）。
// ctx：第一步入口处抓好的上下文 { card, cardIndex, chainPending }。
//      card 允许显式传入，是因为连锁响应窗口里打出的卡未必在手牌同下标。
// basePayload：第一步（own_ships）收集到的 selected_cells，确认后与效果一起提交。
function promptDivineDecreeChoice(ctx, basePayload) {
    const context = ctx || {};
    const card = context.card || gameState.hand[context.cardIndex];
    if (!card) return;
    const picked = basePayload || null;

    const overlay = document.createElement('div');
    overlay.className = 'taoyuan-choice-overlay';
    overlay.style.zIndex = '10000';
    overlay.innerHTML = `
        <div class="taoyuan-choice-container">
            <div class="taoyuan-choice-header">
                <h3>神之宣告</h3>
                <p>已选定牺牲的两艘战舰，请选择要触发的效果：</p>
            </div>
            <div class="divine-decree-options" style="display:flex;flex-direction:column;gap:10px;padding:12px 0;">
                <button class="phase-btn" data-choice="1">摧毁对方一艘战舰</button>
                <button class="phase-btn" data-choice="2">跳过对方本回合所有阶段</button>
                <button class="phase-btn" data-choice="0" style="opacity:.7;">取消</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    overlay.querySelectorAll('button[data-choice]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const choice = parseInt(btn.dataset.choice, 10);
            document.body.removeChild(overlay);
            if (choice === 0) {
                // 取消：卡牌不打出，清掉选区状态
                gameState.pendingEffectChoice = null;
                gameState.currentMagicCard = null;
                gameState.currentCardIndex = null;
                return;
            }

            if (picked) {
                // 两步都齐了：并到一起提交（上下文沿用第一步的，state 已被清理也不怕）
                gameState.pendingEffectChoice = null;
                _dispatchMagicTarget(
                    Object.assign({}, picked, { effect_choice: choice }), context);
                return;
            }

            // 兜底：没有第一步的结果时，退回「先点选两艘自己的船」。
            // 服务端收不到 selected_cells 会随机补两艘，玩家就没有选择权了。
            gameState.pendingEffectChoice = choice;
            gameState.currentMagicCard = card;
            gameState.currentCardIndex = context.cardIndex;
            showMagicTargetSelection(card, context.cardIndex);
        });
    });
}

// 修改目标选择后的确认函数
function confirmMagicTarget(targetData) {
    // 优先权询问里选好目标的情况：pendingPriorityCard 已记下要打的卡，
    // currentMagicCard 也在 showPriorityPrompt 里同步设过，两者取其一即可。
    if (!gameState.currentMagicCard && !gameState.pendingPriorityCard) return;
    if (gameState.currentCardIndex === null && !gameState.pendingPriorityCard) return;

    // ⚠️ 先把「提交这张卡所需的全部上下文」抓进局部变量。
    // showMagicTargetSelection 的「确认」监听器在 confirmMagicTarget 返回之后
    // 会把 currentMagicCard / currentCardIndex / pendingChainCard / pendingEffectChoice
    // 统统清空；而神之宣告是两段式（先选船、再选效果），等效果选完再去读 gameState
    // 只会读到 null —— 轻则卡牌索引丢失打不出去，重则把连锁响应误发成普通出牌。
    const ctx = {
        card: gameState.currentMagicCard,
        cardIndex: gameState.currentCardIndex,
        chainPending: gameState.pendingChainCard,
        priorityPending: gameState.pendingPriorityCard,
    };

    // 兼容多种 targetData 格式：
    // - { target_area: {x1,y1,x2,y2} } （来自对手真实棋盘）
    // - { selected_cells: [ {x,y}, ... ] } （来自小面板或选舰）
    // - { target_line: {...} } （行/列选择）
    // - { target_cells: [ {x,y}, ... ] } （显式格子集合）
    // - legacy array [ {x,y}, ... ]

    let payload = {};

    if (Array.isArray(targetData)) {
        // 旧格式数组 -> 计算包围盒
        const xs = targetData.map(c => c.x);
        const ys = targetData.map(c => c.y);
        payload.target_area = {
            x1: Math.min(...xs),
            y1: Math.min(...ys),
            x2: Math.max(...xs),
            y2: Math.max(...ys)
        };
        payload.selected_cells = targetData;
    } else if (targetData && targetData.selected_cells) {
        const arr = targetData.selected_cells;
        const xs = arr.map(c => c.x);
        const ys = arr.map(c => c.y);
        payload.target_area = {
            x1: Math.min(...xs),
            y1: Math.min(...ys),
            x2: Math.max(...xs),
            y2: Math.max(...ys)
        };
        payload.selected_cells = arr;
    } else if (targetData && targetData.target_area) {
        payload.target_area = targetData.target_area; // 直接传递 { target_area: {...} }
        if (targetData.board) payload.board = targetData.board; // 神威！：作用棋盘
    } else if (targetData && targetData.target_line) {
        payload.target_line = targetData.target_line; // 行/列选择
    } else if (targetData && targetData.target_cells) {
        payload.target_cells = targetData.target_cells; // 显式格子集合（如连续选择）
    } else if (targetData && targetData.x !== undefined && targetData.y !== undefined) {
        // 单格位置
        payload.target_area = { x1: targetData.x, y1: targetData.y, x2: targetData.x, y2: targetData.y };
    } else {
        // 未识别格式，直接发送原始数据
        payload = targetData;
    }

    // 神之宣告：船已经选好了，接着问要发动哪个效果 —— 效果选完才真正提交。
    // 卡面是「选定自己的两艘船死亡，并选择接下来两个效果其一发动」，船在前、效果在后。
    if (ctx.card.name === '神之宣告' && !gameState.pendingEffectChoice) {
        promptDivineDecreeChoice(ctx, payload);
        return;
    }

    // 神之宣告：把选好的效果一并带上（否则服务端只能退回默认效果）
    if (gameState.pendingEffectChoice) {
        payload.effect_choice = gameState.pendingEffectChoice;
        gameState.pendingEffectChoice = null;
    }

    _dispatchMagicTarget(payload, ctx);
}

// 真正把目标选择结果提交出去：
// 连锁响应窗口里打出的卡回填给 chain_response，否则走 use_magic_card。
// ctx 必须由调用方在入口处抓好传进来 —— 走到这里时 gameState 里的选择状态可能已被清理。
function _dispatchMagicTarget(payload, ctx) {
    const context = ctx || {};
    const cardIndex = (context.cardIndex === undefined || context.cardIndex === null)
        ? gameState.currentCardIndex
        : context.cardIndex;
    const chainPending = (context.chainPending === undefined)
        ? gameState.pendingChainCard
        : context.chainPending;
    // 优先权询问里打的速阶3（方案 D）：与连锁同构，
    // 目标选好后回填给 priority_response，而不是 use_magic_card。
    const priorityPending = (context.priorityPending === undefined)
        ? gameState.pendingPriorityCard
        : context.priorityPending;

    if (priorityPending) {
        gameState.pendingPriorityCard = null;
        gameState.pendingChainCard = null;
        gameState.pendingEffectChoice = null;
        gameState.currentMagicCard = null;
        gameState.currentCardIndex = null;
        gameState.socket.emit('priority_response', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            respond: true,
            card: priorityPending.card,
            targets: payload,
            decline_all: !!gameState.declinePriority
        });
        return;
    }

    if (chainPending) {
        gameState.pendingChainCard = null;
        gameState.pendingEffectChoice = null;
        gameState.currentMagicCard = null;
        gameState.currentCardIndex = null;
        gameState.socket.emit('chain_response', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            chain: true,
            card: chainPending.card,
            targets: payload
        });
        return;
    }

    // 发送并清理当前魔法卡选择状态
    sendMagicCard(cardIndex, payload);
    gameState.currentMagicCard = null;
    gameState.currentCardIndex = null;
}


// 扩展applyCardEffect函数
// 添加魔法效果动画和UI辅助函数
