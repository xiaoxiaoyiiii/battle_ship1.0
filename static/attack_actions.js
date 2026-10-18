// 攻击提交与攻击前的客户端门禁。
function handleAttack(x, y) {
    if (gameState.currentMagicCard || !gameState.isMyTurn) return;
    if (freezeAlert()) return;
    if (gameState.fieldMagic === '教皇旨意') {
        const left = parseInt(attacksRemaining.textContent, 10) || 0;
        if (left <= 0) {
            if (!gameState.hand || gameState.hand.length === 0) {
                showAlert('教皇旨意：攻击次数为 0，需要弃一张魔法卡换 2 次攻击，但你没有手牌');
                return;
            }
            showPapalDiscardChoice();
            return;
        }
    }
    if (gameState.currentPhase !== 'battle') {
        showAlert('当前不是战斗阶段');
        return;
    }
    if (attacksRemaining.textContent === '0') {
        showAlert('无剩余攻击次数');
        return;
    }
    gameState.socket.emit('attack', {
        room_id: gameState.roomId,
        player_id: gameState.playerId,
        x,
        y,
    }, (response) => {
        if (response && response.status === 'error') showAlert(response.message);
    });
}
