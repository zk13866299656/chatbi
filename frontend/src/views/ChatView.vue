<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Promotion, Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchMessages, listConversations, removeConversation, streamChat } from '../api'
import type { ChatEvent, ChatFinal, ChatMessage, ConversationInfo, StoredMessage } from '../types'
import ChartBlock from '../components/ChartBlock.vue'

const EXAMPLES = [
  '2026年6月各品类的销售额排名',
  '2026年6月每天的销售趋势',
  '最近30天各区域的退款率',
  '上个月GMV为什么下降',
  '各支付方式的订单占比',
  '金卡会员的客单价是多少',
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
      // 新会话由后端懒创建,首个 start 事件带回会话 ID
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
</script>

<template>
  <div class="chat-page">
    <div class="conv-sidebar">
      <el-button class="new-btn" type="primary" plain :icon="Plus" @click="newConversation">新建对话</el-button>
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
    </div>

    <div class="chat-main">
      <div ref="listEl" class="msg-list">
        <div v-if="messages.length === 0" class="welcome">
          <h2>问我任何经营数据</h2>
          <p>基于 10 万级真实订单数据,自然语言直接查数、看趋势、做归因</p>
          <div class="example-chips">
            <el-tag
              v-for="example in EXAMPLES"
              :key="example"
              class="chip"
              effect="plain"
              @click="send(example)"
            >{{ example }}</el-tag>
          </div>
        </div>

        <div v-for="(msg, idx) in messages" :key="idx" class="msg-row" :class="msg.role">
          <div class="bubble" :class="msg.role">
            <template v-if="msg.role === 'user'">{{ msg.text }}</template>
            <template v-else>
              <div v-if="msg.events?.length" class="timeline">
                <div v-for="(event, eIdx) in msg.events" :key="eIdx" class="tl-item">
                  <span class="tl-dot" />
                  <span class="tl-label">{{ nodeLabel(event.node) }}</span>
                  <span class="tl-msg">{{ event.message }}</span>
                </div>
              </div>

              <div v-if="msg.final" class="final">
                <div class="final-tags">
                  <el-tag size="small" type="info" effect="plain">{{ INTENT_LABELS[msg.final.intent] ?? msg.final.intent }}</el-tag>
                  <el-tag v-if="msg.final.period?.[0]" size="small" effect="plain">{{ msg.final.period[0] }} ~ {{ msg.final.period[1] }}</el-tag>
                  <el-tag v-if="msg.final.mode === 'fallback'" size="small" type="warning" effect="plain">降级</el-tag>
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
              <div v-if="msg.streaming && !msg.final" class="loading-dot">分析中<span class="dots" /></div>
            </template>
          </div>
        </div>
      </div>

      <div class="input-bar">
        <el-input
          v-model="input"
          placeholder="例如:上个月各品类的销售额排名"
          size="large"
          :disabled="sending"
          @keydown.enter="send()"
        />
        <el-button type="primary" size="large" :icon="Promotion" :loading="sending" @click="send()">
          发送
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page { display: flex; height: 100%; }

.conv-sidebar {
  width: 220px; flex: none; display: flex; flex-direction: column;
  background: #fff; border-right: 1px solid #e5e6eb;
}
.new-btn { margin: 14px; }
.conv-scroll { flex: 1; }
.conv-item {
  position: relative; padding: 10px 28px 10px 14px;
  cursor: pointer; border-bottom: 1px solid #f2f3f5;
}
.conv-item:hover { background: #f5f7fa; }
.conv-item.active { background: #ecf5ff; border-right: 2px solid #409eff; }
.conv-title {
  font-size: 13px; color: #1d2129;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.conv-meta { font-size: 11px; color: #c0c4cc; margin-top: 3px; }
.conv-del {
  position: absolute; right: 8px; top: 12px;
  color: #c0c4cc; display: none;
}
.conv-item:hover .conv-del { display: inline-flex; }
.conv-del:hover { color: #f56c6c; }
.conv-empty { text-align: center; color: #c0c4cc; font-size: 12px; padding: 24px 0; }

.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.msg-list { flex: 1; overflow-y: auto; padding: 24px 32px; }

.welcome { text-align: center; margin-top: 12vh; color: #4e5969; }
.welcome h2 { font-size: 24px; color: #1d2129; margin-bottom: 8px; }
.welcome p { font-size: 14px; color: #86909c; }
.example-chips { margin-top: 28px; display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; }
.chip { cursor: pointer; padding: 6px 4px; }
.chip:hover { color: #409eff; border-color: #409eff; }

.msg-row { display: flex; margin-bottom: 16px; }
.msg-row.user { justify-content: flex-end; }
.bubble {
  max-width: 78%; padding: 12px 16px; border-radius: 10px;
  font-size: 14px; line-height: 1.7; word-break: break-word;
}
.bubble.user { background: #409eff; color: #fff; border-top-right-radius: 2px; }
.bubble.assistant { background: #fff; border: 1px solid #e5e6eb; border-top-left-radius: 2px; }

.timeline { border-left: 2px solid #e5e6eb; padding-left: 12px; margin-bottom: 10px; }
.tl-item { display: flex; gap: 8px; align-items: baseline; padding: 2px 0; font-size: 12px; color: #86909c; }
.tl-dot { width: 6px; height: 6px; border-radius: 50%; background: #409eff; flex: none; align-self: center; }
.tl-label { color: #4e5969; font-weight: 600; flex: none; }
.final-tags { display: flex; gap: 8px; margin-bottom: 8px; }
.final-chart { margin-top: 12px; }
.detail { margin-top: 10px; --el-collapse-border-color: transparent; }
.sql-code { font-size: 12px; background: #f7f8fa; padding: 10px; border-radius: 6px; white-space: pre-wrap; }
.error-tip { color: #f56c6c; font-size: 13px; }
.loading-dot { color: #86909c; font-size: 13px; }
.dots::after { content: '...'; animation: blink 1.2s infinite; }
@keyframes blink { 0%, 100% { opacity: 0.2; } 50% { opacity: 1; } }
.md-gap { height: 6px; }
.md-li { padding-left: 8px; }

.input-bar {
  display: flex; gap: 12px; padding: 14px 32px;
  background: #fff; border-top: 1px solid #e5e6eb;
}
</style>
