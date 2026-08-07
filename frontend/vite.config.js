import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // 端口统一走环境变量 TSUMUGI_PORT（与后端 config.py / Electron 一致）
      "/api": { target: `http://localhost:${process.env.TSUMUGI_PORT || 8001}`, changeOrigin: true },
      "/static": { target: `http://localhost:${process.env.TSUMUGI_PORT || 8001}`, changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
