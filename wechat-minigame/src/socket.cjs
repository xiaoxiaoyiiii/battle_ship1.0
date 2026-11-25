const { WebSocket: EngineWebSocket } = require('engine.io-client')
const { io } = require('socket.io-client')

function createWechatSocket(wx, origin) {
  class WechatWebSocket extends EngineWebSocket {
    createSocket(uri, protocols) {
      let closed = false
      const options = {
        url: uri,
        ...(Array.isArray(protocols) && protocols.length ? { protocols } : {}),
        fail: error => { if (!closed) bridge.onerror?.(error) },
      }
      const task = wx.connectSocket(options)
      const bridge = {
        send(data) {
          task.send({ data, fail: error => { if (!closed) bridge.onerror?.(error) } })
        },
        close() {
          closed = true
          try { task.close({ code: 1000, fail() {} }) } catch {}
        },
      }
      task.onOpen(event => bridge.onopen?.(event))
      task.onClose(event => bridge.onclose?.(event))
      task.onMessage(event => bridge.onmessage?.(event))
      task.onError(event => bridge.onerror?.(event))
      return bridge
    }
  }
  return io(origin, {
    autoConnect: false,
    forceNew: true,
    upgrade: false,
    transports: [WechatWebSocket],
    timeout: 8000,
    reconnectionDelayMax: 3000,
  })
}

module.exports = { createWechatSocket }
