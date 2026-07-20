<template>
  <el-dialog
    v-model="visible"
    title="任务详情"
    width="920px"
    :before-close="handleClose"
    class="terminal-dialog"
    destroy-on-close
  >
    <div v-if="task" class="task-detail">
      <div class="detail-header">
        <div>
          <h3>{{ task.name || getTaskTypeName(task.type) }}</h3>
          <p v-if="task.description" class="task-description">{{ task.description }}</p>
        </div>
        <div class="detail-actions">
          <el-button
            v-if="canRetry(task)"
            type="primary"
            size="small"
            :loading="retrying"
            @click="retryCurrentTask"
          >
            重试
          </el-button>
          <el-tag :type="statusTagType(task.status)">{{ getTaskStatusText(task.status) }}</el-tag>
        </div>
      </div>

      <el-progress :percentage="task.progress || 0" :status="progressStatus(task.status)" :stroke-width="8" />

      <div v-if="streamPreview" class="stream-block">
        <div class="section-title">
          实时生成内容
          <span v-if="isRunning" class="stream-hint">（已生成 {{ streamChars }} 字，流式更新中...）</span>
        </div>
        <div class="stream-window" ref="streamRef">{{ streamPreview }}<span v-if="isRunning" class="cursor">_</span></div>
      </div>

      <div class="detail-grid">
        <div class="detail-card">
          <span class="detail-label">任务 ID</span>
          <span class="detail-value mono">{{ task.id }}</span>
        </div>
        <div class="detail-card">
          <span class="detail-label">任务类型</span>
          <span class="detail-value">{{ getTaskTypeName(task.type) }}</span>
        </div>
        <div class="detail-card">
          <span class="detail-label">创建时间</span>
          <span class="detail-value">{{ formatDateTime(task.created_at) }}</span>
        </div>
        <div class="detail-card">
          <span class="detail-label">更新时间</span>
          <span class="detail-value">{{ formatDateTime(task.updated_at) }}</span>
        </div>
      </div>

      <div class="summary-block">
        <div class="section-title">执行摘要</div>
        <el-card class="summary-card" shadow="never">
          <p class="summary-main">{{ taskSummary.main }}</p>
          <ul v-if="taskSummary.details.length" class="summary-list">
            <li v-for="item in taskSummary.details" :key="item">{{ item }}</li>
          </ul>
        </el-card>
      </div>

      <el-alert
        v-if="task.message"
        :title="task.message"
        :type="task.status === 'failed' ? 'error' : 'info'"
        :closable="false"
        show-icon
      />

      <el-alert
        v-if="task.status === 'failed'"
        type="warning"
        :closable="false"
        show-icon
        class="suggestion-alert"
      >
        <template #title>可能原因 / 建议操作</template>
        <div class="suggestion-content">
          <div>可能原因：{{ failureAdvice.reason }}</div>
          <div>建议操作：{{ failureAdvice.action }}</div>
          <el-button
            v-if="canRetry(task)"
            type="primary"
            size="small"
            :loading="retrying"
            @click="retryCurrentTask"
          >
            重试任务
          </el-button>
        </div>
      </el-alert>

      <el-collapse v-if="hasResult" class="raw-collapse">
        <el-collapse-item title="技术详情 / 原始数据" name="task-result">
          <pre class="result-json">{{ formattedResult }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>

    <div class="section-title">Agent 运行详情</div>
    <div class="agent-runs-block">
      <el-skeleton v-if="agentRunsLoading && agentRuns.length === 0" :rows="4" animated />
      <el-alert
        v-else-if="agentRunsError"
        :title="agentRunsError"
        type="error"
        :closable="false"
        show-icon
      />
      <el-empty v-else-if="agentRuns.length === 0" description="暂无 Agent 运行记录" :image-size="72" />
      <div v-else class="agent-run-list">
        <el-card v-for="run in agentRuns" :key="run.id" class="agent-run-card" shadow="never">
          <div class="agent-run-header">
            <div>
              <div class="agent-title">
                {{ run.agent_name || '未知 Agent' }}
                <span v-if="run.agent_version" class="agent-version">v{{ run.agent_version }}</span>
              </div>
              <div class="agent-subtitle mono">{{ run.id }}</div>
            </div>
            <el-tag :type="statusTagType(run.status)">{{ getTaskStatusText(run.status) }}</el-tag>
          </div>

          <div class="agent-summary">
            <div class="agent-step-row">
              <span class="detail-label">当前阶段</span>
              <span class="detail-value">{{ getAgentStepName(run.current_step) }}</span>
              <span class="step-count mono">{{ formatStepCount(run) }}</span>
            </div>
            <div class="agent-human-summary">{{ getAgentRunSummary(run) }}</div>
          </div>
          <el-progress
            :percentage="agentRunProgress(run)"
            :status="progressStatus(run.status)"
            :stroke-width="8"
          />

          <div class="agent-time-grid">
            <div>
              <span class="detail-label">创建时间</span>
              <span class="detail-value">{{ formatDateTime(run.created_at) }}</span>
            </div>
            <div>
              <span class="detail-label">开始时间</span>
              <span class="detail-value">{{ formatDateTime(run.started_at) }}</span>
            </div>
            <div>
              <span class="detail-label">完成时间</span>
              <span class="detail-value">{{ formatDateTime(run.finished_at) }}</span>
            </div>
          </div>

          <el-collapse class="payload-collapse">
            <el-collapse-item v-if="hasAnyPayload(run)" title="技术详情 / 原始数据" name="raw">
              <div v-if="hasPayload(run.input_payload)" class="payload-section">
                <div class="payload-title">输入 Payload</div>
                <pre class="payload-json">{{ formatPayload(run.input_payload) }}</pre>
              </div>
              <div v-if="hasPayload(run.state_payload)" class="payload-section">
                <div class="payload-title">状态 Payload</div>
                <pre class="payload-json">{{ formatPayload(run.state_payload) }}</pre>
              </div>
              <div v-if="hasPayload(run.result_payload)" class="payload-section">
                <div class="payload-title">结果 Payload</div>
                <pre class="payload-json">{{ formatPayload(run.result_payload) }}</pre>
              </div>
              <div v-if="hasPayload(run.error_payload)" class="payload-section">
                <div class="payload-title">错误 Payload</div>
                <pre class="payload-json error-payload">{{ formatPayload(run.error_payload) }}</pre>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </div>
    </div>

    <div class="section-title">执行日志</div>
    <div class="terminal-window" ref="terminalRef">
      <div v-if="logs.length === 0" class="empty-logs">
        暂无日志。
      </div>
      <div v-for="(log, index) in logs" :key="index" class="log-line">
        {{ log }}
      </div>
      <div v-if="isRunning" class="loading-indicator">
        <span class="cursor">_</span>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch, onUnmounted, nextTick } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  taskId: String
})

