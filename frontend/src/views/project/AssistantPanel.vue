<template>
  <el-drawer
    v-model="visible"
    direction="rtl"
    :size="drawerSize"
    :with-header="false"
    class="assistant-drawer"
    destroy-on-close
    :modal="!maximized"
    @opened="onOpened"
  >
    <div class="assistant-shell" :class="{ maximized, minimized }">
      <div
        v-if="!maximized"
        class="resize-handle"
        title="拖动调整宽度"
        @mousedown.prevent="startResize"
      />

      <header class="panel-header">
        <div class="header-left">
          <div class="brand-avatar">助</div>
          <div class="brand-text">
            <div class="brand-title">创作助手</div>
            <div class="brand-sub">
              {{ textProvider ? `文本：${textProvider}` : '基于项目上下文' }}
              <span v-if="activeTaskId" class="live-dot">生成中</span>
            </div>
          </div>
        </div>
        <div class="header-actions">
          <el-tooltip content="会话列表" placement="bottom">
            <el-button link :icon="ChatLineRound" @click="sessionSidebarOpen = !sessionSidebarOpen" />
          </el-tooltip>
          <el-tooltip :content="minimized ? '展开' : '最小化'" placement="bottom">
            <el-button link :icon="minimized ? FullScreen : Minus" @click="toggleMinimize" />
          </el-tooltip>
          <el-tooltip :content="maximized ? '还原' : '最大化'" placement="bottom">
            <el-button link :icon="maximized ? CopyDocument : FullScreen" @click="toggleMaximize" />
          </el-tooltip>
          <el-button link :icon="Close" @click="visible = false" />
        </div>
      </header>

      <div v-show="!minimized" class="panel-body">
        <aside v-show="sessionSidebarOpen" class="session-sidebar">
          <div class="session-toolbar">
            <span>会话</span>
            <el-button link type="primary" size="small" :disabled="busy" @click="createSession">新建</el-button>
          </div>
          <div class="session-list" v-loading="sessionsLoading">
            <button
              v-for="item in sessions"
              :key="item.id"
              type="button"
              class="session-item"
              :class="{ active: item.id === conversationId, archived: item.status === 'archived' }"
              @click="switchSession(item)"
            >
              <div class="session-title">{{ item.title || `会话 #${item.id}` }}</div>
              <div class="session-meta">
                <span>{{ item.message_count ?? 0 }} 条</span>
                <span v-if="item.status === 'archived'">已归档</span>
              </div>
            </button>
            <div v-if="!sessionsLoading && !sessions.length" class="session-empty">暂无会话</div>
          </div>
        </aside>

        <div class="chat-main">
          <el-alert
            v-if="toolsEnabled === false"
            type="warning"
            :closable="false"
            show-icon
            class="provider-banner"
            title="当前文本模型非 OpenAI 兼容，助手无法调用工具读写项目或派发任务。可在「模型配置」切换文本默认供应商。"
          />

          <div class="quick-chips">
            <button
              v-for="chip in quickChips"
              :key="chip"
              type="button"
              class="chip"
              :disabled="busy"
              @click="applyChip(chip)"
            >
              {{ chip }}
            </button>
          </div>

          <div ref="listRef" class="message-list" v-loading="loading">
            <div v-if="!loading && !displayMessages.length" class="empty">
              <div class="empty-avatar">AI</div>
              <p>可以问我：设定是否自洽、角色弧线、分镜节奏、下一章怎么写…</p>
              <p class="empty-sub">耗时生成也可让我派发后台任务；也可继续用页面按钮。</p>
            </div>

            <div
              v-for="item in displayMessages"
              :key="item.key"
              class="bubble-row"
              :class="item.role"
            >
              <div class="avatar" :class="item.role">
                {{ item.role === 'user' ? '你' : 'AI' }}
              </div>
              <div class="bubble">
                <div class="bubble-content">
                  {{ item.content }}<span v-if="item.streaming" class="cursor">_</span>
                </div>
                <div v-if="item.toolTags?.length" class="tool-tags">
                  <el-tag
                    v-for="tag in item.toolTags"
                    :key="tag.key"
                    size="small"
                    effect="plain"
                    :type="tag.type"
                  >
                    {{ tag.label }}
                  </el-tag>
                </div>
                <div v-if="item.dispatchCards?.length" class="dispatch-cards">
                  <div v-for="card in item.dispatchCards" :key="card.key" class="dispatch-card">
                    <div class="dispatch-title">已派发：{{ card.taskType || card.name }}</div>
                    <div class="dispatch-id mono">{{ card.taskId }}</div>
                    <el-button link type="primary" size="small" @click="emit('open-terminal', card.taskId)">
                      查看任务
                    </el-button>
                  </div>
                </div>
                <div v-if="item.progressHint" class="progress-hint">{{ item.progressHint }}</div>
                <div class="bubble-meta">
                  <span>{{ item.role === 'user' ? '你' : '助手' }}</span>
                  <span v-if="item.created_at">{{ formatTime(item.created_at) }}</span>
                  <el-button
                    v-if="item.task_id && !item.streaming"
                    link
                    type="primary"
                    size="small"
                    @click="emit('open-terminal', item.task_id)"
                  >
                    查看任务
                  </el-button>
                  <el-button
                    v-if="item.content && !item.streaming"
                    link
                    size="small"
                    @click="copyText(item.content)"
                  >
                    复制
                  </el-button>
                  <el-button
                    v-if="item.role === 'assistant' && item.id && !item.streaming && !item.superseded"
                    link
                    size="small"
                    :disabled="busy"
                    @click="regenerate(item.id)"
                  >
                    重新生成
                  </el-button>
                </div>
              </div>
            </div>
          </div>

          <div class="composer">
            <div class="composer-options">
              <el-switch
                v-model="allowWrites"
                size="small"
                inline-prompt
                active-text="写库"
                inactive-text="只读"
                :disabled="busy"
              />
              <span class="option-hint">{{ allowWrites ? '允许 create/update/start' : '仅只读工具' }}</span>
            </div>
            <el-input
              v-model="draft"
              type="textarea"
              :rows="3"
              resize="none"
              maxlength="8000"
              show-word-limit
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              :disabled="busy"
              @keydown="onKeydown"
            />
            <div class="composer-actions">
              <el-button size="small" :disabled="busy || loading" @click="clearConversation">新会话</el-button>
              <div class="composer-right">
                <el-button v-if="activeTaskId" @click="cancelActive">停止</el-button>
                <el-button type="primary" :loading="sending" :disabled="!draft.trim() || !!activeTaskId" @click="send">
                  发送
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatLineRound,
  Close,
  CopyDocument,
  FullScreen,
  Minus,
} from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  projectId: { type: String, required: true },
})

