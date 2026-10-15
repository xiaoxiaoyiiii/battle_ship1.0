/* Interactive target-selection UI for magic cards. */

function showMagicTargetSelection(card, index) {
    // 自愈：上次选区若没清理干净，先收尾（否则 selectingOnBoard 卡住，界面出不来又关不掉）
    if (typeof gameState.selectionCleanup === 'function') {
        try { gameState.selectionCleanup(); } catch (_) { }
        gameState.selectionCleanup = null;
    }
    gameState.selectingOnBoard = false;
    document.querySelectorAll('.magic-target-prompt').forEach(el => el.remove());
    document.querySelectorAll('.area-picker-bar').forEach(el => el.remove());
    document.querySelectorAll('.cell.selection-highlight').forEach(c => c.classList.remove('selection-highlight'));

    // 记录当前待选卡和索引，供确认时使用
    gameState.currentMagicCard = card;
    gameState.currentCardIndex = index;

    const targetPrompt = document.createElement('div');
    targetPrompt.className = 'magic-target-prompt';

    const descriptor = needsTargetSelection(card.name);

    if (!descriptor) {
        showAlert('此卡不需要选择目标');
        return;
    }

    // Helper to cleanup prompt and selection mode
    function cleanupPrompt() {
        if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
        if (typeof gameState.selectionCleanup === 'function') {
            gameState.selectionCleanup();
            gameState.selectionCleanup = null;
        }
        gameState.currentMagicCard = null;
        gameState.currentCardIndex = null;
        gameState.pendingChainCard = null;
        gameState.pendingPriorityCard = null;
        gameState.pendingEffectChoice = null;
    }

    // AREA selection (square) —— 点选定位 + 确认，触摸可用
    if (descriptor.type === 'area') {
        const size = descriptor.size;
        // 提示与确认合并在同一条浮动条上。
        // 此前这里会再挂一个 .magic-target-prompt 裸 div，而那个类名当时
        // 【没有任何 CSS】—— 等于玩家只看得到一条确认条，不知道要点棋盘。
        const picker = createBoardAreaPicker(opponentBoard, size, (areaObj) => {
            confirmMagicTarget(areaObj);
            cleanupPrompt();
        }, cleanupPrompt, {
            title: `在对手棋盘上选择 ${size}×${size} 区域`,
            hint: '点一下棋盘定位，可以随时改点；虚线是可选落点',
            cardName: card.name,
            pendingText: `在棋盘上选 ${size}×${size} 区域…`,
        });
        gameState.selectionCleanup = picker ? picker.cleanup : null;
        return;
    }

    // 神威！—— 先选己方/对方棋盘，再点选 3x3 区域
    if (descriptor.type === 'shenwei') {
        targetPrompt.innerHTML = `
            <h3>神威！— 选择作用棋盘</h3>
            <p class="magic-hint">己方：仅除外与回归；对方：区域仅 1 艘船时直接击沉</p>
            <div class="shenwei-board-picker">
                <button id="shenwei-pick-self">己方棋盘</button>
                <button id="shenwei-pick-opp">对方棋盘</button>
            </div>
            <div style="text-align:center;margin-top:10px;">
                <button id="cancel-target">取消</button>
            </div>
        `;
        document.body.appendChild(targetPrompt);
        document.getElementById('cancel-target').addEventListener('click', cleanupPrompt);
        document.getElementById('shenwei-pick-self').addEventListener('click', () => {
            targetPrompt.innerHTML = `
                <h3>神威！— 在己方棋盘点选 3x3 区域</h3>
                <p class="magic-hint">点一下定位区域，再点「确认」</p>
            `;
            const picker = createBoardAreaPicker(gamePlayerBoard, 3, (areaObj) => {
                confirmMagicTarget(Object.assign({ board: 'self' }, areaObj));
                cleanupPrompt();
            }, cleanupPrompt, {
                cardName: card.name,
                pendingText: '在己方棋盘上选 3×3 区域…',
            });
            gameState.selectionCleanup = picker ? picker.cleanup : null;
        });
        document.getElementById('shenwei-pick-opp').addEventListener('click', () => {
            targetPrompt.innerHTML = `
                <h3>神威！— 在对方棋盘点选 3x3 区域</h3>
                <p class="magic-hint">点一下定位区域，再点「确认」</p>
            `;
            const picker = createBoardAreaPicker(opponentBoard, 3, (areaObj) => {
                confirmMagicTarget(Object.assign({ board: 'opponent' }, areaObj));
                cleanupPrompt();
            }, cleanupPrompt, {
                cardName: card.name,
                pendingText: '在对方棋盘上选 3×3 区域…',
            });
            gameState.selectionCleanup = picker ? picker.cleanup : null;
        });
        return;
    }

    // LINE selection (row or column) e.g., 轰炸 — 方向切换 + 点选定位 + **显式确认**
    // ⚠️ Phase 4：旧实现在 mouseup 上直接 confirmIndex()（拖到哪就打到哪，松手即生效）。
    //    按 Balatro 的「先选后确认」，拖拽/点击只**定位**，必须再点「确认使用 轰炸！」才提交。
    if (descriptor.type === 'line') {
        // ⚠️ 样式统一在 style.css 的「范围选择的选中态」一节里定义。
        // 这里原本会注入一段 <style id="magic-selection-styles">，而下面的
        // 「连选」分支用的是【同一个 id】—— 谁先打开谁生效，后打开的那种模式
        // 样式永远不生效（实测：先开轰炸再开硫磺火焰，绿色变成了橙红色）。
        targetPrompt.innerHTML = `
            <h3>选择一整行/列</h3>
            <p id="line-picker-info" class="selection-info pending">点击或拖拽到目标行/列（虚线是可选落点）</p>
            <div class="magic-selection-controls">
                <button id="toggle-line-dir">方向：行</button>
                <button id="confirm-line-target" disabled>在棋盘上选整行/整列…</button>
                <button id="cancel-target">取消</button>
            </div>
        `;
        document.body.appendChild(targetPrompt);

        const boardEl = opponentBoard;
        if (!boardEl) return;
        gameState.selectingOnBoard = true;

        let mode = 'row'; // 'row' or 'col'
        let picked = null;      // 已定位的行/列号（还没确认）
        let invalidMsg = '';
        const toggleBtn = document.getElementById('toggle-line-dir');
        toggleBtn.addEventListener('click', () => {
            mode = mode === 'row' ? 'col' : 'row';
            toggleBtn.textContent = `方向：${mode === 'row' ? '行' : '列'}`;
            picked = null;
            clearHighlights();
            showAnchors();
            syncBar();
        });

        const cells = Array.from(boardEl.querySelectorAll('.cell'));
        let isMouseDown = false;
        let lastIndex = null;

        // 合法落点虚框锚点：整行 = 每行的任意格；整列 = 每列的任意格
        function showAnchors() {
            cells.forEach(c => c.classList.add('sel-anchor'));
        }
        function clearAnchors() {
            cells.forEach(c => c.classList.remove('sel-anchor'));
        }

        function syncBar() {
            const btn = document.getElementById('confirm-line-target');
            const info = document.getElementById('line-picker-info');
            if (btn) {
                if (invalidMsg) { btn.disabled = true; btn.textContent = invalidMsg; }
                else if (picked === null) {
                    btn.disabled = true;
                    btn.textContent = `在棋盘上选整${mode === 'row' ? '行' : '列'}…`;
                } else {
                    btn.disabled = false;
                    btn.textContent = `确认使用 ${card.name}！`;
                }
            }
            if (info && picked === null && !invalidMsg) {
                info.className = 'selection-info pending';
                info.textContent = `当前方向：整${mode === 'row' ? '行' : '列'} — 点棋盘定位`;
            }
        }

        function clearHighlights() {
            cells.forEach(c => c.classList.remove('magic-selection-overlay', 'col', 'sel-mode-line', 'sel-invalid'));
        }

        // 悬停预览：只改视觉与提示文字，**不写 picked**（不然鼠标划过一路就把落点定了）。
        function previewIndex(idx) {
            clearHighlights();
            if (mode === 'row') {
                boardEl.querySelectorAll(`.cell[data-y="${idx}"]`).forEach(c => c.classList.add('magic-selection-overlay', 'sel-mode-line'));
            } else {
                boardEl.querySelectorAll(`.cell[data-x="${idx}"]`).forEach(c => c.classList.add('magic-selection-overlay', 'col', 'sel-mode-line'));
            }
            const info = document.getElementById('line-picker-info');
            if (info) {
                info.className = 'selection-info pending';
                info.innerHTML = '<span class="sel-dot"></span>' +
                    (mode === 'row' ? `预览：第 ${idx + 1} 行 — 点一下定位` : `预览：第 ${idx + 1} 列 — 点一下定位`);
            }
        }

        function highlightIndex(idx) {
            clearHighlights();
            clearAnchors();
            invalidMsg = '';
            if (mode === 'row') {
                boardEl.querySelectorAll(`.cell[data-y="${idx}"]`).forEach(c => c.classList.add('magic-selection-overlay', 'sel-mode-line'));
            } else {
                boardEl.querySelectorAll(`.cell[data-x="${idx}"]`).forEach(c => c.classList.add('magic-selection-overlay', 'col', 'sel-mode-line'));
            }
            picked = idx;   // 只定位，不提交 —— 提交由确认按钮负责（Phase 4）
            // 说清楚落在哪一行/列 —— 旧实现只有一片几乎看不见的淡色，玩家无法确认落点。
            const info = document.getElementById('line-picker-info');
            if (info) {
                info.className = 'selection-info';
                info.innerHTML = '<span class="sel-dot"></span>' +
                    (mode === 'row'
                        ? `已选中：第 ${idx + 1} 行（整行 6 格）`
                        : `已选中：第 ${idx + 1} 列（整列 6 格）`);
            }
            syncBar();
        }

        function confirmIndex(idx) {
            if (idx === null || idx === undefined) return;
            if (mode === 'row') confirmMagicTarget({ target_line: { type: 'row', index: idx } });
            else confirmMagicTarget({ target_line: { type: 'col', index: idx } });
            cleanupAll();
        }

        cells.forEach(cell => {
            const mx = parseInt(cell.dataset.x, 10);
            const my = parseInt(cell.dataset.y, 10);

            // 拖拽/点击只**定位**（Phase 4：松手不再自动开火），提交一律走确认按钮
            const onMouseDown = (e) => {
                e.preventDefault();
                e.stopPropagation();
                isMouseDown = true;
                lastIndex = mode === 'row' ? my : mx;
                highlightIndex(lastIndex);
                const onUp = () => {
                    isMouseDown = false;
                    window.removeEventListener('mouseup', onUp);
                };
                window.addEventListener('mouseup', onUp);
            };

            const onEnter = () => {
                if (isMouseDown) {
                    lastIndex = mode === 'row' ? my : mx;
                    highlightIndex(lastIndex);
                } else if (picked === null) {
                    previewIndex(mode === 'row' ? my : mx);   // 悬停预览（不定位）
                }
            };

            const onLeave = () => {
                if (isMouseDown) return;
                if (picked === null) clearHighlights();
                else highlightIndex(picked);   // 回到已定位的那一行/列
            };

            const onClick = (e) => {
                e.stopPropagation();
                e.preventDefault();
                highlightIndex(mode === 'row' ? my : mx);
            };

            cell.addEventListener('mousedown', onMouseDown, true);
            cell.addEventListener('mouseenter', onEnter);
            cell.addEventListener('mouseleave', onLeave);
            cell.addEventListener('click', onClick, true);
            // store for cleanup
            (cell._magicHandlers = cell._magicHandlers || []).push({
                type: 'line',
                handlers: { onMouseDown, onEnter, onLeave, onClick }
            });
        });

        function cleanupAll() {
            cells.forEach(cell => {
                if (cell._magicHandlers) {
                    cell._magicHandlers.filter(h => h.type === 'line').forEach(h => {
                        const { onMouseDown, onEnter, onLeave, onClick } = h.handlers;
                        cell.removeEventListener('mousedown', onMouseDown, true);
                        cell.removeEventListener('mouseenter', onEnter);
                        cell.removeEventListener('mouseleave', onLeave);
                        cell.removeEventListener('click', onClick, true);
                    });
                }
                cell.classList.remove('magic-selection-overlay', 'col', 'sel-mode-line', 'sel-anchor', 'sel-invalid');
            });
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
            document.removeEventListener('click', onDocClick, true);
            gameState.selectingOnBoard = false;
            gameState.selectionCleanup = null;
        }

        // 点空白 = 取消（不消耗卡）
        const onDocClick = (e) => {
            if (targetPrompt.contains(e.target)) return;
            if (e.target.closest && e.target.closest('.cell')) return;
            if (e.target.closest && e.target.closest('#magic-hand')) return;
            cleanupAll();
            cleanupPrompt();
        };
        setTimeout(() => document.addEventListener('click', onDocClick, true), 0);

        document.getElementById('cancel-target').addEventListener('click', cleanupAll);
        document.getElementById('confirm-line-target').addEventListener('click', () => {
            if (picked === null) { showAlert(`请先在棋盘上点选一整${mode === 'row' ? '行' : '列'}`); return; }
            confirmIndex(picked);
        });
        clearAnchors();
        showAnchors();
        syncBar();
        gameState.selectionCleanup = cleanupAll;
        return;
    }

    // CONTINUOUS selection (自由连续 n 格) e.g., 硫磺火焰 — 自由连选 6 格
    if (descriptor.type === 'continuous') {
        const L = descriptor.length;
        // 样式统一在 style.css（见「范围选择的选中态」一节的说明：
        // 这里原本注入的 <style> 与「整行整列」分支抢同一个 id，互相覆盖）。

        targetPrompt.innerHTML = `
            <h3>自由选择连续 ${L} 个格子（点击选中/取消，每个新增格需与已选格相邻）</h3>
            <p id="cont-picker-info" class="selection-info pending">已选 0 / ${L} 格</p>
            <div style="text-align:center;margin-top:8px;">
                <button id="confirm-continuous" disabled>还需 ${L} 格…</button>
                <button id="cancel-target">取消</button>
            </div>
        `;
        document.body.appendChild(targetPrompt);

        const boardEl = opponentBoard;
        if (!boardEl) return;
        gameState.selectingOnBoard = true;

        const cells = Array.from(boardEl.querySelectorAll('.cell'));
        const selected = new Set();

        const key = (x, y) => `${x},${y}`;
        const parseKey = (k) => k.split(',').map(Number);

        function isAdjacentToSelected(x, y) {
            if (selected.size === 0) return true;
            for (const k of selected) {
                const [sx, sy] = parseKey(k);
                if (Math.abs(sx - x) + Math.abs(sy - y) === 1) return true;
            }
            return false;
        }

        function isConnected(setLike) {
            if (setLike.size <= 1) return true;
            const arr = Array.from(setLike);
            const [startX, startY] = parseKey(arr[0]);
            const visited = new Set();
            const stack = [[startX, startY]];
            const lookup = new Set(arr);
            while (stack.length) {
                const [cx, cy] = stack.pop();
                const ck = key(cx, cy);
                if (visited.has(ck)) continue;
                visited.add(ck);
                const neighbors = [
                    [cx + 1, cy],
                    [cx - 1, cy],
                    [cx, cy + 1],
                    [cx, cy - 1]
                ];
                neighbors.forEach(([nx, ny]) => {
                    const nk = key(nx, ny);
                    if (lookup.has(nk) && !visited.has(nk)) stack.push([nx, ny]);
                });
            }
            return visited.size === setLike.size;
        }

        function refreshHighlights() {
            cells.forEach(c => c.classList.remove('magic-selection-overlay', 'vert', 'sel-mode-cont', 'sel-anchor', 'sel-invalid'));
            cells.forEach(c => {
                const cx = parseInt(c.dataset.x, 10);
                const cy = parseInt(c.dataset.y, 10);
                if (selected.has(key(cx, cy))) c.classList.add('magic-selection-overlay', 'sel-mode-cont');
            });
            // 实时报数 + 未选满就禁用确认，玩家不用自己数格子。
            const info = document.getElementById('cont-picker-info');
            if (info) {
                if (selected.size === L) {
                    info.className = 'selection-info';
                    info.innerHTML = `<span class="sel-dot"></span>已选 ${selected.size} / ${L} 格 — 可以确认了`;
                } else {
                    info.className = 'selection-info pending';
                    info.textContent = `已选 ${selected.size} / ${L} 格（还需 ${L - selected.size} 格）`;
                }
            }
            // 确认按钮文案随状态变：未满 = 置灰报还差几格；选满 = 「确认使用 <卡名>！」
            const okBtn = document.getElementById('confirm-continuous');
            if (okBtn) {
                okBtn.disabled = selected.size !== L;
                okBtn.textContent = (selected.size === L) ? `确认使用 ${card.name}！` : `还需 ${L - selected.size} 格…`;
            }
        }

        // 非法（不相邻 / 超量）不进提交路径：相关格子画红框 + 确认按钮置灰。
        // 旧实现只弹一个 alert，棋盘上什么标记都没有，玩家看不出「哪一格不合法」。
        function flashInvalid(cellLike, msg) {
            const cell = cellLike;
            if (cell && cell.classList) {
                cell.classList.add('sel-invalid');
                setTimeout(() => cell.classList.remove('sel-invalid'), 900);
            }
            const okBtn = document.getElementById('confirm-continuous');
            if (okBtn) {
                okBtn.disabled = true;
                okBtn.textContent = msg;
                setTimeout(refreshHighlights, 900);
            }
        }

        cells.forEach(cell => {
            const mx = parseInt(cell.dataset.x, 10);
            const my = parseInt(cell.dataset.y, 10);
            cell.style.cursor = 'pointer';

            const onClick = (e) => {
                e.stopPropagation();
                e.preventDefault();
                const k = key(mx, my);
                if (selected.has(k)) {
                    const temp = new Set(selected);
                    temp.delete(k);
                    if (temp.size > 0 && !isConnected(temp)) {
                        flashInvalid(cell, '不连续');
                        showAlert('移除该格会导致不连续，请选择其他格子');
                        return;
                    }
                    selected.delete(k);
                    refreshHighlights();
                    return;
                }

                if (selected.size >= L) {
                    flashInvalid(cell, `最多 ${L} 格`);
                    showAlert(`最多只能选择 ${L} 个格子`);
                    return;
                }
                if (!isAdjacentToSelected(mx, my)) {
                    flashInvalid(cell, '需相邻');
                    showAlert('新增格子需与已选格子相邻');
                    return;
                }
                selected.add(k);
                refreshHighlights();
            };

            cell.addEventListener('click', onClick, true);
            (cell._magicHandlers = cell._magicHandlers || []).push({
                type: 'continuous',
                handlers: { onClick }
            });
        });

        function cleanupAll() {
            cells.forEach(cell => {
                if (cell._magicHandlers) {
                    cell._magicHandlers.filter(h => h.type === 'continuous').forEach(h => {
                        const { onClick } = h.handlers;
                        cell.removeEventListener('click', onClick, true);
                    });
                }
                cell.classList.remove('magic-selection-overlay', 'vert', 'sel-mode-cont', 'sel-anchor', 'sel-invalid');
                cell.style.cursor = '';
            });
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
            document.removeEventListener('click', onDocClick, true);
            gameState.selectingOnBoard = false;
            gameState.selectionCleanup = null;
        }

        // 点空白 = 取消（不消耗卡）
        const onDocClick = (e) => {
            if (targetPrompt.contains(e.target)) return;
            if (e.target.closest && e.target.closest('.cell')) return;
            if (e.target.closest && e.target.closest('#magic-hand')) return;
            cleanupAll();
            cleanupPrompt();
        };
        setTimeout(() => document.addEventListener('click', onDocClick, true), 0);
        // 合法落点虚框锚点：连选模式下每格都能当起点
        cells.forEach(c => { if (!selected.has(key(parseInt(c.dataset.x, 10), parseInt(c.dataset.y, 10)))) c.classList.add('sel-anchor'); });

        document.getElementById('cancel-target').addEventListener('click', cleanupAll);
        document.getElementById('confirm-continuous').addEventListener('click', () => {
            if (selected.size !== L) {
                showAlert(`需要选择 ${L} 个格子`);
                return;
            }
            if (!isConnected(selected)) {
                showAlert('所选格子必须保持连续相邻');
                return;
            }
            const payload = Array.from(selected).map(k => {
                const [x, y] = parseKey(k);
                return { x, y };
            });
            confirmMagicTarget({ target_cells: payload });
            cleanupAll();
        });
        gameState.selectionCleanup = cleanupAll;
        return;
    }

    // SINGLE selection (单格) - 默认选择对手棋盘，如需选择我方则 descriptor.board === 'self'
    if (descriptor.type === 'single') {
        const which = descriptor.board || 'opponent';
        // board==='self'（克苏鲁之眼）：只能点自己战舰所在的格子，空格不可选
        const selfShipsOnly = (which === 'self');

        targetPrompt.innerHTML = selfShipsOnly
            ? `<h3>选择你要暴露的战舰</h3>
               <p class="magic-hint">只能点自己战舰所在的格子（绿色高亮）</p>
               <div style="text-align:center;margin-top:8px;">
                   <button id="cancel-target">取消</button>
               </div>`
            : `<h3>选择一个目标格子</h3>
               <div style="text-align:center;margin-top:8px;">
                   <button id="cancel-target">取消</button>
               </div>`;
        document.body.appendChild(targetPrompt);

        const boardEl = selfShipsOnly ? gamePlayerBoard : opponentBoard;
        if (!boardEl) return;
        gameState.selectingOnBoard = true;
        const listeners = [];

        // 自己船所在格集合
        const ownCells = new Set();
        if (selfShipsOnly) {
            // 只收【还活着】的船：沉船仍留在 gameState.ships 里（击沉只减船数、
            // 不把船移出列表），不过滤的话点自己沉船的格子也会被当成有效选择 ——
            // 克苏鲁之眼就能靠这个拿一艘早沉的船来「暴露」。
            (gameState.ships || []).forEach(ship => {
                if (ship.alive === false) return;
                (ship.positions || []).forEach(p => ownCells.add(p.x + ',' + p.y));
            });
        }

        const onClick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            const el = e.currentTarget;
            const x = parseInt(el.dataset.x, 10);
            const y = parseInt(el.dataset.y, 10);
            confirmMagicTarget({ x, y });
            cleanupAll();
        };

        boardEl.querySelectorAll('.cell').forEach(cell => {
            const x = parseInt(cell.dataset.x, 10);
            const y = parseInt(cell.dataset.y, 10);
            if (selfShipsOnly && !ownCells.has(x + ',' + y)) {
                cell.classList.add('pick-disabled');   // 空格：灰掉，点了没用
                return;
            }
            if (selfShipsOnly) cell.classList.add('pick-ship');
            cell.addEventListener('click', onClick, true);
            listeners.push({ el: cell, handler: onClick });
        });

        function cleanupAll() {
            listeners.forEach(({ el, handler }) => el.removeEventListener('click', handler, true));
            document.querySelectorAll('.cell.pick-ship, .cell.pick-disabled')
                .forEach(c => c.classList.remove('pick-ship', 'pick-disabled'));
            gameState.selectingOnBoard = false;
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
        }

        document.getElementById('cancel-target').addEventListener('click', cleanupAll);
        gameState.selectionCleanup = cleanupAll;
        return;
    }

    // OWN_SHIPS selection (选择若干我方舰船) e.g., 神之宣告 选择两艘自己船
    if (descriptor.type === 'own_ships') {
        const count = descriptor.count || 1;
        targetPrompt.innerHTML = `
            <h3>请选择 ${count} 艘你自己的战舰（点击格子切换选择）</h3>
            <div style="text-align:center;margin-top:8px;">
                <button id="confirm-magic-ships">确认</button>
                <button id="cancel-target">取消</button>
            </div>
        `;
        document.body.appendChild(targetPrompt);

        const boardEl = gamePlayerBoard;
        if (!boardEl) return;
        const selected = new Set();
        boardEl.querySelectorAll('.cell').forEach(cell => {
            const x = parseInt(cell.dataset.x, 10);
            const y = parseInt(cell.dataset.y, 10);
            // 仅允许选有船的格子
            const hasShip = gameState.ships.some(s => s.positions.some(p => p.x === x && p.y === y));
            if (!hasShip) return;
            cell.style.cursor = 'pointer';
            const onClick = (e) => {
                e.stopPropagation();
                e.preventDefault();
                const key = `${x},${y}`;
                if (selected.has(key)) {
                    selected.delete(key);
                    cell.classList.remove('selected');
                    cell.style.outline = '';
                } else {
                    if (selected.size >= count) {
                        showAlert(`只能选择 ${count} 艘战舰`);
                        return;
                    }
                    selected.add(key);
                    cell.classList.add('selected');
                    cell.style.outline = '3px solid rgba(0,191,255,0.9)';
                }
            };
            cell.addEventListener('click', onClick, true);
            // store to cleanup later
            (cell._magicHandlers = cell._magicHandlers || []).push(onClick);
        });

        document.getElementById('confirm-magic-ships').addEventListener('click', () => {
            if (selected.size !== count) {
                showAlert(`请选中 ${count} 艘战舰`);
                return;
            }
            const arr = Array.from(selected).map(k => {
                const [x, y] = k.split(',');
                return { x: parseInt(x, 10), y: parseInt(y, 10) };
            });
            confirmMagicTarget({ selected_cells: arr });
            // cleanup
            document.querySelectorAll('#player-board .cell').forEach(cell => {
                if (cell._magicHandlers && cell._magicHandlers.length) {
                    cell._magicHandlers.forEach(h => cell.removeEventListener('click', h, true));
                    cell._magicHandlers = [];
                }
                cell.style.outline = '';
                cell.classList.remove('selected');
            });
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
            gameState.currentMagicCard = null;
            gameState.currentCardIndex = null;
            gameState.pendingChainCard = null;
            gameState.pendingEffectChoice = null;
        });

        document.getElementById('cancel-target').addEventListener('click', () => {
            // cleanup
            document.querySelectorAll('#player-board .cell').forEach(cell => {
                if (cell._magicHandlers && cell._magicHandlers.length) {
                    cell._magicHandlers.forEach(h => cell.removeEventListener('click', h, true));
                    cell._magicHandlers = [];
                }
                cell.style.outline = '';
                cell.classList.remove('selected');
            });
            if (document.body.contains(targetPrompt)) document.body.removeChild(targetPrompt);
            gameState.currentMagicCard = null;
            gameState.currentCardIndex = null;
            gameState.pendingChainCard = null;
            gameState.pendingEffectChoice = null;
            gameState.pendingEffectChoice = null;
        });

        return;
    }

    showAlert('尚未实现该卡的目标选择方式');
}

