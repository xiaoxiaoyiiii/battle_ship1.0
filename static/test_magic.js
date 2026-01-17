// 魔法卡测试工具 - 完整测试系统
class MagicTestSystem {
    constructor() {
        this.isOpen = false;
        this.container = null;
        this.initialize();
    }

    initialize() {
        this.createTestPanel();
        this.createTestButton();
        console.log("====== 魔法卡测试系统已初始化 ======");
    }

    createTestButton() {
        // 添加测试按钮
        const testButton = document.createElement('button');
        testButton.textContent = '魔法卡测试';
        testButton.id = 'test-magic-system';
        testButton.style.position = 'fixed';
        testButton.style.bottom = '20px';
        testButton.style.right = '20px';
        testButton.style.zIndex = '1000';
        testButton.style.padding = '10px 15px';
        testButton.style.backgroundColor = '#4CAF50';
        testButton.style.color = 'white';
        testButton.style.border = 'none';
        testButton.style.borderRadius = '5px';
        testButton.style.cursor = 'pointer';
        document.body.appendChild(testButton);
        
        testButton.addEventListener('click', () => this.toggleTestPanel());
    }

    createTestPanel() {
        // 创建测试面板容器
        this.container = document.createElement('div');
        this.container.id = 'magic-test-panel';
        this.container.style.position = 'fixed';
        this.container.style.bottom = '70px';
        this.container.style.right = '20px';
        this.container.style.width = '350px';
        this.container.style.height = '500px';
        this.container.style.backgroundColor = 'white';
        this.container.style.border = '1px solid #ccc';
        this.container.style.borderRadius = '8px';
        this.container.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
        this.container.style.padding = '15px';
        this.container.style.zIndex = '999';
        this.container.style.overflowY = 'auto';
        this.container.style.display = 'none';
        
        // 添加标题
        const title = document.createElement('h3');
        title.textContent = '魔法卡测试系统';
        title.style.marginTop = '0';
        title.style.borderBottom = '1px solid #eee';
        title.style.paddingBottom = '10px';
        this.container.appendChild(title);

        // 添加关闭按钮
        const closeBtn = document.createElement('button');
        closeBtn.textContent = '×';
        closeBtn.style.position = 'absolute';
        closeBtn.style.top = '10px';
        closeBtn.style.right = '10px';
        closeBtn.style.width = '30px';
        closeBtn.style.height = '30px';
        closeBtn.style.border = 'none';
        closeBtn.style.backgroundColor = '#f44336';
        closeBtn.style.color = 'white';
        closeBtn.style.borderRadius = '50%';
        closeBtn.style.cursor = 'pointer';
        closeBtn.addEventListener('click', () => this.toggleTestPanel());
        this.container.appendChild(closeBtn);

        // 添加状态信息
        const statusDiv = document.createElement('div');
        statusDiv.innerHTML = '<strong>状态:</strong> <span id="test-status">未连接</span>';
        statusDiv.style.marginBottom = '15px';
        statusDiv.style.fontSize = '14px';
        this.container.appendChild(statusDiv);

        // 添加测试功能区域
        this.addTestFunctions();

        // 添加游戏状态显示
        this.addGameStateDisplay();

        document.body.appendChild(this.container);
    }

