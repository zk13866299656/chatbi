import axios from 'axios'
import type { CategoryData, ChatEvent, ChatFinal, ConversationInfo, OverviewData, SemanticLayer, StoredMessage, TrendData } from '../types'

const http = axios.create({ baseURL: '/api', timeout: 120000 })

export async function fetchHealth(): Promise<{ llm_enabled: boolean; mode: string }> {
  const { data } = await http.get('/health')
  return data.data
}

export async function listConversations(): Promise<ConversationInfo[]> {
  const { data } = await http.get('/conversations')
  return data.data
}

export async function fetchMessages(conversationId: string): Promise<StoredMessage[]> {
  const { data } = await http.get(`/conversations/${conversationId}/messages`)
  return data.data
}

export async function removeConversation(conversationId: string): Promise<void> {
  await http.delete(`/conversations/${conversationId}`)
}

export async function fetchOverview(days = 30): Promise<OverviewData> {
  const { data } = await http.get('/dashboard/overview', { params: { days } })
  return data.data
}

export async function fetchTrend(days = 30): Promise<TrendData> {
  const { data } = await http.get('/dashboard/trend', { params: { days } })
  return data.data
}

export async function fetchCategory(days = 30): Promise<CategoryData> {
  const { data } = await http.get('/dashboard/category', { params: { days } })
  return data.data
}

export interface CategoryHealthItem {
  category: string
  gmv: number
  refund_rate: number
  avg_star: number
}

export async function fetchCategoryHealth(days = 30): Promise<CategoryHealthItem[]> {
  const { data } = await http.get('/dashboard/category-health', { params: { days } })
  return data.data
}

export async function fetchSemanticLayer(): Promise<SemanticLayer> {
  const { data } = await http.get('/meta/semantic-layer')
  return data.data
}

/**
 * SSE 流式对话:POST /chat/stream,逐行解析 data: 事件。
 * 返回 abort 函数,组件卸载或重新提问时可中断。
 */
export function streamChat(
  question: string,
  history: { role: string; content: string }[],
  conversationId: string | null,
  handlers: {
    onStart?: (data: { conversation_id?: string }) => void
    onEvent: (event: ChatEvent) => void
    onFinal: (final: ChatFinal) => void
    onError: (message: string) => void
    onDone: () => void
  },
): () => void {
  const controller = new AbortController()
  ;(async () => {
    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, history, conversation_id: conversationId }),
        signal: controller.signal,
      })
      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`)
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''
        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const payload = line.slice(5).trim()
          if (payload === '[DONE]') {
            handlers.onDone()
            return
          }
          const event = JSON.parse(payload)
          if (event.type === 'start') handlers.onStart?.(event)
          else if (event.type === 'node') handlers.onEvent(event)
          else if (event.type === 'final') handlers.onFinal(event)
          else if (event.type === 'error') handlers.onError(event.message)
        }
      }
      handlers.onDone()
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      handlers.onError((err as Error).message || '网络错误')
    }
  })()
  return () => controller.abort()
}
