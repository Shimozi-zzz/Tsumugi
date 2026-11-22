<script setup lang="ts">
import { useLibraryStore } from '@/stores/library'

const store = useLibraryStore()
</script>

<template>
  <main class="empty-hall">
    <!-- 顶部极克制展馆聚光渐变 -->
    <div class="hall-spotlight" aria-hidden="true" />

    <!-- 背景深处低透明度大号衬线水印 -->
    <div class="hall-watermark" aria-hidden="true">TSUMUGI</div>

    <!-- 居中极简排版（无边框卡片套娃） -->
    <section class="hall-content">
      <h1 class="hall-title">开始你的收藏</h1>
      <p class="hall-subtitle">从在线资料库搜寻导入，或手动添加本地游戏</p>

      <button
        type="button"
        class="btn btn-primary hall-primary-btn"
        @click="store.openImport('aggregated')"
      >
        导入作品
      </button>

      <div class="hall-links">
        <button
          type="button"
          class="hall-ghost-link"
          @click="store.openImport('local', 'single')"
        >
          手动添加
        </button>
        <span class="hall-link-dot" aria-hidden="true">·</span>
        <button
          type="button"
          class="hall-ghost-link"
          @click="store.openSettings('sources')"
        >
          配置数据源与代理
        </button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.empty-hall {
  position: relative;
  min-height: 100vh;
  width: 100%;
  background: #0a0a0c;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 28px;
  overflow: hidden;
}

.hall-spotlight {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(
      ellipse 56% 42% at 50% 0%,
      rgba(255, 255, 255, 0.055) 0%,
      rgba(255, 255, 255, 0.015) 48%,
      transparent 76%
    ),
    radial-gradient(
      circle at 50% 54%,
      rgba(255, 255, 255, 0.022) 0%,
      transparent 52%
    );
  pointer-events: none;
}

.hall-watermark {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -52%);
  font-family: var(--font-serif);
  font-size: clamp(72px, 14vw, 196px);
  font-weight: 600;
  letter-spacing: 0.22em;
  text-indent: 0.22em;
  color: #f5f5f7;
  opacity: 0.04;
  white-space: nowrap;
  pointer-events: none;
  user-select: none;
}

.hall-content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 480px;
}

.hall-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: clamp(28px, 3vw, 38px);
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-primary);
  line-height: 1.25;
}

.hall-subtitle {
  margin: 14px 0 0;
  font-size: 14px;
  font-weight: 400;
  color: var(--text-secondary);
  line-height: 1.6;
  opacity: 0.85;
}

.hall-primary-btn {
  margin-top: 32px;
  padding: 12px 32px;
  border-radius: 999px;
  font-size: 14px;
  letter-spacing: 0.03em;
}

.hall-links {
  margin-top: 20px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.hall-ghost-link {
  border: none;
  background: transparent;
  padding: 4px 2px;
  font-size: 12.5px;
  font-weight: 400;
  color: var(--text-muted);
  transition: color var(--duration-fast) var(--ease-out-expo);
}

.hall-ghost-link:hover {
  color: var(--text-primary);
}

.hall-link-dot {
  color: rgba(255, 255, 255, 0.22);
  font-size: 12px;
  user-select: none;
}
</style>