    addTestFunctions() {
        // 功能区域容器
        const functionsDiv = document.createElement('div');
        functionsDiv.style.marginBottom = '20px';
        
        // 1. 获取所有魔法卡
        const getAllCardsBtn = document.createElement('button');
        getAllCardsBtn.textContent = '1. 获取所有魔法卡';
        getAllCardsBtn.style.width = '100%';
        getAllCardsBtn.style.padding = '10px';
        getAllCardsBtn.style.marginBottom = '8px';
        getAllCardsBtn.style.backgroundColor = '#4CAF50';
        getAllCardsBtn.style.color = 'white';
        getAllCardsBtn.style.border = 'none';
        getAllCardsBtn.style.borderRadius = '4px';
        getAllCardsBtn.style.cursor = 'pointer';
        getAllCardsBtn.addEventListener('click', () => this.getAllMagicCards());
        functionsDiv.appendChild(getAllCardsBtn);

        // 2. 设置船只数量
        const setShipsDiv = document.createElement('div');
        setShipsDiv.style.marginBottom = '15px';
        
        const setShipsLabel = document.createElement('label');
        setShipsLabel.textContent = '2. 设置船只数量:';
        setShipsLabel.style.display = 'block';
        setShipsLabel.style.marginBottom = '5px';
        
        const shipCountSelect = document.createElement('select');
        shipCountSelect.id = 'ship-count-select';
        for (let i = 1; i <= 6; i++) {
            const option = document.createElement('option');
            option.value = i;
            option.textContent = i;
            shipCountSelect.appendChild(option);
        }
        shipCountSelect.style.padding = '8px';
        shipCountSelect.style.marginRight = '8px';
        
        const setShipsBtn = document.createElement('button');
        setShipsBtn.textContent = '设置';
        setShipsBtn.style.padding = '8px 12px';
        setShipsBtn.style.backgroundColor = '#2196F3';
        setShipsBtn.style.color = 'white';
        setShipsBtn.style.border = 'none';
        setShipsBtn.style.borderRadius = '4px';
        setShipsBtn.style.cursor = 'pointer';
        setShipsBtn.addEventListener('click', () => this.setPlayerShips());
        
        setShipsDiv.appendChild(setShipsLabel);
        setShipsDiv.appendChild(shipCountSelect);
        setShipsDiv.appendChild(setShipsBtn);
        functionsDiv.appendChild(setShipsDiv);

        // 3. 清除所有效果
        const clearEffectsBtn = document.createElement('button');
        clearEffectsBtn.textContent = '3. 清除所有魔法效果';
        clearEffectsBtn.style.width = '100%';
        clearEffectsBtn.style.padding = '10px';
        clearEffectsBtn.style.marginBottom = '8px';
        clearEffectsBtn.style.backgroundColor = '#FF9800';
        clearEffectsBtn.style.color = 'white';
        clearEffectsBtn.style.border = 'none';
        clearEffectsBtn.style.borderRadius = '4px';
        clearEffectsBtn.style.cursor = 'pointer';
        clearEffectsBtn.addEventListener('click', () => this.clearAllEffects());
        functionsDiv.appendChild(clearEffectsBtn);

        // 4. 添加特定魔法卡
        const addSpecificCardDiv = document.createElement('div');
        addSpecificCardDiv.style.marginBottom = '15px';
        
        const addSpecificCardLabel = document.createElement('label');
        addSpecificCardLabel.textContent = '4. 添加特定魔法卡:';
        addSpecificCardLabel.style.display = 'block';
        addSpecificCardLabel.style.marginBottom = '5px';
        
        const cardNameInput = document.createElement('input');
        cardNameInput.id = 'card-name-input';
        cardNameInput.type = 'text';
        cardNameInput.placeholder = '输入魔法卡名称';
        cardNameInput.style.padding = '8px';
        cardNameInput.style.width = '60%';
        cardNameInput.style.marginRight = '8px';
        
        const addSpecificCardBtn = document.createElement('button');
        addSpecificCardBtn.textContent = '添加';
        addSpecificCardBtn.style.padding = '8px 12px';
        addSpecificCardBtn.style.backgroundColor = '#9C27B0';
        addSpecificCardBtn.style.color = 'white';
        addSpecificCardBtn.style.border = 'none';
        addSpecificCardBtn.style.borderRadius = '4px';
        addSpecificCardBtn.style.cursor = 'pointer';
        addSpecificCardBtn.addEventListener('click', () => this.addSpecificMagicCard());
        
        addSpecificCardDiv.appendChild(addSpecificCardLabel);
        addSpecificCardDiv.appendChild(cardNameInput);
        addSpecificCardDiv.appendChild(addSpecificCardBtn);
        functionsDiv.appendChild(addSpecificCardDiv);

        // 5. 刷新游戏状态
        const refreshStateBtn = document.createElement('button');
        refreshStateBtn.textContent = '5. 刷新游戏状态';
        refreshStateBtn.style.width = '100%';
        refreshStateBtn.style.padding = '10px';
        refreshStateBtn.style.marginBottom = '8px';
        refreshStateBtn.style.backgroundColor = '#795548';
        refreshStateBtn.style.color = 'white';
        refreshStateBtn.style.border = 'none';
        refreshStateBtn.style.borderRadius = '4px';
        refreshStateBtn.style.cursor = 'pointer';
        refreshStateBtn.addEventListener('click', () => this.getGameState());
        functionsDiv.appendChild(refreshStateBtn);

        this.container.appendChild(functionsDiv);
    }

