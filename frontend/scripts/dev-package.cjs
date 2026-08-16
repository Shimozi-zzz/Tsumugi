// 开发免安装更新：npm run dev:package
// 流程：停止 Tsumugi.exe → 清理 release/win-unpacked → vite build →
//       electron-builder --dir → release/win-unpacked/Tsumugi.exe → 自动启动
// 说明：
// - 只处理本应用的 Tsumugi.exe（不杀无关 Electron/进程）
// - 只删除 release/win-unpacked 与 win-unpacked.tmp（程序文件；用户数据在项目根
//   ./tsumugi.db 与 ./data，不会被此脚本触碰）
// - 不生成安装包、不新增依赖
"use strict";

const { execSync, spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, ".."); // frontend/
const release = path.join(root, "release");
const unpacked = path.join(release, "win-unpacked");
const tmpDir = path.join(release, "win-unpacked.tmp");
const exe = path.join(unpacked, "Tsumugi.exe");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function tsumugiRunning() {
  try {
    const out = execSync('tasklist /FI "IMAGENAME eq Tsumugi.exe" /FO CSV /NH', { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    return /Tsumugi\.exe/.test(out);
  } catch {
    return false;
  }
}

async function stopApp() {
  if (!tsumugiRunning()) return;
  console.log("[dev:package] 停止 Tsumugi.exe…");
  try {
    execSync("taskkill /IM Tsumugi.exe /T /F", { stdio: "ignore" });
  } catch {
    /* 已退出 */
  }
  for (let i = 0; i < 30; i++) {
    if (!tsumugiRunning()) break;
    await sleep(300);
  }
  if (tsumugiRunning()) {
    console.error("[dev:package] 未能停止 Tsumugi.exe，请手动关闭后重试。");
    process.exit(1);
  }
}

function cleanDir(dir, tries = 6) {
  for (let i = 0; i < tries; i++) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {
      /* 可能被占用，重试 */
    }
    if (!fs.existsSync(dir)) return true;
    // 同步等待，避免脚本异步化复杂度
    const end = Date.now() + 2000;
    while (Date.now() < end) { /* 空转等锁释放 */ }
  }
  return !fs.existsSync(dir);
}

async function main() {
  console.log("[dev:package] 开发打包开始");
  await stopApp();

  if (fs.existsSync(release)) {
    console.log("[dev:package] 清理旧程序文件 release/win-unpacked …");
    const ok = cleanDir(unpacked) && cleanDir(tmpDir);
    if (!ok) {
      console.error("[dev:package] release/ 被其他进程占用（可能为杀软扫描），无法清理。");
      console.error("  请稍后重试，或对 E:\\program\\MyProject\\Tsumugi 添加杀软排除后重跑。");
      process.exit(1);
    }
  }

  console.log("[dev:package] vite build …");
  execSync("npm run build", { cwd: root, stdio: "inherit", shell: true });

  console.log("[dev:package] electron-builder --dir …");
  execSync("npx electron-builder --dir", {
    cwd: root,
    stdio: "inherit",
    shell: true,
    env: {
      ...process.env,
      CSC_IDENTITY_AUTO_DISCOVERY: "false",
      ELECTRON_BUILDER_BINARIES_MIRROR: "https://npmmirror.com/mirrors/electron-builder-binaries/",
    },
  });

  if (!fs.existsSync(exe)) {
    console.error(`[dev:package] 未生成 ${exe}，构建失败。`);
    process.exit(1);
  }

  console.log(`[dev:package] 完成：${exe}`);
  console.log("[dev:package] 启动 Tsumugi …");
  const child = spawn(exe, [], { detached: true, stdio: "ignore" });
  child.unref();
}

main().catch((e) => {
  console.error("[dev:package] 出错：", e && e.message ? e.message : e);
  process.exit(1);
});