const emit = defineEmits(['update:modelValue', 'task-started', 'open-terminal', 'project-mutated'])

const WRITE_TOOL_PREFIXES = ['create_', 'update_']
const WIDTH_KEY = 'assistant_panel_width'
const MIN_WIDTH = 360
const MAX_WIDTH = 960
const DEFAULT_WIDTH = 460

const isWriteTool = (name) =>
  typeof name === 'string' && WRITE_TOOL_PREFIXES.some((p) => name.startsWith(p))
const isStartTool = (name) => typeof name === 'string' && name.startsWith('start_')

const quickChips = [
  '检查设定是否自洽',
  '分析主要角色弧线',
  '帮我规划下一章',
  '看看分镜节奏',
  '搜索章节里的关键冲突',
]

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const loading = ref(false)
const sessionsLoading = ref(false)
const sending = ref(false)
const draft = ref('')
const messages = ref([])
const sessions = ref([])
const conversationId = ref(null)
const listRef = ref(null)
const activeTaskId = ref('')
const streamPreview = ref('')
const streamChars = ref(0)
const activeToolCalls = ref([])
const taskMessage = ref('')
const toolsEnabled = ref(null)
const textProvider = ref(null)
const allowWrites = ref(true)
const sessionSidebarOpen = ref(true)
const maximized = ref(false)
const minimized = ref(false)
const panelWidth = ref(Number(localStorage.getItem(WIDTH_KEY)) || DEFAULT_WIDTH)

let eventSource = null
let pollTimer = null
let sseFallbackActive = false
let resizing = false

const busy = computed(() => sending.value || !!activeTaskId.value)

const drawerSize = computed(() => {
  if (maximized.value) return '100%'
  if (minimized.value) return '72px'
  return `${panelWidth.value}px`
})

const buildToolTags = (calls) => {
  if (!Array.isArray(calls) || !calls.length) return []
  return calls.map((c, index) => {
    const name = c?.name || '?'
    const ok = c?.ok
    let type = 'info'
    let suffix = ''
    if (c?.blocked) {
      type = 'warning'
      suffix = ' 🔒'
    } else if (ok === true) {
      type = 'success'
      suffix = ' ✓'
    } else if (ok === false) {
      type = 'danger'
      suffix = ' ✗'
    } else {
      type = 'warning'
      suffix = ' …'
    }
    return {
      key: `${name}-${index}`,
      label: `${name}${suffix}`,
      type,
    }
  })
}

