// 魔法卡测试工具 - 通过服务器获取所有魔法卡
function testMagicSystem() {
    console.log("====== 魔法卡测试工具 ======");
    
    // 添加Socket连接检查
    if (!gameState.socket) {
        console.error("错误: 未建立游戏连接，请先创建或加入房间");
        alert("请先创建或加入房间后再运行测试");
        return;
    }
    
    // 添加房间和玩家ID检查
    if (!gameState.roomId || !gameState.playerId) {
        console.error("错误: 未加入房间，请先创建或加入房间");
        alert("请先创建或加入房间后再运行测试");
        return;
    }
    
    console.log("正在通过服务器获取所有魔法卡...");
    
    // 发送请求到服务器，让服务器添加所有魔法卡到手牌
    gameState.socket.emit('test_add_all_magic_cards', {
        room_id: gameState.roomId,
        player_id: gameState.playerId
    }, (response) => {
        if (response.status === 'success') {
            console.log(response.message);
            console.log("魔法卡已添加到手牌，可开始测试魔法卡效果");
            alert("已获取所有魔法卡，可开始测试魔法卡效果");
        } else {
            console.error(`错误: ${response.message}`);
            alert(`获取魔法卡失败: ${response.message}`);
        }
    });
}

// 添加测试启动函数
window.addEventListener('load', function() {
    // 添加测试按钮
    const testButton = document.createElement('button');
    testButton.textContent = '获取所有魔法卡';
    testButton.id = 'test-magic-system';
    testButton.style.position = 'fixed';
    testButton.style.bottom = '20px';
    testButton.style.right = '20px';
    testButton.style.zIndex = '1000';
    document.body.appendChild(testButton);
    testButton.addEventListener('click', testMagicSystem);
    
    console.log("test_magic.js 加载完成，魔法卡测试工具已就绪");
});