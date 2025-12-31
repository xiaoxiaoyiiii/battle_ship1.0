// DOM元素
const startScreen = document.getElementById('start-screen');
const shipPlacementScreen = document.getElementById('ship-placement-screen');
const rpsScreen = document.getElementById('rps-screen');
const gameScreen = document.getElementById('game-screen');
const gameOverScreen = document.getElementById('game-over-screen');

// 开始界面元素
const createRoomBtn = document.getElementById('create-room');
const joinRoomBtn = document.getElementById('join-room');
const roomIdInput = document.getElementById('room-id-input');
const confirmJoinBtn = document.getElementById('confirm-join');
const roomInfo = document.getElementById('room-info');
const currentRoomId = document.getElementById('current-room-id');
const playerNameInput = document.getElementById('player-name');
const roomCodeInput = document.getElementById('room-code');

// 战舰放置界面元素
const playerBoard = document.getElementById('player-board');
const shipsPlaced = document.getElementById('placed-count');
const confirmShipsBtn = document.getElementById('confirm-ships');

// 猜拳界面元素
const rpsChoices = document.querySelectorAll('.rps-choice');
const rpsResult = document.getElementById('rps-result');
const rpsRound = document.getElementById('rps-round');

// 游戏界面元素
const gamePlayerBoard = document.getElementById('game-player-board');
const opponentBoard = document.getElementById('opponent-board');
const yourShips = document.getElementById('your-ships');
const opponentShips = document.getElementById('opponent-ships');
const currentPlayer = document.getElementById('current-player');
const attacksRemaining = document.getElementById('attacks-remaining');
const gameRound = document.getElementById('game-round');

// 游戏结束界面元素
const gameResult = document.getElementById('game-result');
const playAgainBtn = document.getElementById('play-again');

// 游戏状态
// 游戏状态
window.gameState = {
    socket: null,
    playerId: null,
    roomId: null,
    playerName: '玩家',
    ships: [],
    placedShips: 0,
    isMyTurn: false,
    myAttacks: [],
    opponentAttacks: [],
    // 新增魔法卡相关状态
    deck: [],               // 牌堆
    hand: [],               // 手牌
    discardPile: [],        // 弃牌堆
    chain: [],              // 连锁栈
    currentPhase: null,     // 当前游戏阶段
    fieldMagic: null        // 场地魔法
}

// 添加加载完成验证
console.log("game.js 加载完成，playMagicCard 状态:", typeof window.playMagicCard);

// 绑定事件监听器
function bindEventListeners() {
    // 开始界面
    createRoomBtn.addEventListener('click', createRoom);
    joinRoomBtn.addEventListener('click', () => roomIdInput.classList.remove('hidden'));
    confirmJoinBtn.addEventListener('click', joinRoom);
    playAgainBtn.addEventListener('click', resetGame);

    // 战舰放置
    confirmShipsBtn.addEventListener('click', confirmShipPlacement);

    // 猜拳选择
    rpsChoices.forEach(choice => {
        choice.addEventListener('click', () => handleRPSChoice(choice.dataset.choice));
    });
    
    // 修复：结束战斗阶段按钮事件（修正ID匹配问题）
    document.getElementById('enter-end-phase').addEventListener('click', endBattlePhase);
}

// 创建房间
function createRoom() {
    gameState.playerName = playerNameInput.value || '玩家';
    gameState.socket = io.connect('http://' + window.location.host);
    setupSocketListeners();

    // 等待Socket连接成功后再发送创建房间请求
    gameState.socket.on('connect', () => {
        gameState.socket.emit('create_room', {}, (response) => {
            if (response.status === 'success') {
                gameState.roomId = response.room_id;
                currentRoomId.textContent = gameState.roomId;
                roomInfo.classList.remove('hidden');
                
                // 自动加入创建的房间
                gameState.socket.emit('join_room', {
                    room_id: gameState.roomId,
                    player_name: gameState.playerName
                }, (joinResponse) => {
                    if (joinResponse.status === 'success') {
                        gameState.playerId = joinResponse.player_id;
                    } else {
                        alert(joinResponse.message);
                    }
                });
            }
        });
    });
}

// 加入房间
function joinRoom() {
    gameState.playerName = playerNameInput.value || '玩家';
    const roomId = roomCodeInput.value.trim();
    if (!roomId) return;

    gameState.socket = io.connect('http://' + window.location.host);
    setupSocketListeners();

    gameState.socket.emit('join_room', {
        room_id: roomId,
        player_name: gameState.playerName
    }, (response) => {
        if (response.status === 'success') {
            gameState.roomId = roomId;
            gameState.playerId = response.player_id;
            currentRoomId.textContent = roomId;
            roomInfo.classList.remove('hidden');
        } else {
            alert(response.message);
        }
    });
}

