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
    <el-card shadow="never">
      <template #header>
        <div class="header-row">
          <span>语义层(Semantic Layer)</span>
          <span class="sub">表结构 / 指标口径的统一管理,是 Text2SQL 准确率的基石</span>
        </div>
      </template>

      <el-tabs v-model="activeTab">
        <el-tab-pane label="数据表" name="tables">
          <el-collapse>
            <el-collapse-item v-for="table in data?.tables" :key="table.name" :name="table.name">
              <template #title>
                <span class="table-name">{{ table.name }}</span>
                <span class="table-desc">{{ table.meaning }}</span>
              </template>
              <el-table :data="table.fields" size="small">
                <el-table-column prop="name" label="字段" width="180" />
                <el-table-column prop="comment" label="说明" />
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>

        <el-tab-pane label="指标口径" name="metrics">
          <el-table :data="data?.metrics" size="small">
            <el-table-column prop="metric" label="指标" width="200" />
            <el-table-column prop="definition" label="计算口径" />
            <el-table-column prop="note" label="备注" width="260" />
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="内置示例" name="examples">
          <el-tag v-for="example in data?.examples" :key="example.question" class="example-tag" effect="plain">
            {{ example.question }}
          </el-tag>
          <p class="note">这些示例既是 SQL 生成的 few-shot 上下文,也是 LLM 不可用时降级模式的兜底答案来源。</p>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.schema-page { padding: 20px 24px; height: 100%; overflow-y: auto; }
.header-row { display: flex; justify-content: space-between; align-items: center; }
.sub { font-size: 12px; color: #86909c; }
.table-name { font-weight: 600; margin-right: 12px; }
.table-desc { color: #86909c; font-size: 12px; }
.example-tag { margin: 0 8px 8px 0; }
.note { color: #86909c; font-size: 12px; margin-top: 8px; }
</style>
