// 魔法卡测试工具 - 直接获取所有魔法卡
function testMagicSystem() {
    console.log("====== 魔法卡测试工具 ======");
    
    // 添加Socket连接检查
    if (!gameState.socket) {
        console.error("错误: 未建立游戏连接，请先创建或加入房间");
        alert("请先创建或加入房间后再运行测试");
        return;
    }
    
    console.log("正在获取所有魔法卡...");
    
    // 直接将所有魔法卡添加到手牌
    gameState.hand = [...window.magicCards];
    
    // 清空牌堆和弃牌堆
    gameState.deck = [];
    gameState.discardPile = [];
    
    console.log(`已获取 ${gameState.hand.length} 张魔法卡`);
    console.log("魔法卡已添加到手牌，可开始测试魔法卡效果");
    
    // 更新手牌UI
    updateHandUI();
    
    // 显示提示信息
    alert("已获取所有魔法卡，可开始测试魔法卡效果");
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