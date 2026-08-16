// Electron preload：向渲染进程注入 API 地址
// 客户端模式下前端直接访问本机后端 http://127.0.0.1:8001，
// 与 Web 模式（走 Vite 代理 /api）共用同一个后端，实现数据同步。
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("tsumugiBridge", {
  apiBase: "http://127.0.0.1:8001/api",
  isClient: true,
  // 窗口控制（Renderer → IPC → main → BrowserWindow）
  window: {
    minimize: () => ipcRenderer.send("window:minimize"),
    toggleMaximize: () => ipcRenderer.send("window:toggle-maximize"),
    close: () => ipcRenderer.send("window:close"),
    onMaximizedChange: (cb) => {
      ipcRenderer.on("window:maximized", (_e, maximized) => cb(maximized));
    },
  },
});
