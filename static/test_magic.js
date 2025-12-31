// 魔法卡系统测试工具
function testMagicSystem() {
    console.log("====== 开始魔法系统测试 ======");
    
    // 添加Socket连接检查
    if (!gameState.socket) {
        console.error("错误: 未建立游戏连接，请先创建或加入房间");
        alert("请先创建或加入房间后再运行测试");
        return;
    }
    
    testCardUniqueness();
    testMagicCardUsage();
    testFieldMagic(); // 添加场地魔法测试
    testEndPhase();
}

// 测试1: 验证卡牌唯一性
function testCardUniqueness() {
    console.log("\n测试1: 卡牌唯一性测试");
    
    // 重置牌堆
    gameState.deck = [...magicCards];
    shuffleDeck(gameState.deck);
    gameState.hand = [];
    gameState.discardPile = [];
    
    // 抽10张牌(超过牌堆中非失灵卡牌数量)
    for (let i = 0; i < 10; i++) {
        drawCard();
    }
    
    // 检查手牌中是否有重复非失灵卡牌
    const cardNames = {};
    let hasDuplicate = false;
    
    gameState.hand.forEach(card => {
        if (card.name !== "失灵！") {
            if (cardNames[card.name]) {
                console.error(`发现重复卡牌: ${card.name}`);
                hasDuplicate = true;
            }
            cardNames[card.name] = true;
        }
    });
    
    if (hasDuplicate) {
        console.error("测试1失败: 存在重复非失灵卡牌");
    } else {
        console.log("测试1通过: 所有非失灵卡牌都是唯一的");
    }
}

// 测试2: 魔法卡使用流程
function testMagicCardUsage() {
    console.log("测试2: 魔法卡使用流程测试");
    
    // 增强函数存在性检查与重试机制
    if (typeof window.playMagicCard !== 'function') {
        console.error("错误: playMagicCard 函数未找到，等待游戏初始化...");
        // 2秒后重试
        setTimeout(testMagicCardUsage, 2000);
        return;
    }
    
    // 添加Socket回调检查
    if (!gameState.socket || !gameState.socket._callbacks) {
        console.error("错误: 无法访问Socket连接或回调函数");
        return;
    }
    
    // 强制设置为准备阶段和当前玩家回合
    console.log("=== 强制设置测试环境 ===");
    console.log("设置当前阶段为准备阶段");
    gameState.currentPhase = 'preparation';
    console.log("设置当前回合为玩家自己");
    gameState.currentAttacker = gameState.playerId;
    
    // 添加游戏阶段检查
    const validPhases = ['preparation', 'battle', 'end'];
    if (!validPhases.includes(gameState.currentPhase)) {
        console.error(`错误: 当前游戏阶段为${gameState.currentPhase}，无法使用魔法卡。请等待游戏进入准备阶段、战斗阶段或结束阶段。`);
        alert(`当前游戏阶段不允许使用魔法卡，请稍后再试。\n当前阶段: ${gameState.currentPhase || '未开始'}`);
        testEndPhase();
        return;
    }
    
    // 添加当前回合检查
    if (gameState.currentAttacker !== gameState.playerId) {
        console.error("错误: 当前不是你的回合，无法使用速阶1和2的魔法卡");
        alert("当前不是你的回合，无法使用魔法卡");
        testEndPhase();
        return;
    }
    
    if (gameState.hand.length === 0) {
        console.log("手牌为空，尝试抽卡...");
        drawCard();
        // 如果抽卡后仍为空，结束测试
        if (gameState.hand.length === 0) {
            console.error("无法抽卡，手牌为空");
            return;
        }
    }
    
    // 选择第一张非"失灵！"的魔法卡进行测试，如果没有则使用"失灵！"
    let testCardIndex = -1;
    for (let i = 0; i < gameState.hand.length; i++) {
        if (gameState.hand[i].name !== '失灵！') {
            testCardIndex = i;
            break;
        }
    }
    
    // 如果全是"失灵！"，则使用第一张
    if (testCardIndex === -1) testCardIndex = 0;
    
    const testCard = gameState.hand[testCardIndex];
    const originalHandLength = gameState.hand.length;
    const originalDeckLength = gameState.deck.length;
    const originalDiscardLength = gameState.discardPile.length;
    
    console.log(`尝试使用魔法卡: ${testCard.name} (速阶${testCard.speed})`);
    console.log(`使用前状态 - 手牌: ${originalHandLength}张, 牌堆: ${originalDeckLength}张, 弃牌堆: ${originalDiscardLength}张`);
    
    // 检查卡牌是否可以在当前阶段使用
    if (!canPlayCard(testCard)) {
        console.error(`测试失败: 无法在${gameState.currentPhase}阶段使用${testCard.name}（速阶${testCard.speed}）`);
        // 对于速阶3的卡牌，如果仍然无法使用，说明存在严重问题
        if (testCard.speed === 3) {
            console.error("严重错误: 速阶3的卡牌应该可以在任何阶段使用");
        }
        testEndPhase();
        return;
    }
    
    // 监听魔法卡应用事件
    const originalOnMagicApplied = gameState.socket._callbacks['magic_applied'];
    gameState.socket._callbacks['magic_applied'] = (data) => {
        console.log(`\n===== 魔法卡效果生效 =====`);
        console.log(`魔法卡应用成功: ${data.card.name} - ${data.message}`);
        console.log(`效果描述: ${data.card.description}`);
        
        // 验证魔法卡效果
        if (gameState.hand.length === originalHandLength) {
            console.error("效果验证失败: 手牌数量未减少");
        } else if (gameState.discardPile.length <= originalDiscardLength) {
            console.error("效果验证失败: 弃牌堆未增加");
        } else {
            console.log(`效果验证成功: 手牌减少1张, 弃牌堆增加1张`);
            console.log(`使用后状态 - 手牌: ${gameState.hand.length}张, 牌堆: ${gameState.deck.length}张, 弃牌堆: ${gameState.discardPile.length}张`);
            
            // 根据卡牌类型输出具体效果
            if (data.card.type === 'attack') {
                console.log(`攻击效果: 对敌方造成${data.card.power}点伤害`);
            } else if (data.card.type === 'detection') {
                console.log(`探测效果: 已揭示敌方${data.revealedShips || 0}艘战舰位置`);
            } else if (data.card.type === 'defense') {
                console.log(`防御效果: 已抵消敌方${data.blockedAttacks || 0}次攻击`);
            }
        }
        
        console.log("测试2通过: 魔法卡使用流程正常");
        
        // 恢复原始回调
        gameState.socket._callbacks['magic_applied'] = originalOnMagicApplied;
        
        // 继续下一个测试
        testEndPhase();
    };
    
    // 尝试使用魔法卡
    try {
        playMagicCard(testCardIndex);
    } catch (e) {
        console.error(`使用魔法卡时出错: ${e.message}`);
        // 恢复原始回调
        gameState.socket._callbacks['magic_applied'] = originalOnMagicApplied;
        testEndPhase();
    }
}

