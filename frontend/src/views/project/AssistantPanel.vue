<template>
  <el-drawer
    v-model="visible"
    title="创作助手"
    direction="rtl"
    size="420px"
    class="assistant-drawer"
    destroy-on-close
    @opened="onOpened"
  >
    <div class="assistant-panel">
      <div class="toolbar">
        <span class="hint">基于当前项目上下文的多轮对话</span>
        <el-button link type="danger" :disabled="sending || loading" @click="clearConversation">清空会话</el-button>
      </div>

      <div ref="listRef" class="message-list" v-loading="loading">
        <div v-if="!loading && !displayMessages.length" class="empty">
          <p>可以问我：设定是否自洽、角色弧线、分镜节奏、下一章怎么写…</p>
          <p class="empty-sub">耗时生成（初始化 / 批量出图等）请继续用页面上的按钮。</p>
        </div>

        <div
          v-for="item in displayMessages"
          :key="item.key"
          class="bubble-row"
          :class="item.role"
        >
          <div class="bubble">
            <div class="bubble-content">{{ item.content }}<span v-if="item.streaming" class="cursor">_</span></div>
            <div v-if="item.toolNames?.length" class="tool-tags">
              <el-tag
                v-for="name in item.toolNames"
                :key="name"
                size="small"
                effect="plain"
                type="warning"
              >
                {{ name }}
              </el-tag>
            </div>
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
            </div>
          </div>
        </div>
      </div>

      <div class="composer">
        <el-input
          v-model="draft"
          type="textarea"
          :rows="3"
          resize="none"
          maxlength="8000"
          show-word-limit
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          :disabled="sending"
          @keydown="onKeydown"
        />
        <div class="composer-actions">
          <el-button type="primary" :loading="sending" :disabled="!draft.trim()" @click="send">
            发送
          </el-button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  projectId: { type: String, required: true },
})

const emit = defineEmits(['update:modelValue', 'task-started', 'open-terminal', 'project-mutated'])

const WRITE_TOOL_PREFIXES = ['create_', 'update_']
const isWriteTool = (name) =>
  typeof name === 'string' && WRITE_TOOL_PREFIXES.some((p) => name.startsWith(p))
const isStartTool = (name) => typeof name === 'string' && name.startsWith('start_')

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const loading = ref(false)
const sending = ref(false)
const draft = ref('')
const messages = ref([])
const conversationId = ref(null)
const listRef = ref(null)
const activeTaskId = ref('')
const streamPreview = ref('')
const streamChars = ref(0)
let pollTimer = null

const extractToolNames = (payload) => {
  const calls = payload?.tool_calls || payload?.toolCalls || []
  if (!Array.isArray(calls)) return []
  return [...new Set(calls.map((c) => c?.name).filter(Boolean))]
}

const displayMessages = computed(() => {
  const rows = messages.value.map((item) => ({
    key: `m-${item.id}`,
    role: item.role,
    content: item.content || '',
    created_at: item.created_at,
    task_id: item.task_id,
    streaming: false,
    toolNames: extractToolNames(item.payload),
  }))

  const hasStreamingAssistant = rows.some(
    (row) => row.role === 'assistant' && row.task_id === activeTaskId.value && row.content
  )
  if (activeTaskId.value && streamPreview.value && !hasStreamingAssistant) {
    rows.push({
      key: `stream-${activeTaskId.value}`,
      role: 'assistant',
      content: streamPreview.value,
      created_at: null,
      task_id: activeTaskId.value,
      streaming: true,
      toolNames: activeToolNames.value,
    })
  } else if (activeTaskId.value && streamPreview.value) {
    const target = [...rows].reverse().find(
      (row) => row.role === 'assistant' && row.task_id === activeTaskId.value
    )
    if (target && (!target.content || target.content.length < streamPreview.value.length)) {
      target.content = streamPreview.value
      target.streaming = true
      target.toolNames = activeToolNames.value.length ? activeToolNames.value : target.toolNames
    }
  }
  return rows
})

const activeToolNames = ref([])

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

const stopPoll = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const fetchMessages = async () => {
  const res = await axios.get(`/api/v1/projects/${props.projectId}/assistant/messages`, {
    params: { limit: 100 },
  })
  messages.value = res.data || []
}

const loadConversation = async () => {
  loading.value = true
  try {
    const conv = await axios.get(`/api/v1/projects/${props.projectId}/assistant/conversation`)
    conversationId.value = conv.data.id
    await fetchMessages()
    await scrollToBottom()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '加载创作助手失败')
  } finally {
    loading.value = false
  }
}