// 设置Socket监听器
function setupSocketListeners() {
    const socket = gameState.socket;

    socket.on('connect', () => {
        console.log('Connected to server');
    });

    socket.on('game_state', (data) => {
        console.log('Game state received:', data);
        // 隐藏所有屏幕和信息面板
        roomInfo.classList.add('hidden');
        startScreen.classList.remove('active');
        shipPlacementScreen.classList.remove('active');
        rpsScreen.classList.remove('active');
        gameScreen.classList.remove('active');
        gameOverScreen.classList.remove('active');
        
        switch (data.state) {
            case 'waiting':
                // 显示等待其他玩家加入
                roomInfo.classList.remove('hidden');
                currentRoomId.textContent = gameState.roomId;
                break;
            case 'placing_ships':
                console.log('Switching to ship placement screen');
                shipPlacementScreen.classList.add('active');
                initBoard(playerBoard, true);
                // 添加以下代码确保界面正确切换
                startScreen.classList.add('hidden');
                roomInfo.classList.add('hidden');
                break;
            case 'rock_paper_scissors':
                rpsScreen.classList.add('active');
                rpsRound.textContent = data.round || 1;
                rpsResult.classList.add('hidden');
                break;
            // 在setupSocketListeners的game_state事件处理中添加
            case 'attacking':
                gameScreen.classList.add('active');
                gameRound.textContent = data.round || 1;
                gameState.currentPhase = data.current_phase || 'preparation';
                gameState.currentAttacker = data.current_attacker;
                initGameBoards();
                updateTurnIndicator(data.current_attacker, data.attacks_remaining);
                updatePhaseUI(); // 确保调用阶段UI更新
                
                // 不再手动添加卡牌，改为依赖hand_updated事件
                // 卡牌会通过hand_updated事件正确更新，避免重复添加
                break;
            case 'game_over':
                gameOverScreen.classList.add('active');
                gameResult.textContent = data.winner === gameState.playerId ? '恭喜你获胜了！' : '很遗憾，你输了。';
                break;
            default:
                console.error('Unknown game state:', data.state);
                roomInfo.classList.remove('hidden');
                currentRoomId.textContent = gameState.roomId;
                roomInfo.querySelector('.waiting-message').textContent = '未知游戏状态，请刷新页面';
        }
    });

    socket.on('rps_result', (result) => {
        console.log('RPS result:', result);
        rpsResult.classList.remove('hidden');
        if (result.status === 'tie') {
            rpsResult.textContent = result.message;
        } else {
            const winnerName = result.winner === gameState.playerId ? '你' : '对手';
            rpsResult.textContent = `猜拳结果: 你选择了${getRPSName(result.choices[gameState.playerId])}, 对手选择了${getRPSName(result.choices[Object.keys(result.choices).find(k => k !== gameState.playerId)])}。${winnerName}获胜，先攻击！`;
        }
    });

    socket.on('attack_result', (result) => {
        console.log('Attack result:', result);
        updateAttackDisplay(result);
        opponentShips.textContent = result.defender_remaining_ships;
        attacksRemaining.textContent = result.remaining_attacks;
    });

    socket.on('turn_change', (data) => {
        console.log('Turn change:', data);
        gameState.currentPhase = data.phase;  // 添加阶段更新
        updateTurnIndicator(data.current_attacker, data.attacks_remaining);
        updatePhaseUI();  // 更新阶段UI
    });

    socket.on('game_over', (data) => {
        console.log('Game over:', data);
        switchScreen(gameOverScreen);
        gameResult.textContent = data.winner === gameState.playerId ? '恭喜你获胜了！' : '很遗憾，你输了。';
    });

    // 添加阶段更新监听
    socket.on('phase_updated', (data) => {
        gameState.currentPhase = data.current_phase;
        gameState.currentAttacker = data.current_attacker;
        updatePhaseUI();
    });

    // 添加场地魔法更新监听
    socket.on('field_magic_updated', function(data) {
        console.log('场地魔法更新:', data);
        updateFieldMagicUI(data.player_id, data.card);
    });

    // 添加魔法卡连锁相关事件监听
    socket.on('magic_chain_updated', (data) => {
        gameState.chain = data.chain;
        updateChainUI();
    });

    socket.on('chain_resolved', function(data) {
        console.log('连锁结算完成', data.results);
        // 应用连锁结算结果
        data.results.forEach(result => {
            applyCardEffect(result.card);
            // 将使用过的卡牌加入弃牌堆
            gameState.discardPile.push(result.card);
        });
        // 更新游戏状态
        updateHandUI();
        // 如果是攻击阶段，恢复攻击状态
        if (gameState.currentPhase === 'battle') {
            enableAttack();
        }
    });
    
    socket.on('magic_chain_error', function(data) {
        alert('魔法卡使用错误: ' + data.message);
        // 错误恢复 - 将卡牌放回手牌
        if (data.card) {
            gameState.hand.push(data.card);
            updateHandUI();
        }
    });

    socket.on('chain_request', function(data) {
        // 显示连锁选择对话框
        const chainPrompt = document.createElement('div');
        chainPrompt.className = 'magic-prompt';
        chainPrompt.innerHTML = `
            <h3>对方发动了魔法卡【${data.card.name}】</h3>
            <p>是否发动连锁魔法卡？</p>
            <div class="chain-options">
                <button id="chain-yes">发动连锁</button>
                <button id="chain-no">不连锁</button>
            </div>
        `;
        document.body.appendChild(chainPrompt);

        // 不连锁按钮
        document.getElementById('chain-no').addEventListener('click', () => {
            gameState.socket.emit('chain_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                chain: false
            });
            document.body.removeChild(chainPrompt);
        });

        // 发动连锁按钮
        document.getElementById('chain-yes').addEventListener('click', () => {
            document.body.removeChild(chainPrompt);
            // 显示可连锁的手牌
            showChainableCards();
        });
    });

    // 添加新的魔法卡相关事件监听
    socket.on('ask_counter_magic', function(data) {
        // 显示是否使用"失灵！"的对话框
        const counterPrompt = document.createElement('div');
        counterPrompt.className = 'magic-prompt';
        counterPrompt.innerHTML = `
            <h3>对方发动了魔法卡【${data.card.name}】</h3>
            <p>是否使用"失灵！"无效化此魔法？</p>
            <div class="counter-options">
                <button id="use-counter">使用失灵！</button>
                <button id="no-counter">不使用</button>
            </div>
        `;
        document.body.appendChild(counterPrompt);

        // 检查是否有"失灵！"
        const hasCounter = gameState.hand.some(card => card.name === '失灵！');
        document.getElementById('use-counter').disabled = !hasCounter;

        document.getElementById('use-counter').addEventListener('click', () => {
            gameState.socket.emit('counter_magic_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                use_counter: true
            });
            document.body.removeChild(counterPrompt);
        });

        document.getElementById('no-counter').addEventListener('click', () => {
            gameState.socket.emit('counter_magic_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                use_counter: false
            });
            document.body.removeChild(counterPrompt);
        });
    });

    socket.on('magic_negated', function(data) {
        showMessage(`魔法卡【${data.card.name}】被对方无效化！`);
        updateHandUI();
    });

    socket.on('magic_applied', function(result) {
        showMessage(`魔法卡【${result.card.name}】效果生效: ${result.message}`);
        applyCardEffect(result.card);
        updateHandUI();
    });

    // 新增：监听手牌更新事件
    socket.on('hand_updated', (data) => {
        gameState.hand = data.hand;
        updateHandUI();
    });

}