const buildDispatchCards = (calls) => {
  if (!Array.isArray(calls)) return []
  return calls
    .filter((c) => isStartTool(c?.name) && c?.ok !== false)
    .map((c, index) => {
      const taskId = c?.result?.task_id || c?.result?.taskId
      if (!taskId) return null
      return {
        key: `${taskId}-${index}`,
        name: c.name,
        taskId,
        taskType: c?.result?.task_type || c?.result?.taskType || '',
      }
    })
    .filter(Boolean)
}

const extractToolCalls = (payload) => {
  const calls = payload?.tool_calls || payload?.toolCalls || []
  return Array.isArray(calls) ? calls : []
}

const displayMessages = computed(() => {
  const rows = messages.value
    .filter((item) => !(item.role === 'assistant' && (item.payload || {}).superseded))
    .map((item) => {
      const calls = extractToolCalls(item.payload)
      return {
        key: `m-${item.id}`,
        id: item.id,
        role: item.role,
        content: item.content || '',
        created_at: item.created_at,
        task_id: item.task_id,
        streaming: false,
        superseded: !!(item.payload || {}).superseded,
        toolTags: buildToolTags(calls),
        dispatchCards: buildDispatchCards(calls),
        progressHint: '',
      }
    })

  const hasStreamingAssistant = rows.some(
    (row) => row.role === 'assistant' && row.task_id === activeTaskId.value && row.content
  )
  if (activeTaskId.value && (streamPreview.value || activeToolCalls.value.length || taskMessage.value)) {
    if (!hasStreamingAssistant) {
      rows.push({
        key: `stream-${activeTaskId.value}`,
        id: null,
        role: 'assistant',
        content: streamPreview.value || '…',
        created_at: null,
        task_id: activeTaskId.value,
        streaming: true,
        superseded: false,
        toolTags: buildToolTags(activeToolCalls.value),
        dispatchCards: buildDispatchCards(activeToolCalls.value),
        progressHint: taskMessage.value,
      })
    } else {
      const target = [...rows].reverse().find(
        (row) => row.role === 'assistant' && row.task_id === activeTaskId.value
      )
      if (target) {
        if (!target.content || target.content.length < streamPreview.value.length) {
          target.content = streamPreview.value || target.content
        }
        target.streaming = true
        if (activeToolCalls.value.length) {
          target.toolTags = buildToolTags(activeToolCalls.value)
          target.dispatchCards = buildDispatchCards(activeToolCalls.value)
        }
        target.progressHint = taskMessage.value
      }
    }
  }
  return rows
})