const emit = defineEmits(['update:visible'])

const visible = ref(props.visible)
const task = ref(null)
const currentTaskId = ref('')
const logs = ref([])
const isRunning = ref(false)
const terminalRef = ref(null)
const agentRuns = ref([])
const agentRunsLoading = ref(false)
const agentRunsError = ref('')
const retrying = ref(false)
const retryableTaskTypes = new Set([
  'chapter_content_generation',
  'chapter_storyboard',
  'source_analysis',
  'project_initialization',
  'source_project_initialization',
  'storyboard',
  'image_generation',
  'character_generation'
])
let pollingInterval = null
let taskEventSource = null
let sseFallbackActive = false

const hasResult = computed(() => task.value?.result && Object.keys(task.value.result).length > 0)
const formattedResult = computed(() => hasResult.value ? JSON.stringify(task.value.result, null, 2) : '')

const streamRef = ref(null)
const streamPreview = computed(() => task.value?.result?.stream_preview || '')
const streamChars = computed(() => task.value?.result?.stream_chars || streamPreview.value.length)

watch(streamPreview, () => {
  nextTick(() => {
    if (streamRef.value) {
      streamRef.value.scrollTop = streamRef.value.scrollHeight
    }
  })
})

const taskSummary = computed(() => buildTaskSummary(task.value, agentRuns.value))
const failureAdvice = computed(() => getFailureAdvice(task.value))

const getValue = (source, keys) => {
  if (!source || typeof source !== 'object') return undefined
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null && source[key] !== '') return source[key]
  }
  return undefined
}

const plural = (count, unit) => `${count}${unit}`

