<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Coin, ChatDotRound, DataAnalysis, Notebook } from '@element-plus/icons-vue'
import { fetchHealth } from './api'
import ChatView from './views/ChatView.vue'
import DashboardView from './views/DashboardView.vue'
import SchemaView from './views/SchemaView.vue'

const activeView = ref('chat')
const llmMode = ref<'llm' | 'fallback' | 'loading'>('loading')

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
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <el-icon :size="26"><Coin /></el-icon>
        <div>
          <div class="brand-name">ChatBI</div>
          <div class="brand-sub">智能经营分析平台</div>
        </div>
      </div>
      <el-menu :default-active="activeView" class="menu" @select="(k: string) => (activeView = k)">
        <el-menu-item index="chat"><el-icon><ChatDotRound /></el-icon>对话问数</el-menu-item>
        <el-menu-item index="dashboard"><el-icon><DataAnalysis /></el-icon>经营看板</el-menu-item>
        <el-menu-item index="schema"><el-icon><Notebook /></el-icon>数据字典</el-menu-item>
      </el-menu>
      <div class="aside-footer">
        <el-tag v-if="llmMode === 'llm'" type="success" effect="plain" size="small">LLM 模式</el-tag>
        <el-tooltip v-else-if="llmMode === 'fallback'" content="未配置 LLM_API_KEY,正在以规则检索 + 示例 SQL 兜底运行" placement="bottom">
          <el-tag type="warning" effect="plain" size="small">降级模式</el-tag>
        </el-tooltip>
      </div>
    </el-aside>

    <el-main class="main">
      <ChatView v-if="activeView === 'chat'" />
      <DashboardView v-else-if="activeView === 'dashboard'" />
      <SchemaView v-else />
    </el-main>
  </el-container>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; }
body { font-family: 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif; background: #f5f7fa; }

.layout { height: 100%; }
.aside { background: #1d2530; display: flex; flex-direction: column; color: #cfd8e3; }
.brand {
  display: flex; align-items: center; gap: 10px;
  padding: 20px 16px 16px; color: #fff;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.brand-name { font-size: 20px; font-weight: 700; letter-spacing: 1px; }
.brand-sub { font-size: 11px; color: #8a97a8; margin-top: 2px; }
.menu { border-right: none; background: transparent; flex: 1; }
.menu .el-menu-item { color: #aeb9c8; }
.menu .el-menu-item:hover { background: rgba(255, 255, 255, 0.06); color: #fff; }
.menu .el-menu-item.is-active { background: rgba(64, 158, 255, 0.18); color: #66b1ff; border-right: 2px solid #409eff; }
.aside-footer { padding: 14px 16px; }
.main { padding: 0; background: #f5f7fa; overflow: hidden; }
</style>
