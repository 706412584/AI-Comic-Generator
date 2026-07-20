<template>
  <div class="project-view" v-loading="loading" element-loading-text="处理中..." element-loading-background="rgba(0, 0, 0, 0.8)">
    <ProjectHeader 
      :title="project.title" 
      @export="openExportDialog" 
    />

    <TaskManager 
      :tasks="activeTasks" 
      v-model:isCollapsed="isTaskManagerCollapsed" 
      @open-terminal="openTerminal"
      @task-retried="handleTaskRetried"
    />

    <el-tabs v-model="activeTab" class="workflow-tabs">
      <el-tab-pane label="1. 故事与配置" name="story">
        <StoryTab
          :key="`story-${projectId}`"
          :project="project"
          :project-id="projectId"
          :is-task-running="isTaskRunning"
          :task-completion-signal="taskCompletionSignal"
          @refresh-project="fetchProject"
          @task-started="pollActiveTasks"
        />
      </el-tab-pane>

      <el-tab-pane label="2. 设定中心" name="settings">
        <SettingTab :key="tabKey('settings')" :project-id="projectId" />
      </el-tab-pane>

      <el-tab-pane label="3. 章节创作" name="chapters">
        <ChapterTab
          :key="tabKey('chapters')"
          :project-id="projectId"
          :task-completion-signal="taskCompletionSignal"
          @task-started="pollActiveTasks"
        />
      </el-tab-pane>

      <el-tab-pane label="4. 人物关系" name="relationships">
        <RelationshipPanel
          :key="tabKey('relationships')"
          :project-id="projectId"
          :project="project"
        />
      </el-tab-pane>

      <el-tab-pane label="5. 当前进度" name="progress">
        <ProgressPanel
          :key="tabKey('progress')"
          :project-id="projectId"
          :project="project"
        />
      </el-tab-pane>

      <el-tab-pane label="6. 记忆库" name="memory">
        <MemoryPanel
          :key="tabKey('memory')"
          :project-id="projectId"
          :project="project"
        />
      </el-tab-pane>

      <el-tab-pane label="7. 角色工坊" name="characters">
        <CharacterTab
          :project="project"
          :project-id="projectId"
          :is-task-running="isTaskRunning"
          :image-version="imageVersion"
          @refresh-project="fetchProject"
          @task-started="pollActiveTasks"
          @open-merge-dialog="showMergeDialog = true"
          @open-history="openHistory"
        />
      </el-tab-pane>

      <el-tab-pane label="8. 分镜画布" name="comic">
        <StoryboardTab
          :project="project"
          :project-id="projectId"
          :is-task-running="isTaskRunning"
          :image-version="imageVersion"
          @refresh-project="fetchProject"
          @task-started="pollActiveTasks"
          @open-history="openHistory"
        />
      </el-tab-pane>
    </el-tabs>

    <MergeDialog 
      v-model:visible="showMergeDialog"
      :characters="project.characters"
      :project-id="projectId"
      @merged="fetchProject"
    />

    <ExportDialog 
      v-model:visible="showExportDialog"
      :project-id="projectId"
    />

    <HistoryDialog 
      v-model:visible="showHistoryDialog"
      :type="currentHistoryType"
      :entity-id="currentHistoryEntityId"
      :current-image-url="currentHistoryImageUrl"
      @image-selected="fetchProject"
    />

    <TerminalDialog
      v-model:visible="showTerminalDialog"
      :task-id="currentTerminalTaskId"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { ElNotification } from 'element-plus'

import ProjectHeader from './project/ProjectHeader.vue'
import StoryTab from './project/StoryTab.vue'
import SettingTab from './project/SettingTab.vue'
import ChapterTab from './project/ChapterTab.vue'
import RelationshipPanel from './project/RelationshipPanel.vue'
import ProgressPanel from './project/ProgressPanel.vue'
import MemoryPanel from './project/MemoryPanel.vue'
import CharacterTab from './project/CharacterTab.vue'
import StoryboardTab from './project/StoryboardTab.vue'
import TaskManager from './project/TaskManager.vue'
import HistoryDialog from './project/HistoryDialog.vue'
import MergeDialog from './project/MergeDialog.vue'
import ExportDialog from './project/ExportDialog.vue'
import TerminalDialog from './project/TerminalDialog.vue'