// 通用区域点选器：在真实棋盘上点选 size×size 区域（触摸/鼠标均可用）。
// Phase 4 的目标选择态（按卡是否需要目标分流后的那一支）：
//   · 打开时先把**合法落点**画成虚框锚点（还没选，玩家知道能点哪）
//   · 点一下定位 → 该区域换成实框（已选）
//   · 确认按钮文案随状态变：未选 = 置灰「在棋盘上选区域…」/ 已选 = 「确认使用 <卡名>！」
//   · **点空白 = 取消**（不消耗卡）
//   · 越界/非法 → 红框 + 确认置灰（不提交）
function createBoardAreaPicker(boardEl, size, onConfirm, onCancel, opts) {
    if (!boardEl) return null;
    // ★ 2026-09-20 修：占用中**不再静默返回 null**。
    //
    // 旧写法 `if (!boardEl || gameState.selectingOnBoard) return null;` —— 被占用时
    // 悄悄放弃，调用方 `picker ? picker.cleanup : null` 什么也不做，
    // 于是弹窗已经显示、棋盘却点不动，玩家看到的就是「点了没反应、卡住选不了」。
    //
    // 现在：明确告诉玩家**是谁**占着棋盘（通常是恶魔契约那类强制点选），
    // 并给出「先完成它」的指引 —— 与后端的优先级闸门是同一套语义。
    if (gameState.selectingOnBoard) {
        const cur = gameState.boardSelection;
        const who = (cur && cur.label) ? cur.label : '另一个需要点选的效果';
        showAlert(`请先完成「${who}」的点选，再使用这张卡`);
        return null;
    }
    gameState.selectingOnBoard = true;
    const options = opts || {};
    const cardName = options.cardName || '';

    const listeners = [];
    let highlighted = [];
    let current = null;
    let invalidMsg = '';

    const clampStart = (mx, my) => ({
        sx: Math.max(0, Math.min(mx, 6 - size)),
        sy: Math.max(0, Math.min(my, 6 - size))
    });

    const cellAt = (x, y) => boardEl.querySelector(`.cell[data-x="${x}"][data-y="${y}"]`);

    function clearHighlights() {
        highlighted.forEach(c => c.classList.remove('selection-highlight', 'sel-mode-area', 'sel-invalid'));
        highlighted = [];
    }

    // 合法落点虚框锚点：区域左上角能落的所有位置（clamp 之后每个格子都能当锚点，
    // 所以直接按「棋盘能容纳该区域的列/行数」画）。选中后清掉，避免和实框打架。
    function showAnchors() {
        for (let y = 0; y <= 6 - size; y++) {
            for (let x = 0; x <= 6 - size; x++) {
                const cell = cellAt(x, y);
                if (cell) { cell.classList.add('sel-anchor'); listeners.push({ anchor: cell }); }
            }
        }
    }
    function clearAnchors() {
        boardEl.querySelectorAll('.cell.sel-anchor').forEach(c => c.classList.remove('sel-anchor'));
    }

    function setInvalid(msg) {
        invalidMsg = msg || '';
        const block = [];
        if (current) {
            for (let y = current.y1; y <= current.y2; y++) {
                for (let x = current.x1; x <= current.x2; x++) {
                    const cell = cellAt(x, y);
                    if (cell) block.push(cell);
                }
            }
        }
        if (invalidMsg) {
            highlighted.forEach(c => c.classList.remove('selection-highlight', 'sel-mode-area'));
            block.forEach(c => c.classList.add('sel-invalid'));
            highlighted = block;
        }
        syncBar();
    }

    function syncBar() {
        const btn = document.getElementById('area-confirm');
        const info = document.getElementById('area-picker-info');
        if (btn) {
            if (invalidMsg) {
                btn.disabled = true;
                btn.textContent = invalidMsg;
            } else if (!current) {
                btn.disabled = true;
                btn.textContent = options.pendingText || '在棋盘上选区域…';
            } else {
                btn.disabled = false;
                btn.textContent = cardName ? `确认使用 ${cardName}！` : '确认使用！';
            }
        }
        if (info) {
            if (!current) {
                info.className = 'selection-info pending';
                info.textContent = '点击棋盘上的格子来选择区域';
            } else if (invalidMsg) {
                info.className = 'selection-info pending';
                info.innerHTML = `<span class="sel-dot"></span>${escapeHtml(invalidMsg)}`;
            }
        }
    }

    function highlight(sx, sy) {
        clearHighlights();
        invalidMsg = '';
        for (let y = sy; y < sy + size; y++) {
            for (let x = sx; x < sx + size; x++) {
                if (x < 0 || x > 5 || y < 0 || y > 5) continue;
                const cell = cellAt(x, y);
                if (cell) {
                    cell.classList.add('selection-highlight', 'sel-mode-area');
                    highlighted.push(cell);
                }
            }
        }
        current = { x1: sx, y1: sy, x2: sx + size - 1, y2: sy + size - 1 };
        // 明确写出「选中的是哪一块」：旧实现只有棋盘上一片淡色，玩家看不出落点。
        const info = document.getElementById('area-picker-info');
        if (info) {
            info.className = 'selection-info';
            info.innerHTML = '<span class="sel-dot"></span>' +
                `${size}×${size} 已选中：第 ${sx + 1}–${sx + size} 列，第 ${sy + 1}–${sy + size} 行`;
        }
        syncBar();
    }
    // 供未来按卡规则标记非法（例：某卡要求区域内必须有目标）。当前三张区域卡无此规则，
    // 但非法态的红框 + 确认置灰必须先存在，否则「越界/非法不提交」这条就是空话。
    const api = { setInvalid: (msg) => setInvalid(msg), cleanup: null };

    // 浮动确认条（可选带标题/说明：区域类卡牌的「点哪里」提示就放在这里，
    // 免得再挂一个没有样式的裸 div 跟它重叠）
    const bar = document.createElement('div');
    bar.className = 'area-picker-bar';
    const titleHTML = options.title
        ? `<div class="selection-info pending" style="flex-basis:100%;margin:0 0 2px;">${escapeHtml(options.title)}</div>`
        : '';
    const hintHTML = options.hint
        ? `<div class="magic-hint" style="flex-basis:100%;margin:0 0 6px;">${escapeHtml(options.hint)}</div>`
        : '';
    bar.style.flexWrap = 'wrap';
    bar.innerHTML = titleHTML + hintHTML
        + `<span id="area-picker-info" class="selection-info pending">点击棋盘上的格子来选择区域</span>`
        + `<button id="area-confirm" disabled>${escapeHtml(options.pendingText || '在棋盘上选区域…')}</button>`
        + `<button id="area-cancel">取消</button>`;
    document.body.appendChild(bar);
    bar.querySelector('#area-confirm').addEventListener('click', () => {
        if (invalidMsg) { showAlert(invalidMsg); return; }
        if (!current) { showAlert('请先点选一个区域'); return; }
        const area = current;
        cleanup();
        if (typeof onConfirm === 'function') onConfirm({ target_area: area });
    });
    bar.querySelector('#area-cancel').addEventListener('click', () => {
        cleanup();
        if (typeof onCancel === 'function') onCancel();
    });
    // 点空白 = 取消（不消耗卡）：点在棋盘外、也不是确认条上的按钮 → 当作放弃本次选择。
    // ⚠️ 用 capture 阶段，且排除确认条自身（否则点确认条会先被这条判成"空白"）。
    const onDocClick = (e) => {
        if (bar.contains(e.target)) return;
        if (e.target.closest && e.target.closest('.cell')) return;   // 点格子由格子自己处理
        if (e.target.closest && (e.target.closest('.magic-target-prompt') || e.target.closest('#magic-hand'))) return;
        cleanup();
        if (typeof onCancel === 'function') onCancel();
    };

    boardEl.querySelectorAll('.cell').forEach(cell => {
        const mx = parseInt(cell.dataset.x, 10);
        const my = parseInt(cell.dataset.y, 10);
        const onEnter = () => { if (!current) { const p = clampStart(mx, my); highlight(p.sx, p.sy); } };
        const onLeave = () => { if (!current) clearHighlights(); };
        const onPick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            const p = clampStart(mx, my);
            highlight(p.sx, p.sy);
        };
        cell.addEventListener('mouseenter', onEnter);
        cell.addEventListener('mouseleave', onLeave);
        cell.addEventListener('click', onPick, true);
        listeners.push({ cell, onEnter, onLeave, onPick });
    });

    function cleanup() {
        listeners.forEach((it) => {
            if (it.anchor) return;
            const { cell, onEnter, onLeave, onPick } = it;
            cell.removeEventListener('mouseenter', onEnter);
            cell.removeEventListener('mouseleave', onLeave);
            cell.removeEventListener('click', onPick, true);
        });
        clearHighlights();
        clearAnchors();
        document.removeEventListener('click', onDocClick, true);
        if (bar.parentNode) bar.parentNode.removeChild(bar);
        gameState.selectingOnBoard = false;
        current = null;
    }

    showAnchors();
    syncBar();
    // 锚点与空白取消都要等当前这次点击循环结束再挂（否则打开选择器的那一下点击
    // 会立刻把自己关掉）
    setTimeout(() => document.addEventListener('click', onDocClick, true), 0);
    api.cleanup = cleanup;
    return api;
}

// 创建区域选择面板 - 用于区域选择类魔法卡
// 支持两种模式：
// - 小面板模式（默认）：创建 size x size 的选择面板
// - 对手棋盘模式（isOpponentBoard === true）：在对手真实棋盘上悬停预览、点击确认区域
// 获取选中的单元格坐标
// 发动魔法卡
