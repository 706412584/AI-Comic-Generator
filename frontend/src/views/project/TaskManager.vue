<template>
  <div v-if="tasks.length > 0" class="task-manager" :class="{ collapsed: isCollapsed }">
    <div class="task-header" @click="toggleCollapse">
      <span>后台任务 ({{ runningCount }})</span>
      <el-icon><component :is="isCollapsed ? 'ArrowUp' : 'ArrowDown'" /></el-icon>
    </div>
    <div v-show="!isCollapsed" class="task-list">
      <div v-for="task in tasks" :key="task.id" class="task-item" @click="openTerminal(task.id)">
        <div class="task-info">
          <div class="task-name-group">
            <span class="task-name" :title="task.description">{{ task.name || getTaskTypeName(task.type) }}</span>
            <span class="task-desc" :title="getTaskCardSummary(task)">{{ getTaskCardSummary(task) }}</span>
            <span class="task-result" v-if="getTaskResultSummary(task)" :title="getTaskResultSummary(task)">
              {{ getTaskResultSummary(task) }}
            </span>
            <span class="task-error" v-if="task.status === 'failed'" :title="task.message || getFailureAdvice(task).reason">
              建议：{{ getFailureAdvice(task).action }}
            </span>
          </div>
          <div class="status-group">
             <el-button 
               v-if="['pending', 'processing'].includes(task.status)" 
               link 
               size="small" 
               type="danger"
               @click.stop="cancelTask(task.id)" 
               title="取消任务"
             >
                <el-icon><CircleClose /></el-icon>
             </el-button>
             <el-button
               v-if="canRetry(task)"
               link
               size="small"
               type="primary"
               :loading="retryingTaskId === task.id"
               @click.stop="retryTask(task.id)"
               title="重试任务"
             >
                重试
             </el-button>
             <el-button link size="small" @click.stop="openTerminal(task.id)" title="查看日志">
                <el-icon><Monitor /></el-icon>
             </el-button>
             <span class="task-status" :class="task.status">{{ getTaskStatusText(task.status) }}</span>
          </div>
        </div>
        <el-progress :percentage="task.progress" :status="getTaskProgressStatus(task.status)" :stroke-width="6"></el-progress>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowUp, ArrowDown, Monitor, CircleClose } from '@element-plus/icons-vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const props = defineProps({
  tasks: {
    type: Array,
    required: true
  },
  isCollapsed: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:isCollapsed', 'open-terminal', 'task-retried'])

const retryingTaskId = ref('')
const retryableTaskTypes = new Set(['chapter_content_generation', 'chapter_storyboard', 'source_analysis'])

const runningCount = computed(() => {
  return props.tasks.filter(t => ['pending', 'processing'].includes(t.status)).length
})

const toggleCollapse = () => {
  emit('update:isCollapsed', !props.isCollapsed)
}

const openTerminal = (taskId) => {
    emit('open-terminal', taskId)
}

const cancelTask = async (taskId) => {
    try {
        await axios.post(`/api/v1/tasks/${taskId}/cancel`)
        ElMessage.warning('已请求取消任务')
    } catch (e) {
        console.error(e)
        ElMessage.error('取消任务失败')
    }
}

const canRetry = (task) => task?.status === 'failed' && retryableTaskTypes.has(task.type)

const retryTask = async (taskId) => {
    retryingTaskId.value = taskId
    try {
        const res = await axios.post(`/api/v1/tasks/${taskId}/retry`)
        ElMessage.success('已创建重试任务')
        emit('task-retried', res.data)
    } catch (e) {
        console.error(e)
        ElMessage.error(e?.response?.data?.detail || '重试任务失败')
    } finally {
        retryingTaskId.value = ''
    }
}

const getValue = (source, keys) => {
  if (!source || typeof source !== 'object') return undefined
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null && source[key] !== '') return source[key]
  }
  return undefined
}

const getTaskTypeName = (type) => {
  const map = {
    'project_initialization': '项目初始化',
    'source_analysis': '原文分析',
    'chapter_content_generation': '章节正文生成',
    'source_project_initialization': '原文项目初始化',
    'storyboard': '分镜生成',
    'chapter_storyboard': '章节分镜生成',
    'image_generation': '全量图片生成',
    'character_generation': '角色绘制'
  }
  return map[type] || type || '未知任务'
}

