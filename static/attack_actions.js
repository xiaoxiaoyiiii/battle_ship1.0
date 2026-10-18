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

function clearOpponentShieldedShips(positions) {
    const keys = new Set((Array.isArray(positions) ? positions : [])
        .filter(p => p && Number.isInteger(p.x) && Number.isInteger(p.y))
        .map(p => `${p.x},${p.y}`));
    if (!keys.size) return;
    gameState.opponentShieldedShips = (gameState.opponentShieldedShips || [])
        .filter(ship => !(ship || []).some(p => keys.has(`${p.x},${p.y}`)));
}

function updateAttackDisplay(result) {
    const mine = result.attacker === gameState.playerId;
    if (mine && result.ship_sunk) clearOpponentShieldedShips([{x: result.x, y: result.y}]);
    if (result.shield_blocked) {
        const sink = mine ? gameState.shieldBrokenMine : gameState.shieldBrokenOpponent;
        if (!sink.some(p => p.x === result.x && p.y === result.y)) {
            sink.push({x: result.x, y: result.y});
        }
        if (mine) {
            yourShips.textContent = result.attacker_remaining_ships;
            opponentShips.textContent = result.defender_remaining_ships;
        } else {
            yourShips.textContent = result.defender_remaining_ships;
            opponentShips.textContent = result.attacker_remaining_ships;
        }
        gameState.lastAttack = {
            x: result.x, y: result.y, attacker: result.attacker,
            hit: true, shipSunk: false, shieldBlocked: true,
        };
        initGameBoards();
        return;
    }
    if (mine) {
        gameState.shieldBrokenMine = (gameState.shieldBrokenMine || [])
            .filter(p => !(p.x === result.x && p.y === result.y));
        gameState.myAttacks.push({x: result.x, y: result.y, hit: result.hit});
        yourShips.textContent = result.attacker_remaining_ships;
        opponentShips.textContent = result.defender_remaining_ships;
    } else {
        gameState.shieldBrokenOpponent = (gameState.shieldBrokenOpponent || [])
            .filter(p => !(p.x === result.x && p.y === result.y));
        gameState.opponentAttacks.push({x: result.x, y: result.y, hit: result.hit});
        yourShips.textContent = result.defender_remaining_ships;
        opponentShips.textContent = result.attacker_remaining_ships;
    }
    gameState.lastAttack = {
        x: result.x, y: result.y, attacker: result.attacker,
        hit: result.hit, shipSunk: !!result.ship_sunk,
    };
    initGameBoards();
}