    addGameStateDisplay() {
        // 游戏状态容器
        const stateDiv = document.createElement('div');
        stateDiv.innerHTML = '<h4>当前游戏状态</h4>';
        stateDiv.style.borderTop = '1px solid #eee';
        stateDiv.style.paddingTop = '15px';
        stateDiv.style.fontSize = '14px';
        
        // 状态信息
        const stateInfo = document.createElement('pre');
        stateInfo.id = 'game-state-info';
        stateInfo.style.backgroundColor = '#f5f5f5';
        stateInfo.style.padding = '10px';
        stateInfo.style.borderRadius = '4px';
        stateInfo.style.maxHeight = '200px';
        stateInfo.style.overflowY = 'auto';
        stateInfo.textContent = '点击"刷新游戏状态"查看详细信息';
        
        stateDiv.appendChild(stateInfo);
        this.container.appendChild(stateDiv);
    }

    toggleTestPanel() {
        if (!this.container) return;
        
        this.isOpen = !this.isOpen;
        this.container.style.display = this.isOpen ? 'block' : 'none';
        
        if (this.isOpen) {
            this.updateStatus();
            this.getGameState(); // 自动刷新状态
        }
    }

    updateStatus() {
        const statusSpan = document.getElementById('test-status');
        if (!statusSpan) return;
        
        if (!gameState.socket) {
            statusSpan.textContent = '未连接游戏';
            statusSpan.style.color = 'red';
        } else if (!gameState.roomId || !gameState.playerId) {
            statusSpan.textContent = '未加入房间';
            statusSpan.style.color = 'orange';
        } else {
            statusSpan.textContent = '已连接';
            statusSpan.style.color = 'green';
        }
    }

    getAllMagicCards() {
        if (!this.checkConnection()) return;
        
        console.log("正在获取所有魔法卡...");
        
        gameState.socket.emit('test_add_all_magic_cards', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            this.handleResponse(response, '获取所有魔法卡');
        });
    }

    setPlayerShips() {
        if (!this.checkConnection()) return;
        
        const shipCount = parseInt(document.getElementById('ship-count-select').value);
        if (isNaN(shipCount) || shipCount < 1 || shipCount > 6) {
            alert('请选择有效的船只数量(1-6)');
            return;
        }
        
        console.log(`正在设置船只数量为 ${shipCount}...`);
        
        gameState.socket.emit('test_set_player_ships', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            ship_count: shipCount
        }, (response) => {
            this.handleResponse(response, `设置船只数量为 ${shipCount}`);
        });
    }

    clearAllEffects() {
        if (!this.checkConnection()) return;
        
        console.log("正在清除所有魔法效果...");
        
        gameState.socket.emit('test_clear_all_effects', {
            room_id: gameState.roomId
        }, (response) => {
            this.handleResponse(response, '清除所有魔法效果');
        });
    }

    addSpecificMagicCard() {
        if (!this.checkConnection()) return;
        
        const cardName = document.getElementById('card-name-input').value.trim();
        if (!cardName) {
            alert('请输入魔法卡名称');
            return;
        }
        
        console.log(`正在添加魔法卡: ${cardName}...`);
        
        gameState.socket.emit('test_add_specific_magic_card', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            card_name: cardName
        }, (response) => {
            this.handleResponse(response, `添加魔法卡 ${cardName}`);
        });
    }

    getGameState() {
        if (!this.checkConnection()) return;
        
        console.log("正在获取游戏状态...");
        
        gameState.socket.emit('test_get_game_state', {
            room_id: gameState.roomId
        }, (response) => {
            if (response.status === 'success') {
                const stateInfo = document.getElementById('game-state-info');
                if (stateInfo) {
                    stateInfo.textContent = JSON.stringify(response.game_state, null, 2);
                }
                console.log("游戏状态已更新");
            } else {
                console.error(`获取游戏状态失败: ${response.message}`);
                alert(`获取游戏状态失败: ${response.message}`);
            }
        });
    }

    checkConnection() {
        if (!gameState.socket) {
            alert("未建立游戏连接，请先创建或加入房间");
            return false;
        }
        
        if (!gameState.roomId || !gameState.playerId) {
            alert("未加入房间，请先创建或加入房间");
            return false;
        }
        
        return true;
    }

    handleResponse(response, actionName) {
        if (response.status === 'success') {
            console.log(`${actionName}成功: ${response.message}`);
            alert(`${actionName}成功: ${response.message}`);
            this.getGameState(); // 自动刷新状态
        } else {
            console.error(`${actionName}失败: ${response.message}`);
            alert(`${actionName}失败: ${response.message}`);
        }
    }
}

// 初始化测试系统
let magicTestSystem;
window.addEventListener('load', function() {
    magicTestSystem = new MagicTestSystem();
    console.log("魔法卡测试系统已加载完成");
});

// 导出供外部使用
window.MagicTestSystem = MagicTestSystem;