const route = useRoute()
const projectId = computed(() => route.params.id)

// Project State
const project = ref({
    title: '',
    theme: '',
    language: 'zh-CN',
    panel_count: undefined,
    aspect_ratio: '16:9',
    resolution: '2K',
    characters: [],
    storyboard_items: [],
    story_input: '',
    global_config: null
})
const loading = ref(false)
const activeTab = ref('story')
const imageVersion = ref(Date.now())

// 每个内容 tab 有独立的重挂载 key，只由「后台任务完成」驱动，与切换 tab 解耦，
// 因此普通切换 tab 不会重挂载、不会丢失未保存的编辑。
// 任务完成时：非当前 tab 立即刷新；当前正在浏览的 tab 记为 stale，待用户离开后再刷新，
// 避免打断正在进行的编辑。
const CONTENT_TABS = ['settings', 'chapters', 'relationships', 'progress', 'memory']
const tabKeys = reactive({ settings: 0, chapters: 0, relationships: 0, progress: 0, memory: 0 })
const staleTabs = reactive(new Set())

const tabKey = (name) => `${name}-${tabKeys[name]}`

const refreshContentTabs = () => {
    CONTENT_TABS.forEach((name) => {
        if (name === activeTab.value) {
            staleTabs.add(name)
        } else {
            tabKeys[name]++
        }
    })
}

watch(activeTab, (_newTab, oldTab) => {
    if (staleTabs.has(oldTab)) {
        staleTabs.delete(oldTab)
        tabKeys[oldTab]++
    }
})

// Task State
const activeTasks = ref([])
const isTaskManagerCollapsed = ref(true)
const taskPollingInterval = ref(null)
const taskStatusMap = ref(new Map())
const taskCompletionSignal = ref(null)
const RUNNING_TASK_STATUSES = new Set(['pending', 'processing'])
const FINISHED_TASK_STATUSES = new Set(['completed', 'failed'])
// 完成后会更新设定/章节/关系/记忆/进度数据的任务类型
const TABS_REFRESH_TASK_TYPES = new Set([
    'chapter_storyboard',
    'chapter_content_generation',
    'project_initialization',
    'source_project_initialization',
    'source_analysis'
])

// Dialog State
const showMergeDialog = ref(false)
const showExportDialog = ref(false)
const showHistoryDialog = ref(false)
const showTerminalDialog = ref(false)
const currentTerminalTaskId = ref('')

// History State
const currentHistoryType = ref('')
const currentHistoryEntityId = ref('')

const currentHistoryImageUrl = computed(() => {
    if (currentHistoryType.value === 'character') {
        const char = project.value.characters.find(c => c.id === currentHistoryEntityId.value)
        return char?.image_url
    } else {
        const item = project.value.storyboard_items.find(i => i.id === currentHistoryEntityId.value)
        return item?.image_url
    }
})

const isTaskRunning = computed(() => {
    return activeTasks.value.some(t => ['pending', 'processing'].includes(t.status))
})

// Fetch Data
const fetchProject = async () => {
    try {
        const res = await axios.get(`/api/v1/projects/${projectId.value}`)
        // Update fields individually to preserve references where possible, 
        // though replacing the whole object is cleaner if children watch correctly.
        // Our children watch deep or props change, so replacing is fine but might reset some local state if not careful.
        // Let's do a merge or simple assign.
        project.value = res.data
        // Ensure arrays are at least empty arrays
        if (!project.value.characters) project.value.characters = []
        if (!project.value.storyboard_items) project.value.storyboard_items = []
        // imageVersion.value = Date.now() // Disabled to prevent flickering. Backend uses unique filenames.
    } catch (error) {
        console.error('Fetch project error', error)
    } finally {
        loading.value = false
    }
}

// Task Polling
const pollActiveTasks = async () => {
    if (taskPollingInterval.value) clearInterval(taskPollingInterval.value)
    
    // Immediate check
    checkTasks()

    taskPollingInterval.value = setInterval(checkTasks, 2000)
}

