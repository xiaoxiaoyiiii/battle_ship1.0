// 魔法卡测试工具 - 完整测试系统

// 添加深色模式全局样式
const darkModeStyles = `
.dark-theme * {
    transition: background-color 0.3s ease, color 0.3s ease, border-color 0.3s ease;
}

.dark-theme body {
    background-color: #1a202c;
    color: #e2e8f0;
}

.dark-theme #magic-test-panel {
    background-color: #2d3748;
    color: #e2e8f0;
    border-color: #4a5568;
}

.dark-theme #magic-test-panel h3, .dark-theme #magic-test-panel h4 {
    color: #f7fafc;
    border-bottom-color: #4a5568;
}

.dark-theme #magic-test-panel pre {
    background-color: #1a202c;
    color: #e2e8f0;
    border-color: #4a5568;
}

.dark-theme #magic-test-panel input, .dark-theme #magic-test-panel select {
    background-color: #4a5568;
    color: #e2e8f0;
    border-color: #718096;
}

.dark-theme #magic-test-panel input::placeholder {
    color: #a0aec0;
}

.dark-theme #test-status {
    color: #e2e8f0 !important;
}

.dark-theme #test-magic-system {
    background-color: #48bb78;
}

.dark-theme #theme-toggle-btn {
    background-color: #48bb78;
}
`;

// 添加样式到文档
const styleSheet = document.createElement('style');
styleSheet.textContent = darkModeStyles;
document.head.appendChild(styleSheet);
class MagicTestSystem {
    constructor() {
        this.isOpen = false;
        this.container = null;
        this.isDarkMode = false;
        this.initialize();
    }

    initialize() {
        this.initTheme();
        this.createTestPanel();
        this.createTestButton();
        console.log("====== 魔法卡测试系统已初始化 ======");
    }

