// 与后端 API 对应的类型定义

export interface ChatEvent {
  node: string
  message: string
  mode?: string
  [key: string]: unknown
}

export interface ChatFinal {
  question: string
  intent: string
  answer_md: string
  sql: string
  columns: string[]
  rows: unknown[][]
  row_count: number
  chart_type: 'line' | 'bar' | 'pie' | 'table'
  chart_spec: Record<string, unknown>
  mode: 'llm' | 'fallback'
  period: (string | null)[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  text?: string
  events?: ChatEvent[]
  final?: ChatFinal
  streaming?: boolean
  error?: string
}

export interface KpiItem {
  value: number
  delta_pct: number | null
}

export interface OverviewData {
  days: number
  gmv: KpiItem
  orders: KpiItem
  aov: KpiItem
  refund_rate: KpiItem
  period: string[]
}

export interface TrendData {
  dates: string[]
  gmv: number[]
  orders: number[]
}

export interface CategoryData {
  categories: string[]
  gmv: number[]
}

export interface SemanticField {
  name: string
  comment: string
}

export interface SemanticTable {
  name: string
  meaning: string
  fields: SemanticField[]
}

export interface SemanticMetric {
  metric: string
  definition: string
  note?: string
}

export interface SemanticLayer {
  tables: SemanticTable[]
  metrics: SemanticMetric[]
  examples: { question: string }[]
}