const getResultText = (result) => {
  if (!result || typeof result !== 'object' || Object.keys(result).length === 0) return ''
  const parts = []
  const chapters = getValue(result, ['chapters_created', 'chapters', 'chapter_count', 'processed_chapters'])
  const sourceChapters = getValue(result, ['source_chapters', 'source_chapter_count'])
  const storyboardItems = getValue(result, ['storyboard_items', 'items_count', 'panels', 'panel_count'])
  const images = getValue(result, ['generated_images', 'images', 'image_count', 'success_count'])
  const blocks = getValue(result, ['blocks_found'])
  if (chapters !== undefined) parts.push(`章节 ${plural(chapters, '章')}`)
  if (sourceChapters !== undefined) parts.push(`原文章节 ${plural(sourceChapters, '章')}`)
  if (storyboardItems !== undefined) parts.push(`分镜 ${plural(storyboardItems, '条')}`)
  if (images !== undefined) parts.push(`图片 ${plural(images, '张')}`)
  if (blocks !== undefined) parts.push(`解析到 JSON 块 ${plural(blocks, '个')}`)
  return parts.join('，')
}

const getScopeText = (currentTask) => {
  if (!currentTask?.scope_type && !currentTask?.scope_id) return ''
  const scopeMap = { project: '项目', chapter: '章节', source: '原文', storyboard: '分镜' }
  return `${scopeMap[currentTask.scope_type] || currentTask.scope_type || '范围'} ${currentTask.scope_id || ''}`.trim()
}

const buildTaskSummary = (currentTask, runs = []) => {
  if (!currentTask) return { main: '暂无任务信息。', details: [] }
  const typeName = getTaskTypeName(currentTask.type)
  const statusText = getTaskStatusText(currentTask.status)
  const resultText = getResultText(currentTask.result)
  const scopeText = getScopeText(currentTask)
  const activeRun = runs.find(run => ['pending', 'processing'].includes(run.status)) || runs[0]
  const agentText = activeRun ? `Agent 阶段：${getAgentStepName(activeRun.current_step)}，${formatStepCount(activeRun)}。` : ''
  const typeSummaryMap = {
    source_analysis: '正在把导入的小说原文拆解为章节、角色、世界观和改编线索。',
    source_project_initialization: '正在根据原文资料初始化项目结构，准备章节、设定和后续改编上下文。',
    chapter_content_generation: '正在根据章节目标、原文上下文和项目设定生成章节正文。',
    chapter_storyboard: '正在把当前章节内容改写为漫画分镜，生成画面、动作、对白和角色信息。',
    image_generation: '正在根据角色或分镜提示词生成图片资源。',
    storyboard: '正在根据故事输入生成项目分镜和相关角色设定。'
  }
  const base = typeSummaryMap[currentTask.type] || `正在处理「${typeName}」任务。`
  const main = currentTask.status === 'completed'
    ? `${typeName}已完成${resultText ? `，${resultText}` : ''}。`
    : currentTask.status === 'failed'
      ? `${typeName}执行失败，详情见下方建议和技术详情。`
      : currentTask.status === 'cancelled'
        ? `${typeName}已取消，未继续执行。`
        : base
  const details = [
    `当前状态：${statusText}，进度 ${currentTask.progress || 0}%。`,
    scopeText ? `作用范围：${scopeText}。` : '',
    currentTask.message ? `最新消息：${currentTask.message}` : '',
    resultText && currentTask.status !== 'completed' ? `当前结果：${resultText}。` : '',
    agentText
  ].filter(Boolean)
  return { main, details }
}

const getTaskTypeName = (type) => {
  const map = {
    project_initialization: '项目初始化',
    source_analysis: '原文分析',
    chapter_content_generation: '章节正文生成',
    source_project_initialization: '原文项目初始化',
    storyboard: '分镜生成',
    chapter_storyboard: '章节分镜生成',
    image_generation: '全量图片生成',
    character_generation: '角色绘制'
  }
  return map[type] || type || '未知任务'
}

const getTaskStatusText = (status) => ({
  pending: '等待中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消'
}[status] || status || '未知')

const statusTagType = (status) => ({
  completed: 'success',
  failed: 'danger',
  cancelled: 'warning',
  processing: 'primary',
  pending: 'info'
}[status] || 'info')

const progressStatus = (status) => {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  if (status === 'cancelled') return 'warning'
  return ''
}