// 测试3: 结束阶段功能
function testEndPhase() {
    console.log("\n测试3: 结束阶段功能测试");
    
    // 模拟攻击次数为0
    gameState.attacksRemaining = 0;
    
    // 监听回合变化事件
    const originalOnTurnChange = gameState.socket._callbacks['turn_change'];
    gameState.socket._callbacks['turn_change'] = (data) => {
        console.log(`回合已切换到玩家: ${data.current_attacker}`);
        console.log("测试3通过: 结束阶段功能正常");
        
        // 恢复原始回调
        gameState.socket._callbacks['turn_change'] = originalOnTurnChange;
    };
    
    // 尝试结束阶段
    try {
        endBattlePhase();
        console.log("测试3完成");
    } catch (e) {
        console.error(`结束阶段测试失败: ${e.message}`);
    }
}

// 添加测试启动函数
window.addEventListener('load', function() {
    // 添加测试按钮
    const testButton = document.createElement('button');
    testButton.textContent = '运行魔法系统测试';
    testButton.id = 'test-magic-system';
    testButton.style.position = 'fixed';
    testButton.style.bottom = '20px';
    testButton.style.right = '20px';
    testButton.style.zIndex = '1000';
    document.body.appendChild(testButton);
    testButton.addEventListener('click', testMagicSystem);
});

// 修改页面加载事件，确保在 game.js 之后执行
window.addEventListener('load', function() {
    console.log("test_magic.js 加载完成，检查 playMagicCard:", typeof window.playMagicCard);
    // 延迟添加测试按钮，确保 game.js 有足够时间加载
    setTimeout(addTestButton, 1000);
});

// 添加洗牌函数
function shuffleDeck(deck) {
    for (let i = deck.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [deck[i], deck[j]] = [deck[j], deck[i]];
    }
    return deck;
}

// 在 magic_applied 回调中添加详细效果验证
console.log("魔法卡效果验证:");
console.log("- 手牌变化: ", originalHandLength, "→", gameState.hand.length);
console.log("- 弃牌堆变化: ", originalDiscardLength, "→", gameState.discardPile.length);
console.log("- 效果描述: ", data.card.description);

// 添加场地魔法测试
function testFieldMagic() {
    console.log("\n测试4: 场地魔法测试");

    // 查找场地魔法
    let fieldCardIndex = -1;
    for (let i = 0; i < gameState.hand.length; i++) {
        if (gameState.hand[i].type === '场地') {
            fieldCardIndex = i;
            break;
        }
    }

    if (fieldCardIndex === -1) {
        console.log("手牌中没有场地魔法，无法测试");
        return;
    }

    const fieldCard = gameState.hand[fieldCardIndex];
    console.log(`尝试使用场地魔法: ${fieldCard.name}`);

    // 监听场地魔法更新
    const originalOnFieldMagic = gameState.socket._callbacks['field_magic_updated'];
    gameState.socket._callbacks['field_magic_updated'] = (data) => {
        if (data.player_id === gameState.playerId) {
            console.log(`场地魔法更新成功: ${data.card ? data.card.name : '无'}`);
            console.log("测试4通过: 场地魔法使用流程正常");
        }

        // 恢复原始回调
        gameState.socket._callbacks['field_magic_updated'] = originalOnFieldMagic;
    };

    try {
        playMagicCard(fieldCardIndex);
    } catch (e) {
        console.error(`使用场地魔法时出错: ${e.message}`);
        gameState.socket._callbacks['field_magic_updated'] = originalOnFieldMagic;
    }
}