    initTheme() {
        this.isDarkMode = localStorage.getItem('darkMode') === 'true' || 
                        (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        this.applyTheme();
    }

    applyTheme() {
        if (this.isDarkMode) {
            document.documentElement.classList.add('dark-theme');
        } else {
            document.documentElement.classList.remove('dark-theme');
        }
        localStorage.setItem('darkMode', this.isDarkMode);
        
        if (this.container) {
            this.updatePanelTheme();
        }
    }

    toggleTheme() {
        this.isDarkMode = !this.isDarkMode;
        this.applyTheme();
    }

    updatePanelTheme() {
        const panel = this.container;
        if (panel) {
            panel.style.backgroundColor = this.isDarkMode ? '#2d3748' : '#ffffff';
            panel.style.color = this.isDarkMode ? '#e2e8f0' : '#2d3748';
            panel.style.borderColor = this.isDarkMode ? '#4a5568' : '#ccc';
            
            const headers = panel.querySelectorAll('h3, h4');
            headers.forEach(h => {
                h.style.color = this.isDarkMode ? '#f7fafc' : '#1a202c';
                h.style.borderBottomColor = this.isDarkMode ? '#4a5568' : '#eee';
            });
            
            const pre = panel.querySelector('pre');
            if (pre) {
                pre.style.backgroundColor = this.isDarkMode ? '#1a202c' : '#f5f5f5';
                pre.style.color = this.isDarkMode ? '#e2e8f0' : '#2d3748';
            }
            
            const statusDiv = panel.querySelector('div');
            if (statusDiv) {
                const borders = panel.querySelectorAll('div');
                borders.forEach(border => {
                    if (border.style.borderTop) {
                        border.style.borderTopColor = this.isDarkMode ? '#4a5568' : '#eee';
                    }
                });
            }
        }
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
        this.container.style.width = '400px';
        this.container.style.height = '600px';
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

        // 添加主题切换按钮
        const themeBtn = document.createElement('button');
        themeBtn.textContent = '🌙';
        themeBtn.id = 'theme-toggle-btn';
        themeBtn.style.position = 'absolute';
        themeBtn.style.top = '10px';
        themeBtn.style.right = '50px';
        themeBtn.style.width = '30px';
        themeBtn.style.height = '30px';
        themeBtn.style.border = 'none';
        themeBtn.style.backgroundColor = '#4CAF50';
        themeBtn.style.color = 'white';
        themeBtn.style.borderRadius = '50%';
        themeBtn.style.cursor = 'pointer';
        themeBtn.addEventListener('click', () => this.toggleTheme());
        this.container.appendChild(themeBtn);

        // 添加状态信息
        const statusDiv = document.createElement('div');
        statusDiv.innerHTML = '<strong>状态:</strong> <span id="test-status">未连接</span>';
        statusDiv.style.marginBottom = '15px';
        statusDiv.style.fontSize = '14px';
        this.container.appendChild(statusDiv);

        // 添加测试功能区域
        this.addTestFunctions();

        // 添加高级测试功能区域
        this.addAdvancedTestFunctions();

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

    addAdvancedTestFunctions() {
        // 高级功能区域容器
        const advancedDiv = document.createElement('div');
        advancedDiv.innerHTML = '<h4 style="margin-top: 20px; margin-bottom: 15px;">高级测试功能</h4>';
        advancedDiv.style.borderTop = '1px solid #eee';
        advancedDiv.style.paddingTop = '15px';
        advancedDiv.style.marginTop = '15px';

        // 1. 重置游戏状态
        const resetGameBtn = document.createElement('button');
        resetGameBtn.textContent = '6. 重置游戏状态';
        resetGameBtn.style.width = '100%';
        resetGameBtn.style.padding = '10px';
        resetGameBtn.style.marginBottom = '8px';
        resetGameBtn.style.backgroundColor = '#f44336';
        resetGameBtn.style.color = 'white';
        resetGameBtn.style.border = 'none';
        resetGameBtn.style.borderRadius = '4px';
        resetGameBtn.style.cursor = 'pointer';
        resetGameBtn.addEventListener('click', () => this.resetGame());
        advancedDiv.appendChild(resetGameBtn);

        // 2. 设置对方船只数量
        const setOpponentShipsDiv = document.createElement('div');
        setOpponentShipsDiv.style.marginBottom = '15px';
        
        const setOpponentShipsLabel = document.createElement('label');
        setOpponentShipsLabel.textContent = '7. 设置对方船只数量:';
        setOpponentShipsLabel.style.display = 'block';
        setOpponentShipsLabel.style.marginBottom = '5px';
        
        const opponentShipCountSelect = document.createElement('select');
        opponentShipCountSelect.id = 'opponent-ship-count-select';
        for (let i = 1; i <= 6; i++) {
            const option = document.createElement('option');
            option.value = i;
            option.textContent = i;
            opponentShipCountSelect.appendChild(option);
        }
        opponentShipCountSelect.style.padding = '8px';
        opponentShipCountSelect.style.marginRight = '8px';
        
        const setOpponentShipsBtn = document.createElement('button');
        setOpponentShipsBtn.textContent = '设置';
        setOpponentShipsBtn.style.padding = '8px 12px';
        setOpponentShipsBtn.style.backgroundColor = '#3f51b5';
        setOpponentShipsBtn.style.color = 'white';
        setOpponentShipsBtn.style.border = 'none';
        setOpponentShipsBtn.style.borderRadius = '4px';
        setOpponentShipsBtn.style.cursor = 'pointer';
        setOpponentShipsBtn.addEventListener('click', () => this.setOpponentShips());
        
        setOpponentShipsDiv.appendChild(setOpponentShipsLabel);
        setOpponentShipsDiv.appendChild(opponentShipCountSelect);
        setOpponentShipsDiv.appendChild(setOpponentShipsBtn);
        advancedDiv.appendChild(setOpponentShipsDiv);

        // 3. 自动攻击功能
        const autoAttackDiv = document.createElement('div');
        autoAttackDiv.style.marginBottom = '15px';
        
        const autoAttackLabel = document.createElement('label');
        autoAttackLabel.textContent = '8. 自动攻击:';
        autoAttackLabel.style.display = 'block';
        autoAttackLabel.style.marginBottom = '5px';
        
        const autoAttackInput = document.createElement('input');
        autoAttackInput.id = 'auto-attack-count';
        autoAttackInput.type = 'number';
        autoAttackInput.min = '1';
        autoAttackInput.max = '20';
        autoAttackInput.value = '1';
        autoAttackInput.style.padding = '8px';
        autoAttackInput.style.width = '40%';
        autoAttackInput.style.marginRight = '8px';
        
        const autoAttackBtn = document.createElement('button');
        autoAttackBtn.textContent = '执行';
        autoAttackBtn.style.padding = '8px 12px';
        autoAttackBtn.style.backgroundColor = '#ff5722';
        autoAttackBtn.style.color = 'white';
        autoAttackBtn.style.border = 'none';
        autoAttackBtn.style.borderRadius = '4px';
        autoAttackBtn.style.cursor = 'pointer';
        autoAttackBtn.addEventListener('click', () => this.autoAttack());
        
        autoAttackDiv.appendChild(autoAttackLabel);
        autoAttackDiv.appendChild(autoAttackInput);
        autoAttackDiv.appendChild(autoAttackBtn);
        advancedDiv.appendChild(autoAttackDiv);

        // 4. 结束回合
        const endTurnBtn = document.createElement('button');
        endTurnBtn.textContent = '9. 结束回合';
        endTurnBtn.style.width = '100%';
        endTurnBtn.style.padding = '10px';
        endTurnBtn.style.marginBottom = '8px';
        endTurnBtn.style.backgroundColor = '#795548';
        endTurnBtn.style.color = 'white';
        endTurnBtn.style.border = 'none';
        endTurnBtn.style.borderRadius = '4px';
        endTurnBtn.style.cursor = 'pointer';
        endTurnBtn.addEventListener('click', () => this.endTurn());
        advancedDiv.appendChild(endTurnBtn);

        // 5. 直接胜利
        const winGameBtn = document.createElement('button');
        winGameBtn.textContent = '10. 直接胜利';
        winGameBtn.style.width = '100%';
        winGameBtn.style.padding = '10px';
        winGameBtn.style.marginBottom = '8px';
        winGameBtn.style.backgroundColor = '#4caf50';
        winGameBtn.style.color = 'white';
        winGameBtn.style.border = 'none';
        winGameBtn.style.borderRadius = '4px';
        winGameBtn.style.cursor = 'pointer';
        winGameBtn.addEventListener('click', () => this.winGame());
        advancedDiv.appendChild(winGameBtn);

        // 6. 直接失败
        const loseGameBtn = document.createElement('button');
        loseGameBtn.textContent = '11. 直接失败';
        loseGameBtn.style.width = '100%';
        loseGameBtn.style.padding = '10px';
        loseGameBtn.style.marginBottom = '8px';
        loseGameBtn.style.backgroundColor = '#9c27b0';
        loseGameBtn.style.color = 'white';
        loseGameBtn.style.border = 'none';
        loseGameBtn.style.borderRadius = '4px';
        loseGameBtn.style.cursor = 'pointer';
        loseGameBtn.addEventListener('click', () => this.loseGame());
        advancedDiv.appendChild(loseGameBtn);

        // 7. 获取魔法卡列表
        const getMagicCardsListBtn = document.createElement('button');
        getMagicCardsListBtn.textContent = '12. 获取魔法卡列表';
        getMagicCardsListBtn.style.width = '100%';
        getMagicCardsListBtn.style.padding = '10px';
        getMagicCardsListBtn.style.marginBottom = '8px';
        getMagicCardsListBtn.style.backgroundColor = '#ff9800';
        getMagicCardsListBtn.style.color = 'white';
        getMagicCardsListBtn.style.border = 'none';
        getMagicCardsListBtn.style.borderRadius = '4px';
        getMagicCardsListBtn.style.cursor = 'pointer';
        getMagicCardsListBtn.addEventListener('click', () => this.getMagicCardsList());
        advancedDiv.appendChild(getMagicCardsListBtn);

        this.container.appendChild(advancedDiv);
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
            this.updatePanelTheme(); // 确保主题正确应用
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

    // 高级功能实现
    resetGame() {
        if (!this.checkConnection()) return;
        
        console.log("正在重置游戏状态...");
        
        gameState.socket.emit('test_reset_game', {
            room_id: gameState.roomId
        }, (response) => {
            this.handleResponse(response, '重置游戏状态');
        });
    }

    setOpponentShips() {
        if (!this.checkConnection()) return;
        
        const shipCount = parseInt(document.getElementById('opponent-ship-count-select').value);
        if (isNaN(shipCount) || shipCount < 1 || shipCount > 6) {
            alert('请选择有效的船只数量(1-6)');
            return;
        }
        
        console.log(`正在设置对方船只数量为 ${shipCount}...`);
        
        gameState.socket.emit('test_set_opponent_ships', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            ship_count: shipCount
        }, (response) => {
            this.handleResponse(response, `设置对方船只数量为 ${shipCount}`);
        });
    }

    endTurn() {
        if (!this.checkConnection()) return;
        
        console.log("正在结束回合...");
        
        gameState.socket.emit('test_end_turn', {
            room_id: gameState.roomId
        }, (response) => {
            this.handleResponse(response, '结束回合');
        });
    }

    winGame() {
        if (!this.checkConnection()) return;
        
        console.log("正在设置游戏胜利...");
        
        gameState.socket.emit('test_win_game', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            this.handleResponse(response, '设置游戏胜利');
        });
    }

    loseGame() {
        if (!this.checkConnection()) return;
        
        console.log("正在设置游戏失败...");
        
        gameState.socket.emit('test_lose_game', {
            room_id: gameState.roomId,
            player_id: gameState.playerId
        }, (response) => {
            this.handleResponse(response, '设置游戏失败');
        });
    }

    getMagicCardsList() {
        if (!this.checkConnection()) return;
        
        console.log("正在获取魔法卡列表...");
        
        gameState.socket.emit('test_get_magic_cards_list', {}, (response) => {
            if (response.status === 'success') {
                console.log("魔法卡列表:", response.magic_cards);
                
                // 显示魔法卡列表
                const cardsList = response.magic_cards;
                let cardsText = "可用魔法卡列表:\n\n";
                
                cardsList.forEach((card, index) => {
                    cardsText += `${index + 1}. ${card.name} (速度: ${card.speed}, 类型: ${card.type})\n`;
                    cardsText += `   描述: ${card.description}\n\n`;
                });
                
                alert(cardsText);
            } else {
                console.error(`获取魔法卡列表失败: ${response.message}`);
                alert(`获取魔法卡列表失败: ${response.message}`);
            }
        });
    }

    autoAttack() {
        if (!this.checkConnection()) return;
        
        const attackCount = parseInt(document.getElementById('auto-attack-count').value);
        if (isNaN(attackCount) || attackCount < 1 || attackCount > 20) {
            alert('请输入有效的攻击次数(1-20)');
            return;
        }
        
        console.log(`正在执行 ${attackCount} 次自动攻击...`);
        
        gameState.socket.emit('test_auto_attack', {
            room_id: gameState.roomId,
            player_id: gameState.playerId,
            count: attackCount
        }, (response) => {
            if (response.status === 'success') {
                console.log("自动攻击结果:", response.attack_results);
                
                // 显示攻击结果
                const results = response.attack_results;
                let resultsText = `自动攻击完成! 共执行 ${results.length} 次攻击:\n\n`;
                
                results.forEach((result, index) => {
                    const hitText = result.hit ? '命中' : '未命中';
                    const sunkText = result.ship_sunk ? '(击沉!' : ')';
                    resultsText += `${index + 1}. 位置(${result.x}, ${result.y}): ${hitText} ${sunkText}\n`;
                });
                
                resultsText += `\n${response.message}`;
                alert(resultsText);
                this.getGameState(); // 刷新状态
            } else {
                console.error(`自动攻击失败: ${response.message}`);
                alert(`自动攻击失败: ${response.message}`);
            }
        });
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