// 切换屏幕
function switchScreen(screen) {
    [startScreen, shipPlacementScreen, rpsScreen, gameScreen, gameOverScreen].forEach(s => {
        s.classList.remove('active');
    });
    screen.classList.add('active');
}

// 初始化棋盘
function initBoard(boardElement, isEditable = false) {
    boardElement.innerHTML = '';
    for (let y = 0; y < 6; y++) {
        for (let x = 0; x < 6; x++) {
            const cell = document.createElement('div');
            cell.classList.add('cell');
            cell.dataset.x = x;
            cell.dataset.y = y;
            if (isEditable) {
                cell.addEventListener('click', () => handleCellClick(x, y));
            }
            boardElement.appendChild(cell);
        }
    }
}

// 初始化游戏棋盘
function initGameBoards() {
    // 初始化玩家棋盘
    gamePlayerBoard.innerHTML = '';
    for (let y = 0; y < 6; y++) {
        for (let x = 0; x < 6; x++) {
            const cell = document.createElement('div');
            cell.classList.add('cell');
            cell.dataset.x = x;
            cell.dataset.y = y;

            // 显示自己的战舰
            if (gameState.ships.some(ship => ship.positions.some(pos => pos.x === x && pos.y === y))) {
                cell.classList.add('ship');
            }

            // 显示被攻击的位置
            if (gameState.opponentAttacks.some(attack => attack.x === x && attack.y === y)) {
                const attack = gameState.opponentAttacks.find(a => a.x === x && a.y === y);
                cell.classList.add(attack.hit ? 'hit' : 'miss');
                cell.textContent = attack.hit ? '✕' : '○';
            }

            gamePlayerBoard.appendChild(cell);
        }
    }

    // 初始化对手棋盘
    opponentBoard.innerHTML = '';
    for (let y = 0; y < 6; y++) {
        for (let x = 0; x < 6; x++) {
            const cell = document.createElement('div');
            cell.classList.add('cell');
            cell.dataset.x = x;
            cell.dataset.y = y;

            // 如果是自己的回合，可以点击攻击
            if (gameState.isMyTurn) {
                // 检查是否已经攻击过
                const alreadyAttacked = gameState.myAttacks.some(attack => attack.x === x && attack.y === y);
                if (!alreadyAttacked) {
                    cell.addEventListener('click', () => handleAttack(x, y));
                }
            }

            // 显示攻击结果
            if (gameState.myAttacks.some(attack => attack.x === x && attack.y === y)) {
                const attack = gameState.myAttacks.find(a => a.x === x && a.y === y);
                cell.classList.add(attack.hit ? 'hit' : 'miss');
                cell.textContent = attack.hit ? '✕' : '○';
            }

            opponentBoard.appendChild(cell);
        }
    }
}

// 处理棋盘单元格点击（放置战舰）
function handleCellClick(x, y) {
    // 检查是否已经放置了6艘战舰
    if (gameState.placedShips >= 6) return;

    // 检查该位置是否已经放置了战舰
    const alreadyPlaced = gameState.ships.some(ship => 
        ship.positions.some(pos => pos.x === x && pos.y === y)
    );
    if (alreadyPlaced) return;

    // 添加新战舰（1x1大小）
    gameState.ships.push({
        id: Date.now(),
        positions: [{x, y}],
        hits: []
    });

    gameState.placedShips++;
    shipsPlaced.textContent = gameState.placedShips;

    // 更新界面
    const cell = playerBoard.querySelector(`[data-x="${x}"][data-y="${y}"]`);
    cell.classList.add('ship');

    // 如果放置了6艘战舰，显示确认按钮
    if (gameState.placedShips === 6) {
        confirmShipsBtn.classList.remove('hidden');
    }
}