// 处理中的任务需要周期性刷新项目以显示批量出图的中间结果，
// 但降低频率，避免每 2s 全量拉项目干扰正在编辑的内容。
const PROCESSING_REFRESH_INTERVAL_MS = 10000
let lastProcessingRefreshAt = 0

const checkTasks = async () => {
    try {
        const res = await axios.get(`/api/v1/tasks/project/${projectId.value}`)
        activeTasks.value = res.data.slice(0, 5) // Top 5

        const anyActive = res.data.some(t => RUNNING_TASK_STATUSES.has(t.status))
        if (anyActive) {
            const now = Date.now()
            if (res.data.some(t => t.status === 'processing') && now - lastProcessingRefreshAt >= PROCESSING_REFRESH_INTERVAL_MS) {
                lastProcessingRefreshAt = now
                fetchProject()
            }
        } else if (taskPollingInterval.value) {
            // 没有进行中的任务时停止轮询；新任务启动会通过 task-started 事件重新开启。
            clearInterval(taskPollingInterval.value)
            taskPollingInterval.value = null
        }
    } catch (e) {
        console.error("Polling error", e)
    }
}

const buildTaskCompletionSignal = (task) => ({
    id: task.id,
    type: task.type,
    status: task.status,
    scope_type: task.scope_type,
    scope_id: task.scope_id,
    result: task.result || {},
    updated_at: task.updated_at
})

// Watch tasks for completion/failure transitions. Keep an explicit status map because
// the API returns only the latest tasks and oldTasks can be empty after mount/remount.
watch(activeTasks, (newTasks) => {
    const previousStatuses = taskStatusMap.value
    const nextStatuses = new Map(previousStatuses)
    const finishedTransitions = []

    newTasks.forEach((task) => {
        const previousStatus = previousStatuses.get(task.id)
        if (RUNNING_TASK_STATUSES.has(previousStatus) && FINISHED_TASK_STATUSES.has(task.status)) {
            finishedTransitions.push(task)
        }
        nextStatuses.set(task.id, task.status)
    })

    taskStatusMap.value = nextStatuses

    finishedTransitions.forEach((task) => {
        taskCompletionSignal.value = buildTaskCompletionSignal(task)
        fetchProject()

        if (task.status === 'completed') {
            // 这些任务会写入设定/章节/关系/记忆/进度等数据，完成后需要刷新内容 tab
            if (TABS_REFRESH_TASK_TYPES.has(task.type)) {
                refreshContentTabs()
            }
            ElNotification({ title: '任务完成', message: '后台任务已完成，相关内容已刷新', type: 'success' })
        } else if (task.status === 'failed') {
            ElNotification({ title: '任务失败', message: task.message || '后台任务执行失败，请查看任务日志', type: 'error' })
        }
    })
}, { deep: true })

// Actions
const openExportDialog = () => {
    if (!project.value.characters.length && !project.value.storyboard_items.some(i => i.image_url)) {
        ElNotification({ title: '提示', message: '暂无可导出的图片内容', type: 'warning' })
        return
    }
    showExportDialog.value = true
}

const openHistory = (type, id) => {
    currentHistoryType.value = type
    currentHistoryEntityId.value = id
    showHistoryDialog.value = true
}

const openTerminal = (taskId) => {
    currentTerminalTaskId.value = taskId
    showTerminalDialog.value = true
}

const handleTaskRetried = (task) => {
    checkTasks()
    if (task?.id) {
        currentTerminalTaskId.value = task.id
    }
}

// 同一组件实例在 /project/A -> /project/B 时会被复用，必须监听路由参数重置全部状态
watch(projectId, (newId, oldId) => {
    if (!newId || newId === oldId) return
    activeTasks.value = []
    taskStatusMap.value = new Map()
    taskCompletionSignal.value = null
    staleTabs.clear()
    CONTENT_TABS.forEach((name) => { tabKeys[name]++ })
    loading.value = true
    fetchProject()
    pollActiveTasks()
})

// Lifecycle
onMounted(() => {
    loading.value = true
    fetchProject()
    pollActiveTasks()
})

onUnmounted(() => {
    if (taskPollingInterval.value) clearInterval(taskPollingInterval.value)
})
</script>

<style scoped>
.project-view {
    padding: 20px;
    height: 100vh;
    display: flex;
    flex-direction: column;
}
</style>