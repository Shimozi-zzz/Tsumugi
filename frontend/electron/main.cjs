// Electron 主进程：加载前端页面 + 自动管理后端服务（uvicorn / 打包后端）
//
// 模式说明：
// - 未打包（npm run electron）：优先连接 Vite dev server(5173)，失败则回退
//   到 dist 静态包；后端用项目内 .venv 的 python 启动 uvicorn。
// - 打包发布（electron-builder 产物）：加载 dist/index.html；后端用
//   electron-builder 附带打包的 tsumugi-backend.exe（PyInstaller 产物，
//   见 scripts/backend.spec）。
// - 环境变量 TSUMUGI_SMOKE=1 时自动退出（用于自动化冒烟测试）。
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const net = require("net");
const path = require("path");
const fs = require("fs");

const ROOT_DIR = path.resolve(__dirname, "..", ".."); // frontend/electron -> 项目根
const VITE_URL = "http://localhost:5173";
// 端口统一走环境变量 TSUMUGI_PORT（与后端 config.py / vite 一致）
const BACKEND_PORT = Number(process.env.TSUMUGI_PORT || 8001);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

let backendProc = null;

// 打包模式下后端 exe 的位置（electron-builder extraResources 复制到 resources/backend）
function resolveBackendCommand() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, "backend", "tsumugi-backend.exe");
    return { command: exe, args: [], cwd: path.dirname(exe) };
  }
  const python = path.join(ROOT_DIR, ".venv", "Scripts", "python.exe");
  return {
    command: python,
    args: ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)],
    cwd: ROOT_DIR,
  };
}

// ---------------------------------------------------------------- 端口探测
function isPortOpen(port, host) {
  return new Promise((resolve) => {
    const sock = net.connect({ port, host, timeout: 800 });
    sock.once("connect", () => { sock.destroy(); resolve(true); });
    sock.once("error", () => resolve(false));
    sock.once("timeout", () => { sock.destroy(); resolve(false); });
  });
}

async function backendReady(retries = 40) {
  for (let i = 0; i < retries; i++) {
    try {
      const r = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(500) });
      if (r.ok) return true;
    } catch { /* 继续重试 */ }
    await new Promise((res) => setTimeout(res, 300));
  }
  return false;
}

// ---------------------------------------------------------------- 后端管理
async function ensureBackend() {
  // 端口已被占用（Web 端已开后端）则不重复启动 —— 这就是"web 与客户端同步"
  if (await isPortOpen(BACKEND_PORT, "127.0.0.1")) {
    return { alreadyRunning: true, started: true };
  }
  const { command, args, cwd } = resolveBackendCommand();
  if (!fs.existsSync(command)) {
    console.error("[electron] 未找到后端程序：", command);
    return { alreadyRunning: false, started: false };
  }
  backendProc = spawn(command, args, { cwd, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  backendProc.stdout.on("data", (d) => console.log("[backend]", String(d).trimEnd()));
  backendProc.stderr.on("data", (d) => console.error("[backend]", String(d).trimEnd()));
  backendProc.on("exit", (code) => {
    console.log("[backend] 退出，code =", code);
    backendProc = null;
  });
  return { alreadyRunning: false, started: await backendReady() };
}

function stopBackend() {
  if (backendProc && backendProc.pid) {
    // taskkill /T 连带杀掉整个进程树，避免残留
    spawn("taskkill", ["/PID", String(backendProc.pid), "/T", "/F"], { windowsHide: true });
    backendProc = null;
  }
}

// ---------------------------------------------------------------- 窗口
async function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    title: "Tsumugi 知识库",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 开发模式：优先连 Vite（与浏览器体验完全一致）；回退到 dist 静态包
  try {
    const r = await fetch(VITE_URL, { signal: AbortSignal.timeout(1500) });
    if (r.ok) {
      await win.loadURL(VITE_URL);
      return;
    }
  } catch { /* Vite 未启动，走 dist */ }
  await win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
}

// ---------------------------------------------------------------- 生命周期
app.whenReady().then(async () => {
  const { started, alreadyRunning } = await ensureBackend();
  if (!started && !alreadyRunning) {
    console.error("[electron] 后端启动失败：请确认 .venv 与 8001 端口可用。");
  }
  await createWindow();

  if (process.env.TSUMUGI_SMOKE === "1") {
    setTimeout(() => { console.log("SMOKE_OK"); app.quit(); }, 3000);
  }
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("will-quit", stopBackend);