// 确认战舰放置
function confirmShipPlacement() {
    gameState.socket.emit('place_ships', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        ships: gameState.ships
    }, (response) => {
        if (response.status === 'success') {
            console.log('Ships placed successfully');
        }
    });
}

// 处理猜拳选择
function handleRPSChoice(choice) {
    gameState.socket.emit('rps_choice', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        choice: choice
    }, (response) => {
        if (response.status === 'success') {
            console.log('RPS choice sent:', choice);
        }
    });
}

// 处理攻击
function handleAttack(x, y) {
    if (!gameState.isMyTurn) return;
    
    // 新增：检查当前是否为战斗阶段
    if (gameState.currentPhase !== 'battle') {
        alert('当前不是战斗阶段');
        return;
    }

    gameState.socket.emit('attack', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        x: x,
        y: y
    }, (response) => {
        if (response.status === 'error') {
            alert(response.message);
        }
    });
}

// 更新攻击显示
function updateAttackDisplay(result) {
    // 如果是自己的攻击
    if (result.attacker === gameState.playerId) {
        gameState.myAttacks.push({
            x: result.x,
            y: result.y,
            hit: result.hit
        });
    } else {
        // 如果是对手的攻击
        gameState.opponentAttacks.push({
            x: result.x,
            y: result.y,
            hit: result.hit
        });
        yourShips.textContent = result.defender_remaining_ships;
    }

    // 更新棋盘显示
    initGameBoards();
}

// 更新回合指示器
function updateTurnIndicator(currentAttacker, remainingAttacks) {
    gameState.isMyTurn = currentAttacker === gameState.playerId;
    currentPlayer.textContent = gameState.isMyTurn ? '你' : '对手';
    attacksRemaining.textContent = remainingAttacks;
    initGameBoards(); // 重新初始化棋盘以更新可点击状态
}

// 获取猜拳名称
function getRPSName(choice) {
    const names = {
        'rock': '石头',
        'paper': '剪刀',
        'scissors': '布'
    };
    return names[choice] || choice;
}

// 重置游戏
function resetGame() {
    gameState = {
        socket: null,
        playerId: null,
        roomId: null,
        playerName: playerNameInput.value || '玩家',
        ships: [],
        placedShips: 0,
        isMyTurn: false,
        myAttacks: [],
        opponentAttacks: []
    };
    switchScreen(startScreen);
}

// 新增：结束战斗阶段函数
window.endBattlePhase = function() {
    if (!gameState.isMyTurn || gameState.currentPhase !== 'battle') {
        alert('当前不是你的战斗阶段');
        return;
    }
    
    // 检查攻击次数是否用完
    if (parseInt(attacksRemaining.textContent) > 0) {
        alert('还有尚未用完的攻击次数');
        return;
    }
    
    gameState.socket.emit('enter_end_phase', {
        room_id: gameState.roomId,
        player_id: gameState.playerId
    }, (response) => {
        if (response.status === 'error') {
            alert(response.message);
        }
    });
}

// 在初始化时调用按钮设置
window.addEventListener('load', () => {
    init();
    setupPhaseButtons(); // 添加这行
});

// 初始化魔法卡牌堆
function initMagicDeck() {
    // 复制魔法卡数组并洗牌
    gameState.deck = [...window.magicCards];
    shuffleDeck(gameState.deck);
    // 初始抽5张牌
    for (let i = 0; i < 5; i++) {
        drawCard();
    }
}

// 洗牌算法 (Fisher-Yates)
function shuffleDeck(deck) {
    for (let i = deck.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [deck[i], deck[j]] = [deck[j], deck[i]];
    }
}

// 抽卡函数
window.drawCard = function() {
    if (gameState.deck.length === 0) {
        // 牌堆为空，从弃牌堆重新洗牌
        gameState.deck = [...gameState.discardPile];
        shuffleDeck(gameState.deck);
        gameState.discardPile = [];
        console.log('牌堆已用尽，从弃牌堆重新洗牌');
    }
    const card = gameState.deck.shift();
    gameState.hand.push(card);
    updateHandUI();
    return card;
};

// 修改canPlayCard函数
function canPlayCard(card) {
    // 速阶1: 只能在自己的准备阶段使用
    if (card.speed === 1) {
        return gameState.currentPhase === 'preparation' && gameState.currentAttacker === gameState.playerId;
    }
    // 速阶2: 只能在自己的回合使用
    else if (card.speed === 2) {
        return gameState.currentAttacker === gameState.playerId;
    }
    // 速阶3: 任何时候都可以使用
    else if (card.speed === 3) {
        return true;
    }
    return false;
}

// 添加魔法卡目标选择UI
function showMagicTargetSelection(card) {
    const targetPrompt = document.createElement('div');
    targetPrompt.className = 'magic-target-prompt';
    
    const size = needsTargetSelection(card.name);
    if (size > 0) {
        targetPrompt.innerHTML = `
            <h3>选择${size}x${size}区域</h3>
            <div class="target-board" id="target-board"></div>
            <button id="confirm-target">确认选择</button>
        `;
        createSelectionBoard(size);
    }
    
    document.body.appendChild(targetPrompt);
}

