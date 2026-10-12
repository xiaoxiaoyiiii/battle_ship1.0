// Phase 8：从 game.js 原样迁出；作为经典脚本共享页面作用域。
// 统一的 socket 获取入口：已有连接则复用，绝不重复建连。
// 之前多处直接 io.connect 覆盖 gameState.socket，旧连接未关闭会变成孤儿，
// 且 setupSocketListeners 会被重复调用导致同一事件被处理多次。
function ensureSocket() {
    if (gameState.socket) {
        return gameState.socket;
    }
    gameState.socket = io.connect('http://' + window.location.host);
    setupSocketListeners();
    return gameState.socket;
}

// 连接就绪后执行回调；已连接则立即执行。
// 使用 once 而非 on，避免反复调用时叠加重复监听。
function onSocketReady(callback) {
    const socket = ensureSocket();
    if (socket.connected) {
        callback(socket);
    } else {
        socket.once('connect', () => callback(socket));
    }
}
