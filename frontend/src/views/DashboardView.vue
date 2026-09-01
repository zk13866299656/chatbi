<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CaretBottom, CaretTop, Coin, Document, Wallet, RefreshLeft, ChatDotRound } from '@element-plus/icons-vue'
import { fetchCategory, fetchCategoryHealth, fetchOverview, fetchTrend } from '../api'
import type { CategoryHealthItem, OverviewData } from '../types'
import ChartBlock from '../components/ChartBlock.vue'

const props = defineProps<{ days?: number }>()
const emit = defineEmits<{ (e: 'ask', question: string): void }>()

const days = ref(30)
const loading = ref(false)
const overview = ref<OverviewData | null>(null)
const trendDates = ref<string[]>([])
const trendGmv = ref<number[]>([])
const trendOrders = ref<number[]>([])
const categoryData = ref<{ categories: string[]; gmv: number[] }>({ categories: [], gmv: [] })
const health = ref<CategoryHealthItem[]>([])

const money = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(1)} 万` : v.toLocaleString())

const kpis = computed(() => {
  const o = overview.value
  if (!o) return []
  return [
    { label: 'GMV', item: o.gmv, display: `¥${money(o.gmv.value)}`, upIsGood: true, icon: Coin, tone: 'blue',
      question: `最近${days.value}天各品类的销售额排名` },
    { label: '支付订单数', item: o.orders, display: o.orders.value.toLocaleString(), upIsGood: true, icon: Document, tone: 'violet',
      question: `最近${days.value}天各区域的支付订单数` },
    { label: '客单价', item: o.aov, display: `¥${o.aov.value.toFixed(0)}`, upIsGood: true, icon: Wallet, tone: 'green',
      question: `最近${days.value}天各会员等级的客单价` },
    { label: '订单退款率', item: o.refund_rate, display: `${o.refund_rate.value.toFixed(2)}%`, upIsGood: false, icon: RefreshLeft, tone: 'orange',
      question: `最近${days.value}天各品类的退款率` },
  ]
})

const deltaClass = (kpi: { item: { delta_pct: number | null }; upIsGood: boolean }) => {
  const d = kpi.item.delta_pct
  if (d === null) return ''
  const isGood = kpi.upIsGood ? d >= 0 : d < 0
  return isGood ? 'good' : 'bad'
}

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['GMV', '订单数'], right: 8, top: 0 },
  grid: { left: 64, right: 64, top: 44, bottom: 36 },
  xAxis: { type: 'category', data: trendDates.value, axisLine: { lineStyle: { color: '#e2e8f2' } } },
  yAxis: [
    { type: 'value', name: 'GMV(元)', splitLine: { lineStyle: { color: '#f0f3f9' } }, axisLabel: { formatter: (v: number) => (v >= 10000 ? `${Math.round(v / 10000)}万` : v) } },
    { type: 'value', name: '订单数', splitLine: { show: false } },
  ],
  series: [
    { name: 'GMV', type: 'line', smooth: true, data: trendGmv.value, areaStyle: { opacity: 0.1 }, itemStyle: { color: '#4f6ef2' }, lineStyle: { width: 2.5 } },
    { name: '订单数', type: 'bar', yAxisIndex: 1, data: trendOrders.value, itemStyle: { color: '#a5b4fc', opacity: 0.7 }, barMaxWidth: 16 },
  ],
}))

const categoryOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 100, right: 40, top: 16, bottom: 28 },
  xAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f3f9' } }, axisLabel: { formatter: (v: number) => (v >= 10000 ? `${Math.round(v / 10000)}万` : v) } },
  yAxis: { type: 'category', data: [...categoryData.value.categories].reverse(), axisLine: { show: false } },
  series: [{
    name: 'GMV', type: 'bar', data: [...categoryData.value.gmv].reverse(),
    itemStyle: { color: '#4f6ef2', borderRadius: [0, 6, 6, 0], opacity: 0.9 }, barMaxWidth: 18,
  }],
}))

/** 品类健康度四象限:X 退款率 / Y 平均评分 / 气泡大小 = GMV */
const healthOption = computed(() => {
  const items = health.value
  if (!items.length) return {}
  const rates = items.map((d) => d.refund_rate)
  const stars = items.map((d) => d.avg_star)
  const avgRate = rates.reduce((a, b) => a + b, 0) / rates.length
  const avgStar = stars.reduce((a, b) => a + b, 0) / stars.length
  const xMin = Math.min(...rates) - 0.4
  const xMax = Math.max(...rates) + 0.4
  const yMin = Math.floor((Math.min(...stars) - 0.08) * 10) / 10
  const yMax = Math.ceil((Math.max(...stars) + 0.08) * 10) / 10
  const gmvMax = Math.max(...items.map((d) => d.gmv))

  return {
    tooltip: {
      formatter: (p: { data: { name: string; value: number[] } }) => {
        const d = items.find((x) => x.category === p.data.name)
        return d
          ? `<b>${d.category}</b><br/>退款率 ${d.refund_rate}%<br/>平均评分 ${d.avg_star}<br/>GMV ¥${money(d.gmv)}`
          : ''
      },
    },
    grid: { left: 56, right: 40, top: 34, bottom: 46 },
    xAxis: { type: 'value', name: '退款率(%) →', nameLocation: 'middle', nameGap: 26, min: xMin, max: xMax, splitLine: { lineStyle: { color: '#f0f3f9' } } },
    yAxis: { type: 'value', name: '平均评分', min: yMin, max: yMax, splitLine: { lineStyle: { color: '#f0f3f9' } } },
    series: [{
      type: 'scatter',
      data: items.map((d) => ({ name: d.category, value: [d.refund_rate, d.avg_star, d.gmv] })),
      symbolSize: (val: number[]) => 12 + (Math.sqrt(val[2]) / Math.sqrt(gmvMax)) * 26,
      itemStyle: { color: 'rgba(79, 110, 242, 0.75)', borderColor: '#fff', borderWidth: 1.5 },
      label: { show: true, formatter: '{b}', position: 'top', fontSize: 11, color: '#475569' },
      markLine: {
        silent: true, symbol: 'none',
        lineStyle: { type: 'dashed', color: '#b0bccf' },
        label: { formatter: '均值', fontSize: 10, color: '#94a3b8' },
        data: [{ xAxis: avgRate }, { yAxis: avgStar }],
      },
      markArea: {
        silent: true,
        itemStyle: { color: 'rgba(229, 72, 77, 0.05)' },
        data: [[{ xAxis: avgRate, yAxis: yMin }, { xAxis: xMax, yAxis: avgStar }]],
      },
    }],
  }
})

function ask(question: string) {
  emit('ask', question)
}

async function loadAll() {
  loading.value = true
  try {
    const [o, t, c, h] = await Promise.all([
      fetchOverview(days.value),
      fetchTrend(days.value),
      fetchCategory(days.value),
      fetchCategoryHealth(days.value),
    ])
    overview.value = o
    trendDates.value = t.dates
    trendGmv.value = t.gmv
    trendOrders.value = t.orders
    categoryData.value = c
    health.value = h
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div v-loading="loading" class="dash-page">
    <div class="dash-header">
      <div>
        <h2 class="page-title">经营看板</h2>
        <p class="page-sub">核心指标与趋势 · {{ overview?.period?.[0] }} ~ {{ overview?.period?.[1] }}</p>
      </div>
      <el-radio-group v-model="days" size="small" @change="loadAll">
        <el-radio-button :value="7">近7天</el-radio-button>
        <el-radio-button :value="30">近30天</el-radio-button>
        <el-radio-button :value="90">近90天</el-radio-button>
      </el-radio-group>
    </div>

    <div class="kpi-grid">
      <el-card v-for="kpi in kpis" :key="kpi.label" shadow="never" class="kpi-card">
        <div class="kpi-top">
          <div class="kpi-icon" :class="kpi.tone">
            <el-icon :size="17"><component :is="kpi.icon" /></el-icon>
          </div>
          <div class="kpi-top-right">
            <span v-if="kpi.item.delta_pct !== null" class="delta-pill" :class="deltaClass(kpi)">
              <el-icon :size="11">
                <component :is="kpi.item.delta_pct >= 0 ? CaretTop : CaretBottom" />
              </el-icon>
              {{ Math.abs(kpi.item.delta_pct).toFixed(1) }}%
            </span>
            <el-tooltip :content="`在对话中追问:${kpi.question}`" placement="top">
              <button class="ask-btn" @click="ask(kpi.question)"><el-icon :size="13"><ChatDotRound /></el-icon></button>
            </el-tooltip>
          </div>
        </div>
        <div class="kpi-value">{{ kpi.display }}</div>
        <div class="kpi-label">{{ kpi.label }} · 环比上期</div>
      </el-card>
    </div>

    <el-row :gutter="16" class="chart-row">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <div class="chart-head">
              <div class="chart-head-left">
                <span class="chart-title">销售趋势</span>
                <span class="chart-sub">GMV 与订单量</span>
              </div>
              <el-tooltip content="在对话中追问每天的销售趋势" placement="top">
                <button class="ask-btn" @click="ask(`最近${days}天每天的销售趋势`)"><el-icon :size="13"><ChatDotRound /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
          <ChartBlock :option="trendOption" height="316px" />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>
            <div class="chart-head">
              <div class="chart-head-left">
                <span class="chart-title">品类结构</span>
                <span class="chart-sub">GMV 贡献排行</span>
              </div>
              <el-tooltip content="在对话中追问各品类的销售额排名" placement="top">
                <button class="ask-btn" @click="ask(`最近${days}天各品类的销售额排名`)"><el-icon :size="13"><ChatDotRound /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
          <ChartBlock :option="categoryOption" height="316px" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="chart-row">
      <el-col :span="24">
        <el-card shadow="never">
          <template #header>
            <div class="chart-head">
              <div class="chart-head-left">
                <span class="chart-title">品类健康度</span>
                <span class="chart-sub">虚线为均值 · 右下浅红区 = 高退款低评分的问题品类 · 气泡大小 = GMV</span>
              </div>
              <el-tooltip content="在对话中追问各品类的退款率" placement="top">
                <button class="ask-btn" @click="ask(`最近${days}天各品类的退款率`)"><el-icon :size="13"><ChatDotRound /></el-icon></button>
              </el-tooltip>
            </div>
          </template>
          <ChartBlock :option="healthOption" height="360px" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.dash-page { padding: 22px 28px; height: 100%; overflow-y: auto; }
.dash-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.page-title { font-size: 20px; font-weight: 700; color: var(--ink); }
.page-sub { font-size: 12.5px; color: var(--ink-3); margin-top: 5px; }

.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.kpi-card :deep(.el-card__body) { padding: 18px 20px; }
.kpi-top { display: flex; justify-content: space-between; align-items: center; }
.kpi-icon {
  width: 38px; height: 38px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
}
.kpi-icon.blue { background: #eef1fe; color: #4f6ef2; }
.kpi-icon.violet { background: #f3effe; color: #8b5cf6; }
.kpi-icon.green { background: #e7f8f1; color: #10b981; }
.kpi-icon.orange { background: #fef3e2; color: #f59e0b; }
.kpi-top-right { display: flex; align-items: center; gap: 7px; }
.delta-pill {
  display: inline-flex; align-items: center; gap: 2px;
  font-size: 12px; font-weight: 600;
  padding: 3px 9px; border-radius: 999px;
}
.delta-pill.good { background: #e7f8f1; color: #0d9d6d; }
.delta-pill.bad { background: #fdeaea; color: #e5484d; }
.ask-btn {
  width: 26px; height: 26px; flex: none;
  border: 1px solid var(--line); border-radius: 8px;
  background: #fff; color: var(--ink-3);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: all 0.15s ease;
}
.ask-btn:hover { color: var(--brand); border-color: #b9c6fa; background: #eef1fe; }
.kpi-value { font-size: 27px; font-weight: 700; color: var(--ink); margin: 13px 0 5px; font-variant-numeric: tabular-nums; }
.kpi-label { font-size: 12.5px; color: var(--ink-3); }

.chart-row { margin-top: 16px; }
.chart-head { display: flex; align-items: center; justify-content: space-between; }
.chart-head-left { display: flex; align-items: baseline; gap: 9px; }
.chart-title { font-size: 14.5px; font-weight: 600; color: var(--ink); }
.chart-sub { font-size: 11.5px; color: var(--ink-3); }
</style>