const formatTime = (value) => {
  if (!value) return ''
  try {
    return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

const scrollToBottom = async () => {
  await nextTick()
  const el = listRef.value
  if (el) el.scrollTop = el.scrollHeight
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const stopEvents = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  stopPolling()
  sseFallbackActive = false
}

const handleTaskTerminal = async (task) => {
  const result = task.result || {}
  const toolCalls = Array.isArray(result.tool_calls) ? result.tool_calls : []
  const writeTools = [...new Set(toolCalls.map((c) => c?.name).filter(isWriteTool))]
  const startTools = toolCalls.filter((c) => isStartTool(c?.name))
  const dispatchedTaskIds = [
    ...new Set(startTools.map((c) => c?.result?.task_id || c?.result?.taskId).filter(Boolean)),
  ]

  stopEvents()
  activeTaskId.value = ''
  streamPreview.value = ''
  streamChars.value = 0
  activeToolCalls.value = []
  taskMessage.value = ''

  await fetchMessages()
  await scrollToBottom()

  if (task.status === 'failed') {
    ElMessage.error(task.message || '助手回复失败')
  } else if (task.status === 'cancelled') {
    ElMessage.info('已停止生成')
  } else if (task.status === 'completed') {
    if (writeTools.length) {
      emit('project-mutated', { task_id: task.id, tool_names: writeTools })
    }
    if (startTools.length) {
      emit('task-started', dispatchedTaskIds[0] || task.id)
    }
  }
}

const applyTaskState = async (task) => {
  if (!task) return
  const result = task.result || {}
  if (result.stream_preview) {
    streamPreview.value = result.stream_preview
    streamChars.value = result.stream_chars || streamPreview.value.length
    await scrollToBottom()
  }
  if (Array.isArray(result.tool_calls)) {
    activeToolCalls.value = result.tool_calls
  }
  if (typeof result.tools_enabled === 'boolean') {
    toolsEnabled.value = result.tools_enabled
  }
  if (result.text_provider) {
    textProvider.value = result.text_provider
  }
  if (task.message) {
    taskMessage.value = task.message
  }
  if (['completed', 'failed', 'cancelled'].includes(task.status)) {
    await handleTaskTerminal(task)
  }
}

const pollTaskOnce = async (taskId) => {
  if (!taskId) return
  try {
    const res = await axios.get(`/api/v1/tasks/${taskId}`)
    await applyTaskState(res.data)
  } catch (error) {
    console.error(error)
  }
}

const startPolling = (taskId) => {
  stopPolling()
  pollTaskOnce(taskId)
  pollTimer = setInterval(() => pollTaskOnce(taskId), 1000)
}

const startEvents = (taskId) => {
  stopEvents()
  activeTaskId.value = taskId
  streamPreview.value = ''
  streamChars.value = 0
  activeToolCalls.value = []
  taskMessage.value = '等待生成…'
  sseFallbackActive = false

  if (!window.EventSource) {
    startPolling(taskId)
    return
  }

  const url = `/api/v1/tasks/${taskId}/events`
  eventSource = new EventSource(url)
  const source = eventSource

  const onState = async (event) => {
    try {
      const data = JSON.parse(event.data)
      const task = data.task || data
      await applyTaskState(task)
    } catch (error) {
      console.error(error)
    }
  }

  source.addEventListener('task_state', onState)
  source.addEventListener('done', onState)
  source.addEventListener('error', () => {
    if (eventSource !== source || sseFallbackActive) return
    sseFallbackActive = true
    source.close()
    if (eventSource === source) eventSource = null
    startPolling(taskId)
  })
}

const fetchMessages = async () => {
  const res = await axios.get(`/api/v1/projects/${props.projectId}/assistant/messages`, {
    params: {
      limit: 100,
      conversation_id: conversationId.value || undefined,
    },
  })
  messages.value = res.data || []
}

const fetchSessions = async () => {
  sessionsLoading.value = true
  try {
    const res = await axios.get(`/api/v1/projects/${props.projectId}/assistant/conversations`, {
      params: { include_archived: true, limit: 50 },
    })
    sessions.value = res.data || []
  } catch (error) {
    console.error(error)
  } finally {
    sessionsLoading.value = false
  }
}

const loadConversation = async () => {
  loading.value = true
  try {
    const conv = await axios.get(`/api/v1/projects/${props.projectId}/assistant/conversation`)
    conversationId.value = conv.data.id
    toolsEnabled.value = typeof conv.data.tools_enabled === 'boolean' ? conv.data.tools_enabled : null
    textProvider.value = conv.data.text_provider || null
    await Promise.all([fetchMessages(), fetchSessions()])
    if (conv.data.active_task_id) {
      startEvents(conv.data.active_task_id)
    }
    await scrollToBottom()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '加载创作助手失败')
  } finally {
    loading.value = false
  }
}

const onOpened = () => {
  minimized.value = false
  loadConversation()
}

const parseErrorDetail = (error) => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && detail.message) return detail.message
  return '发送失败'
}

const send = async () => {
  const content = draft.value.trim()
  if (!content || busy.value) return
  sending.value = true
  try {
    const res = await axios.post(`/api/v1/projects/${props.projectId}/assistant/messages`, {
      content,
      conversation_id: conversationId.value || undefined,
      allow_writes: allowWrites.value,
    })
    draft.value = ''
    conversationId.value = res.data.conversation_id
    messages.value = [...messages.value, res.data.user_message]
    emit('task-started', res.data.task_id)
    startEvents(res.data.task_id)
    await fetchSessions()
    await scrollToBottom()
  } catch (error) {
    console.error(error)
    if (error?.response?.status === 409) {
      const detail = error?.response?.data?.detail
      const taskId = typeof detail === 'object' ? detail.task_id : null
      ElMessage.warning(parseErrorDetail(error))
      if (taskId) startEvents(taskId)
    } else {
      ElMessage.error(parseErrorDetail(error))
    }
  } finally {
    sending.value = false
  }
}

