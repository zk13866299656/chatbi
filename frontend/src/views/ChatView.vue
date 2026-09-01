<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Promotion, Plus, Delete, TrendCharts, DataLine, Odometer, Aim, PieChart, Wallet } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchMessages, listConversations, removeConversation, streamChat } from '../api'
import type { ChatEvent, ChatFinal, ChatMessage, ConversationInfo, StoredMessage } from '../types'
import ChartBlock from '../components/ChartBlock.vue'

const props = defineProps<{ initialQuestion?: string }>()
const emit = defineEmits<{ (e: 'consumed'): void }>()

const SUGGESTIONS = [
  { icon: TrendCharts, text: '2026年6月各品类的销售额排名' },
  { icon: DataLine, text: '2026年6月每天的销售趋势' },
  { icon: Odometer, text: '最近30天各区域的退款率' },
  { icon: Aim, text: '上个月GMV为什么下降' },
  { icon: PieChart, text: '各支付方式的订单占比' },
  { icon: Wallet, text: '金卡会员的客单价是多少' },
]

const NODE_LABELS: Record<string, string> = {
  supervisor: '意图解析',
  dispatch_query: '链路分发',
  retrieve_schema: '表结构检索',
  retrieve_caliber: '口径/示例检索',
  retrieve_caliber_attr: '口径检索',
  generate_sql: 'SQL 生成',
  validate_sql: '安全校验',
  repair_sql: 'SQL 修复',
  execute_sql: '数据查询',
  recommend_chart: '图表推荐',
  summarize: '结论生成',
  attribution_run: '归因分析',
  small_talk: '应答',
  fallback_answer: '兜底应答',
}

const INTENT_LABELS: Record<string, string> = {
  query: '查数',
  attribution: '归因',
  chitchat: '闲聊',
}

const messages = reactive<ChatMessage[]>([])
const conversations = ref<ConversationInfo[]>([])
const currentConvId = ref<string | null>(null)
const input = ref('')
const sending = ref(false)
const listEl = ref<HTMLDivElement>()
let abort: (() => void) | null = null