// 添加魔法卡目标选择判断函数
function needsTargetSelection(cardName) {
    const areaCards = {
        '冻结': 3,          // 3x3区域
        '探测雷达': 2,      // 2x2区域
        '轰炸': 10,         // 10x1行或列
        '硫磺火焰': 6,      // 6个连续格子
        '克苏鲁之眼': 1,    // 单个格子
        '神之宣告': 1       // 单个格子
    };
    return areaCards[cardName] || 0;
}

// 创建区域选择面板 - 用于区域选择类魔法卡
function createSelectionBoard(size, isOpponentBoard = true) {
    // 清除现有选择面板
    const existingBoard = document.getElementById('selection-board');
    if (existingBoard) existingBoard.remove();

    // 创建选择面板容器
    const board = document.createElement('div');
    board.id = 'selection-board';
    board.className = 'selection-board';
    board.style.display = 'grid';
    board.style.gridTemplateColumns = `repeat(${size}, 40px)`;
    board.style.gap = '2px';
    board.style.margin = '20px auto';
    board.style.padding = '10px';
    board.style.backgroundColor = '#333';
    board.style.borderRadius = '5px';

    // 创建选择单元格
    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            const cell = document.createElement('div');
            cell.className = 'selection-cell';
            cell.style.width = '40px';
            cell.style.height = '40px';
            cell.style.backgroundColor = '#666';
            cell.style.cursor = 'pointer';
            cell.dataset.x = x;
            cell.dataset.y = y;

            // 添加点击选择效果
            cell.addEventListener('click', () => {
                cell.classList.toggle('selected');
            });

            board.appendChild(cell);
        }
    }

    // 添加确认按钮
    const confirmBtn = document.createElement('button');
    confirmBtn.textContent = '确认选择';
    confirmBtn.className = 'magic-confirm-btn';
    confirmBtn.style.marginTop = '10px';
    confirmBtn.style.padding = '5px 15px';
    
    // 移除旧的确认按钮事件监听器（如果存在）
    const oldConfirmBtn = document.querySelector('.magic-confirm-btn');
    if (oldConfirmBtn) {
        oldConfirmBtn.removeEventListener('click', confirmHandler);
    }
    
    // 创建新的确认按钮事件处理函数
    const confirmHandler = () => {
        const selectedCells = getSelectedCells();
        if (selectedCells.length > 0) {
            confirmMagicTarget(selectedCells);
            board.remove();
        } else {
            alert('请至少选择一个单元格');
        }
    };
    
    confirmBtn.addEventListener('click', confirmHandler);

    board.appendChild(confirmBtn);
    document.body.appendChild(board);
}

// 获取选中的单元格坐标
function getSelectedCells() {
    const selectedCells = [];
    document.querySelectorAll('.selection-cell.selected').forEach(cell => {
        selectedCells.push({
            x: parseInt(cell.dataset.x),
            y: parseInt(cell.dataset.y)
        });
    });
    return selectedCells;
}

// 发动魔法卡
function playMagicCard(index) {
    console.log('playMagicCard called with index:', index);
    const card = gameState.hand[index];
    if (!card) return;

    // 检查卡牌是否可以在当前阶段使用
    if (!canPlayCard(card)) {
        const phaseName = gameState.currentPhase || '未开始';
        alert(`无法使用${card.name}：当前阶段${phaseName}不允许使用速阶${card.speed}的魔法卡`);
        return;
    }

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

    console.log('发送魔法卡:', card.name);
    gameState.socket.emit('use_magic_card', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        card: card,
        targets: targets
    }, (response) => {
        // 只有在服务器确认成功后才更新本地状态
        if (response.status === 'success') {
            console.log('魔法卡使用成功');
            // 从手牌中移除
            gameState.hand.splice(index, 1);
            // 添加到弃牌堆
            gameState.discardPile.push(card);
            // 更新UI
            updateHandUI();
        } else {
            console.error('魔法卡使用失败:', response.message);
            alert(`使用魔法卡失败: ${response.message || '未知错误'}`);
        }
    });
}

// 修改目标选择后的确认函数
function confirmMagicTarget(targetData) {
    if (gameState.currentMagicCard && gameState.currentCardIndex !== null) {
        sendMagicCard(gameState.currentCardIndex, targetData);
        // 清除当前选择的魔法卡
        gameState.currentMagicCard = null;
        gameState.currentCardIndex = null;
    }
}

