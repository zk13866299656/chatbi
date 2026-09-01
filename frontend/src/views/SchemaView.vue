<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchSemanticLayer } from '../api'
import type { SemanticLayer } from '../types'

const data = ref<SemanticLayer | null>(null)
const activeTab = ref('tables')

onMounted(async () => {
  data.value = await fetchSemanticLayer()
})
</script>

<template>
  <div class="schema-page">
    <div class="page-head">
      <h2 class="page-title">数据字典</h2>
      <p class="page-sub">语义层统一管理表结构与指标口径 —— Text2SQL 准确率的基石</p>
    </div>

    <el-card shadow="never" class="main-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="数据表" name="tables">
          <el-collapse class="table-collapse">
            <el-collapse-item v-for="table in data?.tables" :key="table.name" :name="table.name">
              <template #title>
                <div class="table-head">
                  <code class="table-name">{{ table.name }}</code>
                  <span class="table-desc">{{ table.meaning }}</span>
                </div>
              </template>
              <el-table :data="table.fields" size="small" class="field-table">
                <el-table-column prop="name" label="字段" width="200">
                  <template #default="{ row }">
                    <code class="field-name">{{ row.name }}</code>
                  </template>
                </el-table-column>
                <el-table-column prop="comment" label="说明" />
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>

        <el-tab-pane label="指标口径" name="metrics">
          <div class="metric-grid">
            <div v-for="metric in data?.metrics" :key="metric.metric" class="metric-card">
              <div class="metric-name">{{ metric.metric }}</div>
              <code class="metric-def">{{ metric.definition }}</code>
              <p v-if="metric.note" class="metric-note">{{ metric.note }}</p>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="内置示例" name="examples">
          <div class="example-wrap">
            <span v-for="example in data?.examples" :key="example.question" class="example-chip">
              {{ example.question }}
            </span>
          </div>
          <p class="note">
            这些示例既是 SQL 生成的 few-shot 上下文,也是 LLM 不可用时降级模式的兜底答案来源,
            检索时做了时间归一化以避免日期字符干扰结构匹配。
          </p>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.schema-page { padding: 22px 28px; height: 100%; overflow-y: auto; }
.page-head { margin-bottom: 18px; }
.page-title { font-size: 20px; font-weight: 700; color: var(--ink); }
.page-sub { font-size: 12.5px; color: var(--ink-3); margin-top: 5px; }
.main-card { padding: 4px 8px 10px; }

.table-head { display: flex; align-items: center; gap: 12px; min-width: 0; }
.table-name {
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12.5px; padding: 2px 9px; border-radius: 6px;
  background: #eef1fe; color: var(--brand);
}
.table-desc { color: var(--ink-3); font-size: 12.5px; }
.field-name {
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12px; color: #475569;
}

.metric-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 6px 2px; }
.metric-card {
  border: 1px solid var(--line); border-radius: 12px;
  padding: 14px 16px; background: #fbfcfe;
  transition: all 0.18s ease;
}
.metric-card:hover { border-color: #c7d0fa; box-shadow: 0 4px 14px rgba(79, 110, 242, 0.08); }
.metric-name { font-size: 13.5px; font-weight: 600; color: var(--ink); margin-bottom: 8px; }
.metric-def {
  display: block;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12px; color: #475569; line-height: 1.7;
  background: #f6f8fb; border-radius: 8px; padding: 9px 11px;
}
.metric-note { font-size: 12px; color: #b45309; margin-top: 8px; }

.example-wrap { display: flex; flex-wrap: wrap; gap: 9px; padding: 8px 2px; }
.example-chip {
  font-size: 12.5px; padding: 7px 14px; border-radius: 999px;
  background: #f1f4f9; color: var(--ink-2); border: 1px solid var(--line);
}
.note { font-size: 12px; color: var(--ink-3); margin-top: 12px; line-height: 1.7; }
</style>