const regenerate = async (messageId) => {
  if (!messageId || busy.value) return
  sending.value = true
  try {
    const res = await axios.post(
      `/api/v1/projects/${props.projectId}/assistant/messages/${messageId}/regenerate`,
      { allow_writes: allowWrites.value }
    )
    conversationId.value = res.data.conversation_id
    emit('task-started', res.data.task_id)
    startEvents(res.data.task_id)
    await scrollToBottom()
  } catch (error) {
    console.error(error)
    if (error?.response?.status === 409) {
      const detail = error?.response?.data?.detail
      const taskId = typeof detail === 'object' ? detail.task_id : null
      ElMessage.warning(parseErrorDetail(error))
      if (taskId) startEvents(taskId)
    } else {
      ElMessage.error(parseErrorDetail(error) || '重新生成失败')
    }
  } finally {
    sending.value = false
  }
}

const cancelActive = async () => {
  if (!activeTaskId.value) return
  try {
    await axios.post(`/api/v1/tasks/${activeTaskId.value}/cancel`)
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '取消失败')
  }
}

const onKeydown = (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

const applyChip = (text) => {
  if (busy.value) return
  draft.value = text
}

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

const createSession = async () => {
  try {
    const res = await axios.post(`/api/v1/projects/${props.projectId}/assistant/conversations`, {
      title: `会话 ${new Date().toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`,
    })
    conversationId.value = res.data.id
    toolsEnabled.value = typeof res.data.tools_enabled === 'boolean' ? res.data.tools_enabled : toolsEnabled.value
    messages.value = []
    stopEvents()
    activeTaskId.value = ''
    await fetchSessions()
    ElMessage.success('已新建会话')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '新建会话失败')
  }
}

const switchSession = async (item) => {
  if (!item || item.id === conversationId.value) return
  stopEvents()
  activeTaskId.value = ''
  streamPreview.value = ''
  activeToolCalls.value = []
  taskMessage.value = ''
  conversationId.value = item.id
  loading.value = true
  try {
    if (item.status === 'archived') {
      await axios.patch(`/api/v1/projects/${props.projectId}/assistant/conversations/${item.id}`, {
        status: 'active',
      })
    }
    await fetchMessages()
    const active = item.active_task_id
    if (active) startEvents(active)
    await fetchSessions()
    await scrollToBottom()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '切换会话失败')
  } finally {
    loading.value = false
  }
}

const clearConversation = async () => {
  try {
    await ElMessageBox.confirm('将归档当前会话并开启新对话，历史仍保留在会话列表中。', '新会话', {
      type: 'warning',
      confirmButtonText: '开启',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    stopEvents()
    activeTaskId.value = ''
    streamPreview.value = ''
    activeToolCalls.value = []
    taskMessage.value = ''
    const res = await axios.post(`/api/v1/projects/${props.projectId}/assistant/conversation/clear`)
    conversationId.value = res.data.id
    toolsEnabled.value = typeof res.data.tools_enabled === 'boolean' ? res.data.tools_enabled : toolsEnabled.value
    messages.value = []
    await fetchSessions()
    ElMessage.success('已开启新会话')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '清空失败')
  }
}

const toggleMaximize = () => {
  maximized.value = !maximized.value
  if (maximized.value) minimized.value = false
}

const toggleMinimize = () => {
  minimized.value = !minimized.value
  if (minimized.value) maximized.value = false
}

const startResize = (event) => {
  if (maximized.value || minimized.value) return
  resizing = true
  const startX = event.clientX
  const startWidth = panelWidth.value

  const onMove = (e) => {
    if (!resizing) return
    const delta = startX - e.clientX
    const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + delta))
    panelWidth.value = next
  }
  const onUp = () => {
    resizing = false
    localStorage.setItem(WIDTH_KEY, String(panelWidth.value))
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) stopEvents()
  }
)

watch(
  () => props.projectId,
  () => {
    stopEvents()
    messages.value = []
    sessions.value = []
    conversationId.value = null
    activeTaskId.value = ''
    if (props.modelValue) loadConversation()
  }
)

onBeforeUnmount(() => {
  stopEvents()
})
</script>

<style scoped>
.assistant-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.05), transparent 120px), var(--app-surface, #111);
}

.resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  z-index: 3;
}
.resize-handle:hover {
  background: rgba(245, 158, 11, 0.25);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--app-border);
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.brand-avatar,
.avatar,
.empty-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
  color: #1f1300;
  background: linear-gradient(135deg, #f59e0b, #fbbf24);
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.2);
}
.avatar.user {
  background: linear-gradient(135deg, #60a5fa, #93c5fd);
  color: #0b1a33;
}
.avatar.assistant,
.avatar.system {
  background: linear-gradient(135deg, #f59e0b, #fbbf24);
}
.brand-text {
  min-width: 0;
}
.brand-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--app-text);
}
.brand-sub {
  font-size: 11px;
  color: var(--app-text-secondary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.live-dot {
  color: #f59e0b;
}
.live-dot::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 4px;
  border-radius: 50%;
  background: #f59e0b;
  box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.6);
  animation: pulse 1.4s infinite;
}
@keyframes pulse {
  70% { box-shadow: 0 0 0 6px rgba(245, 158, 11, 0); }
  100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.session-sidebar {
  width: 148px;
  flex-shrink: 0;
  border-right: 1px solid var(--app-border);
  display: flex;
  flex-direction: column;
  background: rgba(0, 0, 0, 0.12);
}
.session-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}
.session-item {
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  color: var(--app-text);
  border-radius: 8px;
  padding: 8px;
  cursor: pointer;
  margin-bottom: 4px;
}
.session-item:hover {
  background: rgba(255, 255, 255, 0.04);
}
.session-item.active {
  border-color: rgba(245, 158, 11, 0.45);
  background: rgba(245, 158, 11, 0.12);
}
.session-item.archived {
  opacity: 0.7;
}
.session-title {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  margin-top: 4px;
  display: flex;
  justify-content: space-between;
  gap: 6px;
  font-size: 10px;
  color: var(--app-text-secondary);
}
.session-empty {
  padding: 16px 8px;
  text-align: center;
  font-size: 12px;
  color: var(--app-text-secondary);
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 10px 10px;
  min-height: 0;
}

.provider-banner {
  flex-shrink: 0;
}

.quick-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex-shrink: 0;
}
.chip {
  border: 1px solid var(--app-border);
  background: var(--app-surface-2, rgba(255, 255, 255, 0.04));
  color: var(--app-text-secondary);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
}
.chip:hover:not(:disabled) {
  border-color: rgba(245, 158, 11, 0.45);
  color: var(--app-text);
}
.chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.message-list {
  flex: 1;
  min-height: 180px;
  overflow-y: auto;
  padding: 8px 4px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius, 10px);
}
.empty {
  margin: auto;
  text-align: center;
  color: var(--app-text-secondary);
  padding: 24px 16px;
  font-size: 13px;
  line-height: 1.6;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.empty-avatar {
  width: 48px;
  height: 48px;
  font-size: 14px;
  margin-bottom: 4px;
}
.empty-sub {
  font-size: 12px;
  opacity: 0.85;
}

.bubble-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.bubble-row.user {
  flex-direction: row-reverse;
}
.bubble {
  max-width: calc(100% - 46px);
  border-radius: 14px;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  background: var(--app-surface-2, rgba(255, 255, 255, 0.04));
}
.bubble-row.user .bubble {
  background: rgba(96, 165, 250, 0.12);
  border-color: rgba(96, 165, 250, 0.35);
  border-top-right-radius: 4px;
}
.bubble-row.assistant .bubble,
.bubble-row.system .bubble {
  border-top-left-radius: 4px;
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.28);
}
.bubble-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.55;
  color: var(--app-text);
}
.tool-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.dispatch-cards {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}
.dispatch-card {
  border: 1px dashed rgba(245, 158, 11, 0.4);
  border-radius: 8px;
  padding: 8px;
  background: rgba(245, 158, 11, 0.06);
}
.dispatch-title {
  font-size: 12px;
  font-weight: 600;
}
.dispatch-id {
  margin: 4px 0;
  font-size: 11px;
  color: var(--app-text-secondary);
  word-break: break-all;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.progress-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--app-text-secondary);
}
.bubble-meta {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
  align-items: center;
  font-size: 11px;
  color: var(--app-text-secondary);
}

.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.composer-options {
  display: flex;
  align-items: center;
  gap: 8px;
}
.option-hint {
  font-size: 11px;
  color: var(--app-text-secondary);
}
.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.composer-right {
  display: flex;
  gap: 8px;
}
.cursor {
  display: inline-block;
  margin-left: 1px;
  animation: blink 1s step-end infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}

.assistant-shell.minimized .panel-body {
  display: none;
}
.assistant-shell.maximized {
  background: var(--app-surface, #111);
}
</style>

<style>
.assistant-drawer .el-drawer__body {
  padding: 0 !important;
  height: 100%;
  overflow: hidden;
}
</style>