// 扩展applyCardEffect函数
function applyCardEffect(card) {
    console.log(`应用魔法效果: ${card.name}`);
    // 显示魔法效果动画
    showMagicAnimation(card);

    switch(card.name) {
        case '余音绕梁':
            showMessage('余音绕梁效果生效，接下来两个攻击阶段将造成强制击杀');
            break;

        case '桃园结义':
            showMessage('桃园结义效果生效，请选择卡牌');
            break;

        case '无中生有':
            showMessage('无中生有效果生效，抽2张牌，本回合双方无法获得魔法卡');
            gameState.noMagicCardsThisTurn = true;
            break;

        case '极限增援':
            showMessage('极限增援效果生效，两个大回合后船少的一方获胜');
            break;

        case '无暇圣心':
            showMessage('无暇圣心效果生效，两个大回合后若双方都未造成伤害则你获胜');
            break;

        case '火力全开':
            showMessage('火力全开效果生效，本回合攻击次数翻倍');
            break;

        case '灵气复苏':
            showMessage('灵气复苏效果生效，双方船数已调整');
            break;

        case '溅射':
            showMessage('溅射效果生效，对周围格子造成伤害');
            // 显示溅射动画
            showSplashAnimation(gameState.lastAttack.x, gameState.lastAttack.y);
            break;

        case '雷达子弹':
            showMessage('雷达子弹效果生效，已扫描周围战舰位置');
            // 请求显示扫描结果
            gameState.socket.emit('request_revealed_positions', {
                room_id: gameState.roomId
            });
            break;

        case '越战越勇':
            showMessage('越战越勇效果生效，攻击次数增加2次');
            break;

        case '神威！':
            showMessage('神威效果生效，目标区域战舰被暂时除外');
            // 添加范围攻击逻辑
            if (gameState.selectedArea) {
                gameState.socket.emit('area_attack', {
                    room_id: gameState.roomId,
                    player_id: gameState.playerId,
                    area: gameState.selectedArea
                });
                // 清除已选择的区域
                gameState.selectedArea = null;
            }
            break;

        case '冻结':
            showMessage('冻结效果生效，目标区域战舰被冻结');
            break;

        case '轰炸':
            showMessage('轰炸效果生效，目标行/列受到攻击');
            // 添加轰炸逻辑
            if (gameState.selectedLine) {
                gameState.socket.emit('line_attack', {
                    room_id: gameState.roomId,
                    player_id: gameState.playerId,
                    line: gameState.selectedLine
                });
                // 清除已选择的行/列
                gameState.selectedLine = null;
            }
            break;

        case '探测雷达':
            showMessage('探测雷达效果生效，已显示目标区域战舰');
            gameState.socket.emit('request_revealed_positions', {
                room_id: gameState.roomId
            });
            break;

        case '饮血':
            showMessage('饮血效果生效，接下来每击杀一艘船抽一张牌');
            break;

        case '克苏鲁之眼':
            showMessage('克苏鲁之眼效果生效，双方各暴露一艘战舰位置');
            gameState.socket.emit('request_revealed_positions', {
                room_id: gameState.roomId
            });
            break;

        case 'Freezing！':
            showMessage('Freezing效果生效，对方回合被跳过');
            break;

        case '明智埋葬':
            showMessage('明智埋葬效果生效，埋葬卡牌并抽一张新牌');
            break;

        case '仁王之盾':
            showMessage('仁王之盾效果生效， selected ships are protected');
            break;

        case '八方来财':
            showMessage('八方来财效果生效，战舰数目变化时抽一张牌');
            break;

        case '平等条约':
            showMessage('平等条约效果生效，船数改变效果被无效化');
            break;

        case '百亿补贴':
            showMessage('百亿补贴效果生效，船被击败时攻击次数加3');
            // 添加状态图标显示
            document.getElementById('effect-indicators').innerHTML += '<div class="effect-icon" title="百亿补贴">补贴</div>';
            break;

        case '绝处逢生':
            showMessage('绝处逢生效果生效，击杀任何船直接获胜');
            // 重新初始化棋盘
            initBoard(playerBoard, true);
            gameState.ships = [];
            gameState.placedShips = 0;
            shipsPlaced.textContent = '0';
            confirmShipsBtn.classList.add('hidden');
            break;

        case '死者苏生':
        case '疗愈':
            showMessage('复活效果生效，战舰已复活');
            break;

        case '盗亦有道':
            showMessage('盗亦有道效果生效，获取对方上一张魔法卡');
            break;

        case '回光返照':
            showMessage('回光返照效果生效，请重新摆放战舰');
            // 重新初始化棋盘
            initBoard(playerBoard, true);
            gameState.ships = [];
            gameState.placedShips = 0;
            shipsPlaced.textContent = '0';
            confirmShipsBtn.classList.remove('hidden');
            switchScreen(shipPlacementScreen);
            break;

        case '加百列之光':
            showMessage('加百列之光效果生效，对方魔法和场地魔法被无效化');
            // 通知服务器移除场地魔法
            gameState.socket.emit('remove_field_magic', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            });
            // 本地更新UI
            updateFieldMagicUI(gameState.playerId, null);
            break;

        case '钢筋铁骨':
            showMessage('钢筋铁骨效果生效，其他战舰进入无敌状态');
            break;

        case '神机妙算':
            showMessage('神机妙算效果生效，已宣言船数减少数目');
            break;

        // 场地魔法
        case '恶魔契约':
            showMessage('场地魔法【恶魔契约】生效，双方船数增减绑定');
            document.getElementById('field-magic').textContent = '场地魔法: 恶魔契约';
            break;

        case '禁忌果实':
            showMessage('场地魔法【禁忌果实】生效，双方只能使用失灵！和场地魔法');
            document.getElementById('field-magic').textContent = '场地魔法: 禁忌果实';
            break;

        case '伊甸园':
            showMessage('场地魔法【伊甸园】生效，攻击次数变为6-n');
            document.getElementById('field-magic').textContent = '场地魔法: 伊甸园';
            break;

        case '教皇旨意':
            showMessage('场地魔法【教皇旨意】生效，攻击需要弃置魔法卡');
            document.getElementById('field-magic').textContent = '场地魔法: 教皇旨意';
            break;

        // 已实现的魔法卡
        case '失灵！':
            showMessage('失灵！效果生效，对方魔法被无效化');
            break;

        case '看破！':
            showMessage('看破！效果生效，本回合对方魔法卡被无效化');
            break;

        case '增援':
            showMessage('增援效果生效，获得一艘新战舰');
            showReinforcementPrompt();
            break;
    }
}