const getTaskResultSummary = (task) => {
  const result = task?.result
  if (!result || typeof result !== 'object' || Object.keys(result).length === 0) return ''
  const parts = []
  const chapters = getValue(result, ['chapters_created', 'chapters', 'chapter_count', 'processed_chapters'])
  const sourceChapters = getValue(result, ['source_chapters', 'source_chapter_count'])
  const storyboardItems = getValue(result, ['storyboard_items', 'items_count', 'panels', 'panel_count'])
  const images = getValue(result, ['generated_images', 'images', 'image_count', 'success_count'])
  if (chapters !== undefined) parts.push(`章节 ${chapters} 章`)
  if (sourceChapters !== undefined) parts.push(`原文章节 ${sourceChapters} 章`)
  if (storyboardItems !== undefined) parts.push(`分镜 ${storyboardItems} 条`)
  if (images !== undefined) parts.push(`图片 ${images} 张`)
  return parts.length ? `结果：${parts.join('，')}` : ''
}

const getTaskCardSummary = (task) => {
  const statusText = getTaskStatusText(task.status)
  const typeSummaryMap = {
    source_analysis: '分析原文，整理章节、角色和设定',
    source_project_initialization: '根据原文初始化项目结构',
    chapter_content_generation: '生成当前章节正文',
    chapter_storyboard: '把章节正文改写为漫画分镜',
    image_generation: '生成图片资源',
    storyboard: '生成项目分镜和角色设定'
  }
  if (task.status === 'completed') return `${statusText}：${getTaskResultSummary(task) || '已生成并保存结果'}`
  if (task.status === 'failed') return `${statusText}：${task.message || '任务执行失败'}`
  if (task.status === 'cancelled') return `${statusText}：任务已停止`
  return `${statusText}：${typeSummaryMap[task.type] || task.description || getTaskTypeName(task.type)}`
}

const getFailureAdvice = (task) => {
  const text = `${task?.message || ''} ${JSON.stringify(task?.result || {})}`.toLowerCase()
  if (/model|api key|api_key|provider|base_url|模型|配置|密钥|key/.test(text)) return { action: '检查模型配置后点击重试', reason: '模型配置可能缺失或不可用' }
  if (/timeout|timed out|超时|time out/.test(text)) return { action: '稍后重试，或减少本次生成内容量', reason: 'AI 服务响应超时' }
  if (/json|parse|解析|格式/.test(text)) return { action: '重试；若反复失败请缩短输入或明确格式要求', reason: '模型返回格式无法解析' }
  if (/cancel|cancelled|取消/.test(text) || task?.status === 'cancelled') return { action: '如仍需要结果，请重新发起任务', reason: '任务已取消' }
  return { action: canRetry(task) ? '点击重试；若仍失败再查看详情' : '查看详情并重新发起任务', reason: '未分类错误' }
}

const getTaskStatusText = (status) => {
  const map = {
    'pending': '等待中',
    'processing': '处理中',
    'completed': '已完成',
    'failed': '失败',
    'cancelled': '已取消'
  }
  return map[status] || status
}

const getTaskProgressStatus = (status) => {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  if (status === 'cancelled') return 'warning'
  return ''
}
</script>

<style scoped>
.task-manager {
    position: fixed;
    bottom: 20px;
    right: 20px;
    width: 320px;
    background: #1e1e1e;
    border: 1px solid #333;
    border-radius: 4px;
    padding: 0;
    z-index: 1000;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    transition: all 0.3s ease;
    overflow: hidden;
}
.task-manager.collapsed {
    width: 200px;
}
.task-header {
    font-weight: bold;
    padding: 10px 15px;
    background: #2b2b2b;
    border-bottom: 1px solid #333;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    user-select: none;
}
.task-header:hover {
    background: #333;
}
.task-list {
    max-height: 300px;
    overflow-y: auto;
    padding: 10px;
}
.task-item {
    margin-bottom: 15px;
    font-size: 0.9em;
    padding: 8px 6px 10px;
    border-bottom: 1px solid #2a2a2a;
    border-radius: 6px;
    cursor: pointer;
}

.task-item:hover {
    background: #252525;
}
.task-item:last-child {
    margin-bottom: 0;
    padding-bottom: 0;
    border-bottom: none;
}
.task-info {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 6px;
}
.task-name-group {
    display: flex;
    flex-direction: column;
    max-width: 60%;
}
.status-group {
    display: flex;
    align-items: center;
    gap: 8px;
}
.task-name {
    font-weight: bold;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.task-desc,
.task-result {
    font-size: 0.8em;
    color: #888;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.task-result {
    color: #67C23A;
    margin-top: 2px;
}
.task-error {
    font-size: 0.8em;
    color: #F56C6C;
    margin-top: 2px;
    word-break: break-all;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.task-status.pending { color: #909399; }
.task-status.processing { color: #409EFF; }
.task-status.completed { color: #67C23A; }
.task-status.failed { color: #F56C6C; }
.task-status.cancelled { color: #E6A23C; }
</style>