const formatDateTime = (value) => {
  if (!value) return '未知'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

const hasPayload = (payload) => {
  if (payload === null || payload === undefined) return false
  if (Array.isArray(payload)) return payload.length > 0
  if (typeof payload === 'object') return Object.keys(payload).length > 0
  return String(payload).length > 0
}

const hasAnyPayload = (run) => ['input_payload', 'state_payload', 'result_payload', 'error_payload'].some(key => hasPayload(run?.[key]))

const formatPayload = (payload) => {
  if (!hasPayload(payload)) return ''
  if (typeof payload === 'string') return payload
  return JSON.stringify(payload, null, 2)
}

const normalizeLogs = (rawLogs) => {
  if (!rawLogs) return []
  if (Array.isArray(rawLogs)) {
    return rawLogs.map(log => typeof log === 'string' ? log : JSON.stringify(log))
  }
  if (typeof rawLogs === 'string') {
    try {
      const parsed = JSON.parse(rawLogs)
      return normalizeLogs(parsed)
    } catch {
      return rawLogs ? [rawLogs] : []
    }
  }
  return [JSON.stringify(rawLogs)]
}

const scrollTerminalToBottom = () => {
  nextTick(() => {
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }
  })
}

const stepNameMap = {
  load_source: '读取原文',
  analyze_source: '分析原文',
  split_chapters: '拆分章节',
  extract_characters: '提取角色',
  extract_settings: '提取设定',
  build_outline: '整理大纲',
  initialize_project: '初始化项目',
  assemble_context: '组装上下文',
  generate_content: '生成正文',
  review_content: '检查正文',
  save_content: '保存正文',
  generate_storyboard: '生成分镜',
  save_storyboard: '保存分镜',
  generate_images: '生成图片',
  save_images: '保存图片'
}

const getAgentStepName = (step) => stepNameMap[step] || step || '未开始'

const getCompletedStepNames = (run) => {
  const completed = run?.result_payload?.completed_steps || run?.result_payload?.summary?.completed_steps
  if (Array.isArray(completed) && completed.length) return completed.map(getAgentStepName)
  const state = run?.state_payload
  if (state && typeof state === 'object') return Object.keys(state).map(getAgentStepName)
  return []
}

const getAgentRunSummary = (run) => {
  const completedNames = getCompletedStepNames(run)
  if (run.status === 'completed') {
    return completedNames.length ? `已完成：${completedNames.join('、')}。` : 'Agent 已完成全部步骤。'
  }
  if (run.status === 'failed') {
    const error = run.error_payload?.error ? `失败信息：${run.error_payload.error}` : '请展开技术详情查看错误。'
    return `Agent 在「${getAgentStepName(run.current_step)}」阶段失败。${error}`
  }
  if (run.status === 'cancelled') return `Agent 已在「${getAgentStepName(run.current_step)}」阶段停止。`
  if (completedNames.length) return `已完成：${completedNames.join('、')}；当前正在处理「${getAgentStepName(run.current_step)}」。`
  return `当前正在处理「${getAgentStepName(run.current_step)}」。`
}

const getFailureAdvice = (currentTask) => {
  const text = `${currentTask?.message || ''} ${JSON.stringify(currentTask?.result || {})}`.toLowerCase()
  if (/model|api key|api_key|provider|base_url|模型|配置|密钥|key/.test(text)) {
    return { reason: '模型配置、API Key、服务地址或可用模型可能缺失或不可用。', action: '请先检查模型配置；修正后可点击重试。' }
  }
  if (/timeout|timed out|超时|time out/.test(text)) {
    return { reason: 'AI 服务响应超时或网络连接不稳定。', action: '稍后重试，或减少本次生成内容量后再试。' }
  }
  if (/json|parse|解析|格式/.test(text)) {
    return { reason: '模型返回内容不是预期 JSON 格式，系统无法解析保存。', action: '可以直接重试；如果反复失败，请缩短输入或补充更明确的生成要求。' }
  }
  if (/cancel|cancelled|取消/.test(text) || currentTask?.status === 'cancelled') {
    return { reason: '任务被用户或系统取消。', action: '如仍需要结果，请重新发起任务。' }
  }
  return { reason: '执行过程中遇到未分类错误，可能与输入内容、模型响应或后端服务有关。', action: canRetry(currentTask) ? '建议先点击重试；若仍失败，请展开技术详情查看原始错误。' : '请展开技术详情查看原始错误，并重新发起任务。' }
}

