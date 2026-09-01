<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Coin, ChatDotRound, DataAnalysis, Notebook } from '@element-plus/icons-vue'
import { fetchHealth } from './api'
import ChatView from './views/ChatView.vue'
import DashboardView from './views/DashboardView.vue'
import SchemaView from './views/SchemaView.vue'

const activeView = ref('chat')
const llmMode = ref<'llm' | 'fallback' | 'loading'>('loading')

const NAV = [
  { key: 'chat', label: '对话问数', icon: ChatDotRound },
  { key: 'dashboard', label: '经营看板', icon: DataAnalysis },
  { key: 'schema', label: '数据字典', icon: Notebook },
]

onMounted(async () => {
  try {
    const health = await fetchHealth()
    llmMode.value = health.llm_enabled ? 'llm' : 'fallback'
  } catch {
    llmMode.value = 'fallback'
  }
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo"><el-icon :size="22"><Coin /></el-icon></div>
        <div>
          <div class="brand-name">ChatBI</div>
          <div class="brand-sub">智能经营分析平台</div>
        </div>
      </div>

      <nav class="nav">
        <div
          v-for="item in NAV"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeView === item.key }"
          @click="activeView = item.key"
        >
          <el-icon :size="17"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </div>
      </nav>

      <div class="sidebar-footer">
        <div class="mode-row">
          <span class="mode-dot" :class="llmMode === 'llm' ? 'ok' : 'warn'" />
          <span class="mode-text">{{ llmMode === 'llm' ? 'LLM 模式' : llmMode === 'fallback' ? '降级模式' : '检测中' }}</span>
        </div>
        <el-tooltip
          v-if="llmMode === 'fallback'"
          content="未配置 LLM_API_KEY,正在以规则检索 + 示例 SQL 兜底运行"
          placement="right"
        >
          <div class="mode-hint">配置 Key 后解锁完整能力</div>
        </el-tooltip>
        <div v-else class="mode-hint">v0.1 · 本地演示</div>
      </div>
    </aside>

    <main class="main">
      <div :key="activeView" class="view-anim" style="height: 100%">
        <ChatView v-if="activeView === 'chat'" />
        <DashboardView v-else-if="activeView === 'dashboard'" />
        <SchemaView v-else />
      </div>
    </main>
  </div>
</template>

<style>
/* ============ 全局主题 ============ */
:root {
  --brand: #4f6ef2;
  --brand-2: #8b5cf6;
  --brand-grad: linear-gradient(135deg, #4f6ef2, #8b5cf6);
  --bg: #f4f6fb;
  --ink: #17233d;
  --ink-2: #475569;
  --ink-3: #94a3b8;
  --line: #e8ecf4;
  --card-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px rgba(15, 23, 42, 0.05);

  /* Element Plus 主色对齐 */
  --el-color-primary: #4f6ef2;
  --el-color-primary-light-3: #7a8ff5;
  --el-color-primary-light-5: #a3b2f8;
  --el-color-primary-light-7: #cbd3fb;
  --el-color-primary-light-8: #dde2fc;
  --el-color-primary-light-9: #eef1fe;
  --el-color-primary-dark-2: #3f58c2;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; }
body {
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif;
  background: var(--bg);
  color: var(--ink);
  -webkit-font-smoothing: antialiased;
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-thumb { background: #cdd5e3; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #b3bdd0; }
::-webkit-scrollbar-track { background: transparent; }

/* 统一卡片质感 */
.el-card {
  border-radius: 14px;
  border: 1px solid var(--line);
  box-shadow: var(--card-shadow) !important;
}

/* 页面切换动效 */
.view-anim { animation: viewIn 0.28s cubic-bezier(0.22, 0.61, 0.36, 1) both; }
@keyframes viewIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ============ 布局 ============ */
.layout { display: flex; height: 100%; }

.sidebar {
  width: 216px; flex: none;
  display: flex; flex-direction: column;
  background: linear-gradient(180deg, #0b1220 0%, #141d30 100%);
  color: #c6d0e0;
}
.brand { display: flex; align-items: center; gap: 11px; padding: 20px 18px 18px; }
.brand-logo {
  width: 38px; height: 38px; border-radius: 11px; flex: none;
  display: flex; align-items: center; justify-content: center;
  background: var(--brand-grad); color: #fff;
  box-shadow: 0 4px 14px rgba(79, 110, 242, 0.45);
}
.brand-name { font-size: 19px; font-weight: 700; color: #fff; letter-spacing: 0.5px; }
.brand-sub { font-size: 11px; color: #7c8aa5; margin-top: 2px; }

.nav { flex: 1; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 11px 13px; border-radius: 10px;
  font-size: 13.5px; color: #9aa8c0; cursor: pointer;
  transition: all 0.18s ease;
}
.nav-item:hover { background: rgba(255, 255, 255, 0.06); color: #e6ecf7; }
.nav-item.active {
  background: linear-gradient(135deg, rgba(79, 110, 242, 0.28), rgba(139, 92, 246, 0.2));
  color: #fff; font-weight: 600;
}
.nav-item.active span { letter-spacing: 0.3px; }

.sidebar-footer { padding: 14px 18px 18px; border-top: 1px solid rgba(255, 255, 255, 0.07); }
.mode-row { display: flex; align-items: center; gap: 7px; }
.mode-dot { width: 8px; height: 8px; border-radius: 50%; }
.mode-dot.ok { background: #34d399; box-shadow: 0 0 8px rgba(52, 211, 153, 0.7); }
.mode-dot.warn { background: #f59e0b; box-shadow: 0 0 8px rgba(245, 158, 11, 0.7); }
.mode-text { font-size: 12px; color: #9aa8c0; }
.mode-hint { font-size: 11px; color: #5b6880; margin-top: 5px; }

.main { flex: 1; min-width: 0; overflow: hidden; }
</style>
