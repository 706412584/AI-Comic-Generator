<template>
  <el-config-provider :locale="locale">
    <el-container>
      <el-header class="main-header" height="52px">
        <div class="header-left">
          <div class="logo">
            <svg class="logo-mark" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M4 5.5C4 4.67 4.67 4 5.5 4H11v16H5.5C4.67 20 4 19.33 4 18.5v-13Z" fill="var(--app-accent)" opacity="0.9"/>
              <path d="M13 4h5.5c.83 0 1.5.67 1.5 1.5v13c0 .83-.67 1.5-1.5 1.5H13V4Z" fill="var(--app-accent)" opacity="0.45"/>
              <path d="M15.5 8.5 18 7l-1 2.6 2 .9-3.5 1.5.5-2-1.5-.5 1-1Z" fill="#fff"/>
            </svg>
            <span class="logo-text">AI 漫画生成器</span>
          </div>
          <nav class="nav-links">
            <router-link to="/" class="nav-link" :class="{ active: $route.path === '/' }">项目</router-link>
            <router-link to="/config" class="nav-link" :class="{ active: $route.path === '/config' }">模型配置</router-link>
          </nav>
        </div>
        <div class="header-right">
          <span class="status-dot" :class="serverOnline ? 'online' : 'offline'"></span>
          <span class="status-text">{{ serverOnline ? '服务正常' : '服务离线' }}</span>
          <div v-if="isDesktop" class="win-controls">
            <button class="win-btn" title="最小化" @click="onMinimize">
              <svg viewBox="0 0 12 12" width="12" height="12"><path d="M2 6h8" stroke="currentColor" stroke-width="1" fill="none"/></svg>
            </button>
            <button class="win-btn" :title="isMaximized ? '还原' : '最大化'" @click="onToggleMaximize">
              <svg v-if="!isMaximized" viewBox="0 0 12 12" width="12" height="12"><rect x="2.5" y="2.5" width="7" height="7" stroke="currentColor" stroke-width="1" fill="none"/></svg>
              <svg v-else viewBox="0 0 12 12" width="12" height="12"><rect x="3.5" y="1.5" width="7" height="7" stroke="currentColor" stroke-width="1" fill="none"/><rect x="1.5" y="3.5" width="7" height="7" stroke="currentColor" stroke-width="1" fill="none"/></svg>
            </button>
            <button class="win-btn win-close" title="关闭" @click="onClose">
              <svg viewBox="0 0 12 12" width="12" height="12"><path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" stroke-width="1" fill="none"/></svg>
            </button>
          </div>
        </div>
      </el-header>
      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import axios from 'axios'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

const locale = ref(zhCn)
const serverOnline = ref(true)
let healthTimer = null

const isDesktop = ref(!!window.desktopInfo?.isDesktop)
const isMaximized = ref(false)
let unsubscribeMaximize = null

const checkHealth = async () => {
  try {
    await axios.get('/api/v1/health', { timeout: 5000 })
    serverOnline.value = true
  } catch {
    serverOnline.value = false
  }
}

const onMinimize = () => window.windowControls?.minimize()
const onToggleMaximize = () => window.windowControls?.toggleMaximize()
const onClose = () => window.windowControls?.close()

onMounted(async () => {
  checkHealth()
  healthTimer = setInterval(checkHealth, 30000)
  if (isDesktop.value && window.windowControls) {
    isMaximized.value = await window.windowControls.isMaximized()
    unsubscribeMaximize = window.windowControls.onMaximizeChange(v => {
      isMaximized.value = v
    })
  }
})

onBeforeUnmount(() => {
  if (healthTimer) clearInterval(healthTimer)
  if (unsubscribeMaximize) unsubscribeMaximize()
})
</script>

<style scoped>
.main-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--app-border);
  background-color: var(--app-surface);
  padding: 0 0 0 20px;
  -webkit-app-region: drag;
  user-select: none;
}
.main-header :deep(a),
.main-header :deep(button),
.main-header .nav-link,
.main-header .win-controls {
  -webkit-app-region: no-drag;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 28px;
}
.logo {
  display: flex;
  align-items: center;
  gap: 8px;
}
.logo-mark {
  width: 24px;
  height: 24px;
}
.logo-text {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--app-text);
}
.nav-links {
  display: flex;
  gap: 4px;
}
.nav-link {
  padding: 6px 14px;
  border-radius: var(--app-radius-sm);
  color: var(--app-text-secondary);
  text-decoration: none;
  font-size: 14px;
  transition: color 0.15s, background-color 0.15s;
}
.nav-link:hover {
  color: var(--app-text);
  background: var(--app-surface-2);
}
.nav-link.active {
  color: var(--app-accent);
  background: rgba(245, 158, 11, 0.1);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-dot.online {
  background: #22c55e;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.6);
}
.status-dot.offline {
  background: #ef4444;
  box-shadow: 0 0 6px rgba(239, 68, 68, 0.6);
}
.status-text {
  font-size: 12px;
  color: var(--app-text-secondary);
}
.main-content {
  padding: 0;
  overflow-y: auto;
}
.win-controls {
  display: flex;
  align-items: stretch;
  margin-left: 12px;
  height: 52px;
}
.win-btn {
  width: 46px;
  height: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 0;
  color: var(--app-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.win-btn:hover {
  background: var(--app-surface-2);
  color: var(--app-text);
}
.win-btn.win-close:hover {
  background: #e53935;
  color: #fff;
}
.win-btn:focus {
  outline: none;
}
</style>