const agentRunProgress = (run) => {
  if (run.status === 'completed') return 100
  const stepIndex = Number(run.step_index) || 0
  const totalSteps = Number(run.total_steps) || 0
  if (totalSteps <= 0) return 0
  return Math.min(100, Math.max(0, Math.round((stepIndex / totalSteps) * 100)))
}

const formatStepCount = (run) => {
  const stepIndex = run.step_index ?? 0
  const totalSteps = run.total_steps ?? 0
  return totalSteps ? `${stepIndex}/${totalSteps}` : `${stepIndex}/?`
}

const canRetry = (currentTask) => currentTask?.status === 'failed' && retryableTaskTypes.has(currentTask.type)

const retryCurrentTask = async () => {
  if (!task.value?.id) return
  retrying.value = true
  try {
    const res = await axios.post(`/api/v1/tasks/${task.value.id}/retry`)
    ElMessage.success('已创建重试任务')
    task.value = res.data
    currentTaskId.value = res.data.id
    logs.value = normalizeLogs(res.data.logs)
    agentRuns.value = []
    startTaskUpdates()
  } catch (e) {
    console.error('重试任务失败', e)
    ElMessage.error(e?.response?.data?.detail || '重试任务失败')
  } finally {
    retrying.value = false
  }
}

watch(() => props.visible, (val) => {
  visible.value = val
  currentTaskId.value = props.taskId || ''
  if (val && currentTaskId.value) {
    startTaskUpdates()
  } else {
    stopTaskUpdates()
  }
})

watch(() => props.taskId, (val) => {
  currentTaskId.value = val || ''
  if (visible.value && val) {
    logs.value = []
    agentRuns.value = []
    agentRunsError.value = ''
    startTaskUpdates()
  }
})

const handleClose = () => {
  emit('update:visible', false)
}

const fetchAgentRuns = async () => {
  if (!currentTaskId.value) return
  agentRunsLoading.value = true
  agentRunsError.value = ''
  try {
    const res = await axios.get(`/api/v1/tasks/${currentTaskId.value}/agent-runs`)
    agentRuns.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    console.error('获取 Agent 运行详情失败', e)
    agentRunsError.value = '获取 Agent 运行详情失败'
  } finally {
    agentRunsLoading.value = false
  }
}

const fetchLogs = async () => {
  if (!currentTaskId.value) return
  try {
    const [taskRes] = await Promise.all([
      axios.get(`/api/v1/tasks/${currentTaskId.value}`),
      fetchAgentRuns()
    ])
    task.value = taskRes.data
    logs.value = normalizeLogs(task.value.logs)
    isRunning.value = ['pending', 'processing'].includes(task.value.status)

    scrollTerminalToBottom()

    if (['completed', 'failed', 'cancelled'].includes(task.value.status)) {
      stopPolling()
    }
  } catch (e) {
    console.error("获取任务日志失败", e)
  }
}

const startPolling = () => {
  stopPolling()
  fetchLogs()
  pollingInterval = setInterval(fetchLogs, 1000)
}

const stopPolling = () => {
  if (pollingInterval) {
    clearInterval(pollingInterval)
    pollingInterval = null
  }
}

const closeTaskEventSource = () => {
  if (taskEventSource) {
    taskEventSource.close()
    taskEventSource = null
  }
}

const handleTaskStateEvent = (event) => {
  const data = JSON.parse(event.data)
  if (!data.task || data.task.id !== currentTaskId.value) return
  task.value = data.task
  logs.value = normalizeLogs(data.task.logs)
  isRunning.value = ['pending', 'processing'].includes(data.task.status)
  scrollTerminalToBottom()
}

const handleTaskLogEvent = (event) => {
  const data = JSON.parse(event.data)
  const newLogs = normalizeLogs(data.logs)
  if (newLogs.length) {
    logs.value = [...logs.value, ...newLogs]
    scrollTerminalToBottom()
  }
}

const handleTaskDoneEvent = async (event) => {
  const data = JSON.parse(event.data)
  if (data.task && data.task.id === currentTaskId.value) {
    task.value = data.task
    logs.value = normalizeLogs(data.task.logs)
  }
  isRunning.value = false
  closeTaskEventSource()
  await Promise.all([fetchLogs(), fetchAgentRuns()])
}