// 添加魔法效果动画和UI辅助函数
function showMagicAnimation(card) {
    const animation = document.createElement('div');
    animation.className = 'magic-animation';
    animation.innerHTML = `<div class="magic-card-name">${card.name}</div>`;
    document.body.appendChild(animation);
    
    setTimeout(() => {
        animation.classList.add('active');
        setTimeout(() => {
            animation.classList.add('fade-out');
            setTimeout(() => document.body.removeChild(animation), 1000);
        }, 1000);
    }, 100);
}


// 更新场地魔法UI显示
function updateFieldMagicUI(playerId, card) {
    const isMyField = playerId === gameState.playerId;
    const fieldElement = isMyField ? 
        document.getElementById('player-field-magic') : 
        document.getElementById('opponent-field-magic');

    if (card) {
        fieldElement.innerHTML = `${isMyField ? '你的' : '对方'}场地魔法: <span class="field-magic-card">${card.name}</span>`;
        fieldElement.className = `field-magic ${isMyField ? 'your-field' : 'opponent-field'}`;
    } else {
        fieldElement.innerHTML = `${isMyField ? '你的' : '对方'}场地魔法: <span class="no-magic">无</span>`;
        fieldElement.className = 'field-magic';
    }
}

function showReinforcementPrompt() {
    const prompt = document.createElement('div');
    prompt.className = 'reinforcement-prompt';
    prompt.innerHTML = `
        <h3>选择增援战舰位置</h3>
        <div class="target-board" id="reinforcement-board"></div>
        <button id="confirm-reinforcement">确认放置</button>
    `;
    document.body.appendChild(prompt);
    createSelectionBoard('reinforcement-board', 6, 6, false, true);
    
    document.getElementById('confirm-reinforcement').addEventListener('click', () => {
        const selected = getSelectedCells()[0];
        if (selected) {
            gameState.socket.emit('confirm_reinforcement_position', {
                room_id: gameState.roomId,
                position: selected
            });
            document.body.removeChild(prompt);
        } else {
            alert('请选择放置位置');
        }
    });
}

// 更新手牌UI
function updateHandUI() {
    const handElement = document.getElementById('magic-hand');
    if (!handElement) return;

    handElement.innerHTML = '';
    gameState.hand.forEach((card, index) => {
        const cardElement = document.createElement('div');
        cardElement.classList.add('magic-card');
        cardElement.dataset.index = index;
        cardElement.innerHTML = `
            <div class="card-name">${card.name}</div>
            <div class="card-speed">速阶: ${card.speed}</div>
            <div class="card-type">${card.type}魔法</div>
        `;
        cardElement.addEventListener('click', () => playMagicCard(index));
        
        // 添加悬停事件
        cardElement.addEventListener('mouseover', (e) => {
            const tooltip = document.getElementById('card-tooltip');
            tooltip.innerHTML = `
                <h3>${card.name}</h3>
                <p>速阶: ${card.speed}</p>
                <p>类型: ${card.type}</p>
                <p>效果: ${card.description}</p>
            `;
            tooltip.style.left = `${e.pageX + 10}px`;
            tooltip.style.top = `${e.pageY + 10}px`;
            tooltip.style.display = 'block';
        });
        
        cardElement.addEventListener('mouseout', () => {
            document.getElementById('card-tooltip').style.display = 'none';
        });
        
        cardElement.addEventListener('mousemove', (e) => {
            const tooltip = document.getElementById('card-tooltip');
            tooltip.style.left = `${e.pageX + 10}px`;
            tooltip.style.top = `${e.pageY + 10}px`;
        });
        
        handElement.appendChild(cardElement);
    });
}

// 添加卡牌悬停提示功能
function initCardTooltip() {
    const tooltip = document.createElement('div');
    tooltip.id = 'card-tooltip';
    tooltip.style.position = 'absolute';
    tooltip.style.backgroundColor = 'white';
    tooltip.style.border = '1px solid #333';
    tooltip.style.borderRadius = '5px';
    tooltip.style.padding = '10px';
    tooltip.style.boxShadow = '0 2px 10px rgba(0,0,0,0.2)';
    tooltip.style.zIndex = '1000';
    tooltip.style.display = 'none';
    document.body.appendChild(tooltip);
}



// 创建魔法卡UI元素
function createMagicCardUI() {
    const gameScreen = document.getElementById('game-screen');
    const magicUI = document.createElement('div');
    magicUI.id = 'magic-system';
    magicUI.innerHTML = `
        <div class="magic-hand-container">
            <h3>你的手牌</h3>
            <div id="magic-hand" class="magic-hand"></div>
        </div>
        <div id="chain-display" class="chain-display"></div>
    `;
    gameScreen.appendChild(magicUI);
}