function scrollToBottom() {
  nextTick(() => {
    listEl.value?.scrollTo({ top: listEl.value.scrollHeight, behavior: 'smooth' })
  })
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/** 轻量 Markdown:粗体 + 换行 + 列表,不引第三方库 */
function renderMarkdown(text: string): string {
  const lines = escapeHtml(text).split('\n')
  const html = lines.map((line) => {
    const bolded = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    if (/^[-•]\s+/.test(bolded)) return `<div class="md-li">${bolded.replace(/^[-•]\s+/, '· ')}</div>`
    if (!bolded.trim()) return '<div class="md-gap"></div>'
    return `<div>${bolded}</div>`
  })
  return html.join('')
}

function nodeLabel(node: string): string {
  return NODE_LABELS[node] ?? node
}

function fmtTime(iso: string): string {
  return (iso || '').slice(5, 16).replace('T', ' ')
}

// ============ 会话管理 ============

async function loadConversations() {
  conversations.value = await listConversations()
}

function mapStored(stored: StoredMessage[]): ChatMessage[] {
  return stored.map((m) => {
    if (m.role === 'user') return { role: 'user', text: m.content }
    const payload = m.payload as (ChatFinal & { events?: ChatEvent[] }) | null
    return {
      role: 'assistant',
      final: payload ?? undefined,
      events: payload?.events ?? [],
    }
  })
}

async function selectConversation(convId: string) {
  if (sending.value) return
  if (abort) abort()
  currentConvId.value = convId
  const stored = await fetchMessages(convId)
  messages.splice(0, messages.length, ...mapStored(stored))
  scrollToBottom()
}

function newConversation() {
  if (sending.value) return
  if (abort) abort()
  currentConvId.value = null
  messages.splice(0, messages.length)
}

async function onDelete(conv: ConversationInfo) {
  await ElMessageBox.confirm(`删除会话「${conv.title}」及其全部消息?`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await removeConversation(conv.id)
  ElMessage.success('已删除')
  if (currentConvId.value === conv.id) {
    currentConvId.value = null
    messages.splice(0, messages.length)
  }
  loadConversations()
}

onMounted(loadConversations)

// ============ 发送 ============

async function send(question?: string) {
  const q = (question ?? input.value).trim()
  if (!q || sending.value) return
  if (abort) abort()

  input.value = ''
  sending.value = true
  messages.push({ role: 'user', text: q })

  const assistant = reactive<ChatMessage>({ role: 'assistant', events: [], streaming: true })
  messages.push(assistant)
  scrollToBottom()

  const history = messages
    .filter((m) => !m.streaming && (m.final?.answer_md || m.text))
    .slice(-4)
    .map((m) => ({
      role: m.role,
      content: (m.role === 'assistant' ? m.final?.answer_md : m.text) ?? '',
    }))

  abort = streamChat(q, history, currentConvId.value, {
    onStart: (data) => {
      if (data.conversation_id) currentConvId.value = data.conversation_id
    },
    onEvent: (event: ChatEvent) => {
      assistant.events!.push(event)
      scrollToBottom()
    },
    onFinal: (final: ChatFinal) => {
      assistant.final = final
      assistant.streaming = false
      scrollToBottom()
    },
    onError: (message: string) => {
      assistant.error = message
      assistant.streaming = false
      scrollToBottom()
    },
    onDone: () => {
      assistant.streaming = false
      sending.value = false
      abort = null
      scrollToBottom()
      loadConversations()
    },
  })
}

onBeforeUnmount(() => abort?.())

// 看板联动:外部带问题进来时自动发送(若正在流式请求中则先填入输入框)
watch(
  () => props.initialQuestion,
  (q) => {
    if (!q) return
    emit('consumed')
    if (sending.value) input.value = q
    else send(q)
  },
  { immediate: true },
)
</script>

<template>
  <div class="chat-page">
    <!-- 会话栏 -->
    <aside class="conv-sidebar">
      <button class="new-btn" @click="newConversation">
        <el-icon :size="15"><Plus /></el-icon>
        <span>新建对话</span>
      </button>
      <el-scrollbar class="conv-scroll">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === currentConvId }"
          @click="selectConversation(conv.id)"
        >
          <div class="conv-title">{{ conv.title }}</div>
          <div class="conv-meta">{{ conv.message_count }} 条 · {{ fmtTime(conv.created_at) }}</div>
          <el-popconfirm title="删除该会话?" confirm-button-text="删除" cancel-button-text="取消" @confirm="onDelete(conv)">
            <template #reference>
              <el-icon class="conv-del"><Delete /></el-icon>
            </template>
          </el-popconfirm>
        </div>
        <div v-if="conversations.length === 0" class="conv-empty">暂无历史会话</div>
      </el-scrollbar>
    </aside>

    <!-- 对话区 -->
    <section class="chat-main">
      <div ref="listEl" class="msg-list">
        <div class="thread">
          <div v-if="messages.length === 0" class="welcome">
            <div class="hero-logo"><el-icon :size="26"><Odometer /></el-icon></div>
            <h1 class="hero-title">把经营数据聊明白</h1>
            <p class="hero-sub">10 万级真实订单 · 自然语言查数 · SQL 全程透明 · 异动自动归因</p>
            <div class="sug-grid">
              <div v-for="sug in SUGGESTIONS" :key="sug.text" class="sug-card" @click="send(sug.text)">
                <span class="sug-icon"><el-icon :size="15"><component :is="sug.icon" /></el-icon></span>
                <span class="sug-text">{{ sug.text }}</span>
              </div>
            </div>
          </div>

          <div v-for="(msg, idx) in messages" :key="idx" class="msg-row" :class="msg.role">
            <!-- 用户消息:右对齐渐变气泡 -->
            <div v-if="msg.role === 'user'" class="bubble user">{{ msg.text }}</div>

            <!-- AI 消息:头像 + 全宽答案卡 -->
            <template v-else>
              <div class="avatar" :class="{ thinking: msg.streaming && !msg.final }">AI</div>
              <div class="answer-card">
                <div v-if="msg.events?.length" class="timeline">
                  <div v-for="(event, eIdx) in msg.events" :key="eIdx" class="tl-item">
                    <span class="tl-dot" />
                    <span class="tl-label">{{ nodeLabel(event.node) }}</span>
                    <span class="tl-msg">{{ event.message }}</span>
                  </div>
                </div>

                <div v-if="msg.final" class="final">
                  <div class="final-tags">
                    <span class="chip chip-intent">{{ INTENT_LABELS[msg.final.intent] ?? msg.final.intent }}</span>
                    <span v-if="msg.final.period?.[0]" class="chip">{{ msg.final.period[0] }} ~ {{ msg.final.period[1] }}</span>
                    <span v-if="msg.final.mode === 'fallback'" class="chip chip-warn">降级</span>
                  </div>

                  <div class="answer" v-html="renderMarkdown(msg.final.answer_md)" />

                  <ChartBlock
                    v-if="msg.final.chart_type !== 'table' && Object.keys(msg.final.chart_spec || {}).length"
                    :option="msg.final.chart_spec"
                    :height="msg.final.chart_type === 'line' ? '300px' : '340px'"
                    class="final-chart"
                  />

                  <el-collapse class="detail">
                    <el-collapse-item title="查看生成的 SQL" name="sql">
                      <pre class="sql-code">{{ msg.final.sql || '(降级/归因模式:使用内置模板查询)' }}</pre>
                    </el-collapse-item>
                    <el-collapse-item :title="`原始数据(${msg.final.row_count} 行)`" name="rows">
                      <el-table :data="msg.final.rows.slice(0, 50)" size="small" max-height="320">
                        <el-table-column
                          v-for="(col, cIdx) in msg.final.columns"
                          :key="col"
                          :prop="String(cIdx)"
                          :label="col"
                          :formatter="(row: unknown[]) => (typeof row[cIdx] === 'number' ? row[cIdx].toLocaleString() : row[cIdx])"
                        />
                      </el-table>
                    </el-collapse-item>
                  </el-collapse>
                </div>

                <div v-if="msg.error" class="error-tip">请求失败:{{ msg.error }}</div>
                <div v-if="msg.streaming && !msg.final" class="loading-dot">正在分析<span class="dots" /></div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <div class="input-bar">
        <div class="input-inner">
          <el-input
            v-model="input"
            placeholder="输入你的数据问题,例如:上个月各品类的销售额排名"
            size="large"
            :disabled="sending"
            @keydown.enter="send()"
          />
          <button class="send-btn" :disabled="sending" @click="send()">
            <el-icon :size="17"><Promotion /></el-icon>
          </button>
        </div>
        <div class="input-hint">Enter 发送 · 生成 SQL 会先经过安全校验再执行</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.chat-page { display: flex; height: 100%; }

/* ============ 会话栏 ============ */
.conv-sidebar {
  width: 232px; flex: none; display: flex; flex-direction: column;
  background: #fbfcfe; border-right: 1px solid var(--line);
}
.new-btn {
  margin: 14px; padding: 10px 0;
  display: flex; align-items: center; justify-content: center; gap: 6px;
  background: var(--brand-grad); color: #fff;
  border: none; border-radius: 10px; font-size: 13.5px; font-weight: 600;
  cursor: pointer; transition: all 0.18s ease;
  box-shadow: 0 4px 12px rgba(79, 110, 242, 0.3);
}
.new-btn:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(79, 110, 242, 0.4); }
.new-btn:active { transform: translateY(0); }
.conv-scroll { flex: 1; padding: 0 10px; }
.conv-item {
  position: relative; padding: 10px 30px 10px 12px; margin-bottom: 4px;
  border-radius: 10px; cursor: pointer; transition: all 0.15s ease;
  border: 1px solid transparent;
}
.conv-item:hover { background: #eef2fd; }
.conv-item.active { background: #eef1fe; border-color: #c7d0fa; }
.conv-title {
  font-size: 13px; color: var(--ink); font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.conv-meta { font-size: 11px; color: var(--ink-3); margin-top: 3px; }
.conv-del {
  position: absolute; right: 9px; top: 13px;
  color: #b6c0d2; display: none;
}
.conv-item:hover .conv-del { display: inline-flex; }
.conv-del:hover { color: #ef4444; }
.conv-empty { text-align: center; color: var(--ink-3); font-size: 12px; padding: 26px 0; }

/* ============ 对话区 ============ */
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.msg-list { flex: 1; overflow-y: auto; padding: 28px 32px 12px; }
.thread { max-width: 880px; margin: 0 auto; }

.welcome { text-align: center; padding-top: 9vh; }
.hero-logo {
  width: 58px; height: 58px; margin: 0 auto 18px; border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  background: var(--brand-grad); color: #fff;
  box-shadow: 0 10px 28px rgba(79, 110, 242, 0.4);
}
.hero-title { font-size: 27px; font-weight: 700; color: var(--ink); letter-spacing: 0.5px; }
.hero-sub { font-size: 13.5px; color: var(--ink-3); margin-top: 10px; }
.sug-grid {
  margin: 34px auto 0; max-width: 640px;
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
}
.sug-card {
  display: flex; align-items: center; gap: 10px;
  padding: 13px 15px; background: #fff;
  border: 1px solid var(--line); border-radius: 12px;
  cursor: pointer; transition: all 0.18s ease;
  text-align: left;
}
.sug-card:hover {
  border-color: #b9c6fa; transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(79, 110, 242, 0.12);
}
.sug-icon {
  width: 30px; height: 30px; flex: none; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  background: #eef1fe; color: var(--brand);
}
.sug-text { font-size: 12.5px; color: var(--ink-2); }

/* ============ 消息 ============ */
.msg-row { display: flex; margin-bottom: 20px; gap: 11px; }
.msg-row.user { justify-content: flex-end; }
.bubble.user {
  max-width: 72%; padding: 11px 16px;
  background: var(--brand-grad); color: #fff;
  border-radius: 14px 14px 4px 14px;
  font-size: 14px; line-height: 1.7; word-break: break-word;
  box-shadow: 0 4px 14px rgba(79, 110, 242, 0.25);
}
.avatar {
  width: 34px; height: 34px; flex: none; margin-top: 2px;
  border-radius: 10px; display: flex; align-items: center; justify-content: center;
  background: var(--brand-grad); color: #fff;
  font-size: 12px; font-weight: 700; letter-spacing: 0.5px;
}
.avatar.thinking { animation: pulse 1.4s ease-in-out infinite; }
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(79, 110, 242, 0.35); }
  50% { box-shadow: 0 0 0 7px rgba(79, 110, 242, 0); }
}
.answer-card {
  flex: 1; min-width: 0;
  background: #fff; border: 1px solid var(--line); border-radius: 4px 14px 14px 14px;
  padding: 14px 18px 12px;
  box-shadow: var(--card-shadow);
}

.timeline { border-left: 2px solid #edf0f7; padding-left: 12px; margin-bottom: 12px; }
.tl-item { display: flex; gap: 8px; align-items: baseline; padding: 2.5px 0; font-size: 12px; }
.tl-dot {
  width: 7px; height: 7px; border-radius: 50%; flex: none; align-self: center;
  background: var(--brand); box-shadow: 0 0 0 3px #eef1fe;
}
.tl-label { color: var(--ink-2); font-weight: 600; flex: none; }
.tl-msg { color: var(--ink-3); }

.final-tags { display: flex; gap: 7px; margin-bottom: 10px; flex-wrap: wrap; }
.chip {
  display: inline-flex; align-items: center;
  font-size: 11px; padding: 2.5px 9px; border-radius: 999px;
  background: #f1f4f9; color: var(--ink-2);
}
.chip-intent { background: #eef1fe; color: var(--brand); font-weight: 600; }
.chip-warn { background: #fef3e2; color: #b45309; }

.answer { font-size: 14px; line-height: 1.8; color: var(--ink); }
.final-chart { margin-top: 14px; }
.detail { margin-top: 10px; --el-collapse-border-color: transparent; }
.sql-code {
  font-size: 12px; font-family: 'JetBrains Mono', Consolas, monospace;
  background: #f6f8fb; border: 1px solid var(--line);
  padding: 12px 14px; border-radius: 8px; white-space: pre-wrap;
  color: #334155;
}
.error-tip { color: #ef4444; font-size: 13px; }
.loading-dot { color: var(--ink-3); font-size: 13px; }
.dots::after { content: '...'; animation: blink 1.2s infinite; }
@keyframes blink { 0%, 100% { opacity: 0.2; } 50% { opacity: 1; } }
.md-gap { height: 6px; }
.md-li { padding-left: 8px; }

/* ============ 输入区 ============ */
.input-bar { padding: 14px 32px 10px; background: transparent; }
.input-inner {
  max-width: 880px; margin: 0 auto;
  display: flex; gap: 10px; align-items: center;
  background: #fff; border: 1px solid var(--line); border-radius: 14px;
  padding: 7px 7px 7px 16px;
  box-shadow: var(--card-shadow);
  transition: all 0.18s ease;
}
.input-inner:focus-within {
  border-color: #b9c6fa;
  box-shadow: 0 0 0 3px rgba(79, 110, 242, 0.12), var(--card-shadow);
}
.input-inner :deep(.el-input__wrapper) { box-shadow: none !important; background: transparent; }
.send-btn {
  width: 40px; height: 40px; flex: none;
  border: none; border-radius: 11px; cursor: pointer;
  background: var(--brand-grad); color: #fff;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.18s ease;
}
.send-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 5px 14px rgba(79, 110, 242, 0.4); }
.send-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.input-hint {
  max-width: 880px; margin: 7px auto 0;
  font-size: 11px; color: #a8b3c5; text-align: center;
}
</style>
