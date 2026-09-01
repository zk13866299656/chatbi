<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CaretBottom, CaretTop } from '@element-plus/icons-vue'
import { fetchCategory, fetchOverview, fetchTrend } from '../api'
import type { OverviewData } from '../types'
import ChartBlock from '../components/ChartBlock.vue'

const days = ref(30)
const loading = ref(false)
const overview = ref<OverviewData | null>(null)
const trendDates = ref<string[]>([])
const trendGmv = ref<number[]>([])
const trendOrders = ref<number[]>([])
const categoryData = ref<{ categories: string[]; gmv: number[] }>({ categories: [], gmv: [] })

const money = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(1)} 万` : v.toLocaleString())

const kpis = computed(() => {
  const o = overview.value
  if (!o) return []
  return [
    { label: `GMV(近${o.days}天)`, item: o.gmv, display: `¥${money(o.gmv.value)}`, upIsGood: true },
    { label: '支付订单数', item: o.orders, display: o.orders.value.toLocaleString(), upIsGood: true },
    { label: '客单价', item: o.aov, display: `¥${o.aov.value.toFixed(0)}`, upIsGood: true },
    { label: '订单退款率', item: o.refund_rate, display: `${o.refund_rate.value.toFixed(2)}%`, upIsGood: false },
  ]
})

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['GMV', '订单数'] },
  grid: { left: 64, right: 64, top: 48, bottom: 40 },
  xAxis: { type: 'category', data: trendDates.value },
  yAxis: [
    { type: 'value', name: 'GMV(元)', axisLabel: { formatter: (v: number) => (v >= 10000 ? `${Math.round(v / 10000)}万` : v) } },
    { type: 'value', name: '订单数' },
  ],
  series: [
    { name: 'GMV', type: 'line', smooth: true, data: trendGmv.value, areaStyle: { opacity: 0.12 }, itemStyle: { color: '#409eff' } },
    { name: '订单数', type: 'bar', yAxisIndex: 1, data: trendOrders.value, itemStyle: { color: '#91cc75', opacity: 0.65 }, barMaxWidth: 18 },
  ],
}))

const categoryOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 100, right: 40, top: 24, bottom: 32 },
  xAxis: { type: 'value', axisLabel: { formatter: (v: number) => (v >= 10000 ? `${Math.round(v / 10000)}万` : v) } },
  yAxis: { type: 'category', data: [...categoryData.value.categories].reverse() },
  series: [{
    name: 'GMV', type: 'bar', data: [...categoryData.value.gmv].reverse(),
    itemStyle: { color: '#409eff', borderRadius: [0, 4, 4, 0] }, barMaxWidth: 20,
  }],
}))

async function loadAll() {
  loading.value = true
  try {
    const [o, t, c] = await Promise.all([
      fetchOverview(days.value),
      fetchTrend(days.value),
      fetchCategory(days.value),
    ])
    overview.value = o
    trendDates.value = t.dates
    trendGmv.value = t.gmv
    trendOrders.value = t.orders
    categoryData.value = c
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div v-loading="loading" class="dash-page">
    <div class="dash-header">
      <span class="period">统计区间:{{ overview?.period?.[0] }} ~ {{ overview?.period?.[1] }}</span>
      <el-radio-group v-model="days" size="small" @change="loadAll">
        <el-radio-button :value="7">近7天</el-radio-button>
        <el-radio-button :value="30">近30天</el-radio-button>
        <el-radio-button :value="90">近90天</el-radio-button>
      </el-radio-group>
    </div>

    <el-row :gutter="16">
      <el-col v-for="kpi in kpis" :key="kpi.label" :span="6">
        <el-card shadow="never" class="kpi-card">
          <div class="kpi-label">{{ kpi.label }}</div>
          <div class="kpi-value">{{ kpi.display }}</div>
          <div v-if="kpi.item.delta_pct !== null" class="kpi-delta" :class="kpi.item.delta_pct >= 0 ? 'up' : 'down'">
            <el-icon><component :is="kpi.item.delta_pct >= 0 ? CaretTop : CaretBottom" /></el-icon>
            <span>{{ Math.abs(kpi.item.delta_pct).toFixed(1) }}% 环比上期</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="chart-row">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>销售趋势</template>
          <ChartBlock :option="trendOption" height="320px" />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>品类 GMV 结构</template>
          <ChartBlock :option="categoryOption" height="320px" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dash-page { padding: 20px 24px; height: 100%; overflow-y: auto; }
.dash-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.period { color: #86909c; font-size: 13px; }
.kpi-card :deep(.el-card__body) { padding: 16px 20px; }
.kpi-label { font-size: 13px; color: #86909c; }
.kpi-value { font-size: 26px; font-weight: 700; color: #1d2129; margin: 6px 0 4px; }
.kpi-delta { display: flex; align-items: center; gap: 2px; font-size: 12px; }
.kpi-delta.up { color: #f56c6c; }
.kpi-delta.down { color: #67c23a; }
.chart-row { margin-top: 16px; }
</style>
