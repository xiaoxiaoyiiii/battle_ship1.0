/* Broadcast-only feedback for completed magic-card effects. */

function applyCardEffect(card, casterId) {
    console.log(`应用魔法效果: ${card.name}`);
    // 显示魔法效果动画
    showMagicAnimation(card);

    switch (card.name) {
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
                room_id: gameState.roomId,
                player_id: gameState.playerId
            });
            break;

        case '越战越勇':
            showMessage('越战越勇效果生效，接下来击沉对方战舰时攻击次数净增加1');
            break;

        case '神威！':
            showMessage('神威！生效，目标区域战舰被暂时除外');
            break;

        case '冻结':
            showMessage('冻结效果生效，目标区域战舰被冻结');
            break;

        case '轰炸':
            showMessage('轰炸效果生效，目标行/列受到攻击');
            // 轰炸的实际结算走 use_magic_card（target_line）链路，此处无需额外请求
            break;

        case '探测雷达':
            showMessage('探测雷达效果生效，已显示目标区域战舰');
            gameState.socket.emit('request_revealed_positions', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            });
            break;

        case '饮血':
            showMessage('饮血效果生效，接下来每击杀一艘船抽一张牌');
            break;

        case '克苏鲁之眼':
            showMessage('克苏鲁之眼效果生效，双方各暴露一艘战舰位置');
            gameState.socket.emit('request_revealed_positions', {
                room_id: gameState.roomId,
                player_id: gameState.playerId
            });
            break;

        case 'Freezing！':
            showMessage('Freezing效果生效，对方回合被跳过');
            break;

        case '明智埋葬':
            // 这一刻还什么都没埋、也没摸牌（要等玩家点选后服务端才结算）。
            // 旧文案「埋葬卡牌并抽一张新牌」会让人以为效果已完成 —— 而且双方都会看到。
            showMessage(casterId === gameState.playerId
                ? '明智埋葬：请选择要埋葬的卡牌（牌堆或对方手牌）'
                : '对方发动了明智埋葬，正在选择要埋葬的卡牌');
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
            // 角标不在这里挂 —— 由服务端 active_effects 广播统一渲染。
            // 以前这里是 `indicatorBox.innerHTML += ...`，只加不删：
            // 服务端其实每回合切换就把 subsidy 清掉了，角标却永远亮着，
            // 玩家会以为效果是永久的。
            break;

        case '绝处逢生':
            // ★ 2026-09-20 同批修：绝处逢生也只重摆**施法者自己**的棋盘
            // （服务端只清 caster 的船）。这里以前不看 casterId 就 `initBoard`,
            // 会把**对手本地那份棋盘状态**一起抹掉 —— 对手的船明明还在，
            // 界面上却被清空了。与上面回光返照是同一个形状的缺陷。
            if (casterId && casterId !== gameState.playerId) {
                showMessage('对方发动了绝处逢生，击杀其任何一艘战舰可直接获胜');
                break;
            }
            showMessage('绝处逢生效果生效，击杀任何船直接获胜');
            // 重新初始化棋盘
            initBoard(playerBoard, true);
            gameState.ships = [];
            gameState.placedShips = 0;
            shipsPlaced.textContent = '0';
            // 卡牌重摆 = 一个新的部署阶段（A04：绝处逢生会再走一次 place_ships）
            newDeployPhase('last_stand_redeploy');
            break;

        case '死者苏生':
        case '疗愈':
            showMessage('复活效果生效，战舰已复活');
            break;

        case '盗亦有道':
            showMessage('盗亦有道效果生效，获取对方上一张魔法卡');
            break;

        case '回光返照':
            // ★ 2026-09-20 修：界面不再由这里驱动 —— 改走服务端的 `reset_gameboard`
            //（按 sid 单发给施法者，见 server.py 回光返照分支）。
            //
            // 为什么必须改掉：本函数是**广播**处理器（双方都会跑），
            // 在这里 `switchScreen(shipPlacementScreen)` 会把**对手**也拽进布船界面
            // （作者实测：「对手也需要重新布船」）。
            // 而且"谁该重摆"这件事一旦这里也判一遍，就等于**两份实现** ——
            // 本项目的老病根（第 10 节第 1 条）。服务端 `room.state='placing_ships'`
            // + 单发 `reset_gameboard` 已经是唯一真相。
            //
            // 这里只负责给双方各一句提示。
            showMessage(casterId === gameState.playerId
                ? '回光返照生效，请重新摆放战舰'
                : '对方发动了回光返照，正在重新摆放战舰');
            break;

        case '加百列之光':
            // 场地拆除完全交给服务端：它按 field_magic_owner 判断归属，
            // 只拆对方的场地，并广播 field_magic_updated 刷新双方 UI。
            // 这里此前又 emit 了一次 remove_field_magic，而服务端允许归属者
            // 删除自己的场地 —— 施法者自己的场地就这样被前端「补刀」拆掉了。
            showMessage('加百列之光效果生效，对方魔法和场地魔法被无效化');
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
            updateFieldMagicUI(casterId || gameState.playerId, card);
            break;

        case '禁忌果实':
            showMessage('场地魔法【禁忌果实】生效，双方只能使用失灵！和场地魔法');
            updateFieldMagicUI(casterId || gameState.playerId, card);
            break;

        case '伊甸园':
            showMessage('场地魔法【伊甸园】生效，攻击次数变为6-n');
            updateFieldMagicUI(casterId || gameState.playerId, card);
            break;

        case '教皇旨意':
            showMessage('场地魔法【教皇旨意】生效，攻击需要弃置魔法卡');
            updateFieldMagicUI(casterId || gameState.playerId, card);
            break;

        // 判定魔法卡：命运骰子的动画与效果播报由 dice_rolled 事件统一驱动
        // （双方都收到，能同步看到同一个骰子结果）。
        case '命运骰子':
            // 不在这里显示，避免与 dice_rolled 事件重复
            break;

        // 判定魔法卡：无忧梦呓打出时**不摇骰子**（只登记延迟拼点），
        // 所以这里也不该弹任何东西 —— 动画与播报发生在**对方回合开始时**的
        // dice_rolled 事件里。抢在这里报"效果生效"会与那一刻的真实结果打架。
        case '无忧梦呓':
            break;

        // 已实现的魔法卡
        case '失灵！':
            showMessage('失灵！效果生效，对方魔法被无效化');
            break;

        case '看破！':
            showMessage('看破！效果生效，本回合对方魔法卡被无效化');
            break;

        case '增援':
            showMessage('增援效果生效，请选择部署位置');
            break;
    }
}