const pollTask = async () => {
  if (!activeTaskId.value) return
  try {
    const res = await axios.get(`/api/v1/tasks/${activeTaskId.value}`)
    const task = res.data
    const result = task.result || {}
    if (result.stream_preview) {
      streamPreview.value = result.stream_preview
      streamChars.value = result.stream_chars || streamPreview.value.length
      await scrollToBottom()
    }
    if (Array.isArray(result.tool_calls)) {
      activeToolNames.value = [
        ...new Set(result.tool_calls.map((c) => c?.name).filter(Boolean)),
      ]
    }
    if (['completed', 'failed', 'cancelled'].includes(task.status)) {
      const toolCalls = Array.isArray(result.tool_calls) ? result.tool_calls : []
      const writeTools = [
        ...new Set(toolCalls.map((c) => c?.name).filter(isWriteTool)),
      ]
      const startTools = toolCalls.filter((c) => isStartTool(c?.name))
      const dispatchedTaskIds = [
        ...new Set(
          startTools
            .map((c) => c?.result?.task_id || c?.result?.taskId)
            .filter(Boolean)
        ),
      ]
      stopPoll()
      activeTaskId.value = ''
      streamPreview.value = ''
      streamChars.value = 0
      activeToolNames.value = []
      await fetchMessages()
      await scrollToBottom()
      if (task.status === 'failed') {
        ElMessage.error(task.message || '助手回复失败')
      } else if (task.status === 'completed') {
        if (writeTools.length) {
          emit('project-mutated', {
            task_id: task.id,
            tool_names: writeTools,
          })
        }
        // start_* 派发的后台任务：刷新右下角任务面板轮询
        if (startTools.length) {
          emit('task-started', dispatchedTaskIds[0] || task.id)
        }
      }
    }
  } catch (error) {
    console.error(error)
  }
}

const startPoll = (taskId) => {
  stopPoll()
  activeTaskId.value = taskId
  streamPreview.value = ''
  streamChars.value = 0
  activeToolNames.value = []
  pollTimer = setInterval(pollTask, 1000)
  pollTask()
}

const onOpened = () => {
  loadConversation()
}

const send = async () => {
  const content = draft.value.trim()
  if (!content || sending.value) return
  sending.value = true
  try {
    const res = await axios.post(`/api/v1/projects/${props.projectId}/assistant/messages`, {
      content,
    })
    draft.value = ''
    messages.value = [...messages.value, res.data.user_message]
    emit('task-started', res.data.task_id)
    startPoll(res.data.task_id)
    await scrollToBottom()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '发送失败')
  } finally {
    sending.value = false
  }
}

const onKeydown = (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

const clearConversation = async () => {
  try {
    await ElMessageBox.confirm('将归档当前会话并开启新对话，历史仍保留在归档中。', '清空会话', {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    stopPoll()
    activeTaskId.value = ''
    streamPreview.value = ''
    const res = await axios.post(`/api/v1/projects/${props.projectId}/assistant/conversation/clear`)
    conversationId.value = res.data.id
    messages.value = []
    ElMessage.success('已开启新会话')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '清空失败')
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) stopPoll()
  }
)

watch(
  () => props.projectId,
  () => {
    stopPoll()
    messages.value = []
    conversationId.value = null
    if (props.modelValue) loadConversation()
  }
)
</script>

<style scoped>
.assistant-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: 10px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.hint {
  color: var(--app-text-secondary);
  font-size: 12px;
}
.message-list {
  flex: 1;
  min-height: 240px;
  overflow-y: auto;
  padding: 8px 4px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
}
.empty {
  margin: auto;
  text-align: center;
  color: var(--app-text-secondary);
  padding: 24px 16px;
  font-size: 13px;
  line-height: 1.6;
}
.empty-sub {
  margin-top: 8px;
  font-size: 12px;
  opacity: 0.85;
}
.bubble-row {
  display: flex;
}
.bubble-row.user {
  justify-content: flex-end;
}
.bubble-row.assistant,
.bubble-row.system {
  justify-content: flex-start;
}
.bubble {
  max-width: 92%;
  border-radius: 12px;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  background: var(--app-surface-2);
}
.bubble-row.user .bubble {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.35);
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
.bubble-meta {
  margin-top: 6px;
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
  color: var(--app-text-secondary);
}
.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.composer-actions {
  display: flex;
  justify-content: flex-end;
}
.cursor {
  display: inline-block;
  margin-left: 1px;
  animation: blink 1s step-end infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}
</style>