// 初始化
function init() {
    // 绑定事件监听器
    bindEventListeners();
    // 创建魔法手牌区域
    createMagicCardUI();
    // 初始化卡牌提示框
    initCardTooltip();
}

// 更新连锁UI显示
function updateChainUI() {
    const chainElement = document.getElementById('chain-display');
    if (!chainElement) return;

    chainElement.innerHTML = `<h3>当前连锁 (${gameState.chain.length})</h3>`;
    gameState.chain.forEach((item, index) => {
        const chainItem = document.createElement('div');
        chainItem.className = 'chain-item';
        chainItem.innerHTML = `
            <div>连锁 ${index+1}: ${item.card.name}</div>
            <div>玩家: ${item.playerId === gameState.playerId ? '你' : '对手'}</div>
        `;
        chainElement.appendChild(chainItem);
    });
}

// 添加显示可连锁卡牌的函数
function showChainableCards() {
    const chainPrompt = document.createElement('div');
    chainPrompt.className = 'magic-prompt';
    chainPrompt.innerHTML = `
        <h3>选择要发动的连锁魔法卡</h3>
        <div id="chainable-cards" class="card-selection"></div>
        <div class="chain-buttons">
            <button id="confirm-chain">确认发动</button>
            <button id="cancel-chain">结束连锁</button>
        </div>
        <div class="chain-timer">剩余时间: <span id="chain-time">30</span>秒</div>
    `;
    document.body.appendChild(chainPrompt);

    const container = document.getElementById('chainable-cards');
    gameState.hand.forEach((card, index) => {
        // 只显示速阶大于当前卡牌的魔法卡
        if (card.speed > gameState.chain[gameState.chain.length - 1].card.speed) {
            const cardElement = createCardElement(card, index);
            cardElement.addEventListener('click', () => {
                document.querySelectorAll('#chainable-cards .card').forEach(el => el.classList.remove('selected'));
                cardElement.classList.add('selected');
                document.getElementById('confirm-chain').disabled = false;
            });
            container.appendChild(cardElement);
        }
    });

    // 添加连锁超时机制
    let timeLeft = 30;
    const timerElement = document.getElementById('chain-time');
    const timerInterval = setInterval(() => {
        timeLeft--;
        timerElement.textContent = timeLeft;
        if (timeLeft <= 0) {
            clearInterval(timerInterval);
            // 超时自动结束连锁
            gameState.socket.emit('chain_response', {
                room_id: gameState.roomId,
                player_id: gameState.playerId,
                chain: false
            });
            document.body.removeChild(chainPrompt);
        }
    }, 1000);

    document.getElementById('confirm-chain').addEventListener('click', () => {
        clearInterval(timerInterval);
        const selectedCard = document.querySelector('#chainable-cards .card.selected');
        if (selectedCard) {
            const index = parseInt(selectedCard.dataset.index);
            playMagicCard(index);
        }
        document.body.removeChild(chainPrompt);
    });

    document.getElementById('cancel-chain').addEventListener('click', () => {
        clearInterval(timerInterval);
        gameState.socket.emit('chain_response', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            chain: false
        });
        document.body.removeChild(chainPrompt);
    });
}

// 更新阶段UI
function updatePhaseUI() {
    const phaseElement = document.getElementById('current-phase');
    const enterBattleBtn = document.getElementById('enter-battle-phase');
    const enterEndBtn = document.getElementById('enter-end-phase');
    const endTurnBtn = document.getElementById('end-turn-btn');
    
    // 显示当前阶段
    phaseElement.textContent = {
        'preparation': '准备阶段',
        'battle': '战斗阶段',
        'end': '结束阶段'
    }[gameState.currentPhase] || gameState.currentPhase;
    
    // 按钮显示逻辑
    const isMyTurn = gameState.currentAttacker === gameState.playerId;
    
    // 隐藏所有按钮
    enterBattleBtn.style.display = 'none';
    enterEndBtn.style.display = 'none';
    endTurnBtn.style.display = 'none';
    
    // 根据当前阶段和回合显示相应按钮
    if (isMyTurn) {
        switch(gameState.currentPhase) {
            case 'preparation':
                enterBattleBtn.style.display = 'block';
                break;
            case 'battle':
                enterEndBtn.style.display = 'block';
                break;
            case 'end':
                endTurnBtn.style.display = 'block';
                break;
        }
    }
}

// 添加阶段按钮事件监听
function setupPhaseButtons() {
    // 进入战斗阶段按钮
    document.getElementById('enter-battle-phase').addEventListener('click', () => {
        gameState.socket.emit('enter_battle_phase', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            if (response.status === 'error') {
                alert(response.message);
            }
        });
    });
    
    // 进入结束阶段按钮
    document.getElementById('enter-end-phase').addEventListener('click', () => {
        gameState.socket.emit('enter_end_phase', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            if (response.status === 'error') {
                alert(response.message);
            }
        });
    });
    
    // 结束回合按钮
    document.getElementById('end-turn-btn').addEventListener('click', () => {
        gameState.socket.emit('end_turn', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            if (response.status === 'error') {
                alert(response.message);
            }
        });
    });
}