const startTaskEventStream = () => {
  closeTaskEventSource()
  if (!window.EventSource || !currentTaskId.value) return false

  const streamTaskId = currentTaskId.value
  const source = new EventSource(`/api/v1/tasks/${streamTaskId}/events`)
  taskEventSource = source

  source.addEventListener('task_state', handleTaskStateEvent)
  source.addEventListener('task_log', handleTaskLogEvent)
  source.addEventListener('done', handleTaskDoneEvent)
  source.addEventListener('error', () => {
    if (taskEventSource !== source || sseFallbackActive) return
    sseFallbackActive = true
    closeTaskEventSource()
    startPolling()
  })

  return true
}

const startTaskUpdates = () => {
  stopTaskUpdates()
  sseFallbackActive = false
  fetchLogs()
  fetchAgentRuns()
  if (startTaskEventStream()) return
  startPolling()
}

const stopTaskUpdates = () => {
  stopPolling()
  closeTaskEventSource()
}

onUnmounted(() => {
  stopTaskUpdates()
})
</script>

<style scoped>
.task-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 16px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.detail-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.detail-header h3 {
  margin: 0;
  color: #e5eaf3;
}

.task-description {
  margin: 6px 0 0;
  color: #a3a6ad;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.detail-card {
  border: 1px solid #333;
  background: #252525;
  border-radius: 6px;
  padding: 10px;
}

.detail-label {
  display: block;
  color: #909399;
  font-size: 12px;
  margin-bottom: 6px;
}

.detail-value {
  color: #ddd;
  word-break: break-all;
}

.mono,
.result-json,
.payload-json,
.terminal-window {
  font-family: 'Courier New', Courier, monospace;
}

.section-title {
  color: #e5eaf3;
  font-weight: 700;
  margin: 12px 0 8px;
}

.summary-card {
  border-color: #333;
  background: #252525;
}

.summary-main {
  margin: 0;
  color: #e5eaf3;
  line-height: 1.6;
}

.summary-list {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #cfd3dc;
  line-height: 1.6;
}

.suggestion-alert {
  align-items: flex-start;
}

.suggestion-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.raw-collapse {
  margin-top: 4px;
}

.result-json {
  margin: 0;
  padding: 12px;
  max-height: 220px;
  overflow: auto;
  border: 1px solid #333;
  border-radius: 6px;
  background: #1e1e1e;
  color: #dcdfe6;
  white-space: pre-wrap;
}

.agent-runs-block {
  margin-bottom: 16px;
}

.agent-run-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-run-card {
  border-color: #333;
  background: #252525;
}

.agent-run-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 12px;
}

.agent-title {
  color: #e5eaf3;
  font-weight: 700;
}

.agent-version {
  color: #909399;
  font-size: 12px;
  font-weight: 400;
  margin-left: 6px;
}

.agent-subtitle {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
  word-break: break-all;
}

.agent-step-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.agent-step-row .detail-label {
  margin-bottom: 0;
}

.step-count {
  color: #909399;
  margin-left: auto;
}

.agent-time-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.payload-collapse {
  margin-top: 12px;
}

.agent-summary {
  margin-bottom: 8px;
}

.agent-human-summary {
  color: #cfd3dc;
  line-height: 1.6;
  margin-bottom: 8px;
}

.payload-section + .payload-section {
  margin-top: 12px;
}

.payload-title {
  color: #a3a6ad;
  font-size: 12px;
  margin-bottom: 6px;
}

.payload-json {
  margin: 0;
  padding: 12px;
  max-height: 260px;
  overflow: auto;
  border: 1px solid #333;
  border-radius: 6px;
  background: #1e1e1e;
  color: #dcdfe6;
  white-space: pre-wrap;
}

.error-payload {
  color: #f56c6c;
}

.terminal-window {
  background-color: #1e1e1e;
  color: #00ff00;
  padding: 16px;
  height: 360px;
  overflow-y: auto;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.4;
}

.stream-hint {
  color: #909399;
  font-size: 12px;
  font-weight: 400;
}

.stream-window {
  background-color: #1e1e1e;
  color: #dcdfe6;
  padding: 12px;
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid #333;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-line {
  word-break: break-all;
  white-space: pre-wrap;
  margin-bottom: 4px;
}

.empty-logs {
  color: #666;
  font-style: italic;
}

.cursor {
  animation: blink 1s step-end infinite;
}

@media (max-width: 768px) {
  .detail-grid,
  .agent-time-grid {
    grid-template-columns: 1fr;
  }
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>