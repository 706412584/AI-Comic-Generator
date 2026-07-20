<template>
  <div class="story-tab-content">
    <!-- Top Section: Settings -->
    <el-card class="box-card mb-4" shadow="never">
      <template #header>
        <div class="card-header">
          <span>项目配置</span>
          <el-button type="primary" link @click="openGlobalConfig">高级配置（JSON）</el-button>
        </div>
      </template>
      <el-form :model="project" label-width="120px" class="settings-form" :inline="true">
        <el-form-item label="主题">
          <el-input v-model="project.theme" placeholder="例如：赛博朋克" @change="saveSettings" class="w-200" />
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="project.language" placeholder="请选择" @change="saveSettings" class="w-200">
            <el-option label="简体中文" value="zh-CN" />
            <el-option label="英文" value="en-US" />
            <el-option label="日文" value="ja-JP" />
          </el-select>
        </el-form-item>
        <el-form-item label="分镜数">
          <el-input-number v-model="project.panel_count" :min="1" :max="100" @change="saveSettings" class="w-150" />
        </el-form-item>
        <el-form-item label="画幅比例">
          <el-select v-model="project.aspect_ratio" placeholder="请选择" @change="saveSettings" class="w-150">
            <el-option label="1:1" value="1:1" />
            <el-option label="2:3" value="2:3" />
            <el-option label="3:2" value="3:2" />
            <el-option label="3:4" value="3:4" />
            <el-option label="4:3" value="4:3" />
            <el-option label="4:5" value="4:5" />
            <el-option label="5:4" value="5:4" />
            <el-option label="9:16" value="9:16" />
            <el-option label="16:9" value="16:9" />
            <el-option label="21:9" value="21:9" />
          </el-select>
        </el-form-item>
        <el-form-item label="分辨率">
          <el-select v-model="project.resolution" placeholder="请选择" @change="saveSettings" class="w-150">
            <el-option label="1K" value="1K" />
            <el-option label="2K" value="2K" />
            <el-option label="4K" value="4K" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Main Section: 故事输入 -->
    <el-card class="box-card story-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>故事输入</span>
          <div class="upload-area">
            <input type="file" ref="fileInput" @change="handleFileUpload" accept=".txt" style="display: none" />
            <el-button size="small" @click="$refs.fileInput.click()">从文件导入（.txt）</el-button>
            <span v-if="fileName" class="file-name ml-2">{{ fileName }}</span>
          </div>
        </div>
      </template>
      
      <div class="quick-init-box mb-4">
        <div class="quick-init-title">一句话 AI 初始化</div>
        <div class="quick-init-desc">输入一个核心创意，AI 会自动生成项目设定、角色、服饰、关系、大纲、章节任务、初始进度和记忆。进度会显示在右下角后台任务里。</div>
        <div class="quick-init-actions">
          <el-input
            v-model="quickInitInput"
            placeholder="例如：赛博修仙世界，一个失忆少年和机械狐妖寻找天庭遗迹"
            clearable
            @keyup.enter="initializeProject"
          />
          <el-button type="success" :disabled="isTaskRunning || !quickInitInput" @click="initializeProject">
            一句话生成项目骨架
          </el-button>
        </div>
      </div>

      <el-input
        type="textarea"
        :rows="15"
        v-model="storyInput"
        placeholder="请输入故事创意、简介或完整文本..."
        @change="saveStoryInput"
        class="story-textarea"
        resize="none"
      />

      <div class="action-footer mt-4">
        <el-button size="large" type="primary" @click="generateStoryboard" :disabled="isTaskRunning || !storyInput">
          生成分镜配置
        </el-button>

        <el-popconfirm
          title="重新生成会覆盖现有分镜和角色设定，是否继续？"
          confirm-button-text="是"
          cancel-button-text="否"
          @confirm="generateStoryboard"
        >
          <template #reference>
            <el-button size="large" type="warning" plain :disabled="isTaskRunning || !storyInput">
              全部重新生成
            </el-button>
          </template>
        </el-popconfirm>

        <el-button size="large" @click="saveStoryInput">仅保存故事</el-button>
        <el-button size="large" type="success" plain @click="importSourceText" :disabled="!storyInput || importingSource">
          保存原文并切章
        </el-button>
        <el-button size="large" type="primary" plain @click="analyzeSource('continue')" :disabled="!sourceImports.length || isTaskRunning">
          继续分析原文
        </el-button>
        <el-button size="large" type="danger" plain @click="initializeFromSource" :disabled="!sourceImports.length || isTaskRunning">
          基于原文生成项目设定
        </el-button>
      </div>
    </el-card>

    <el-card class="box-card source-card mt-4" shadow="never">
      <template #header>
        <div class="card-header">
          <span>原文导入</span>
          <el-button size="small" @click="loadSourceData">刷新</el-button>
        </div>
      </template>

      <el-empty v-if="!sourceImports.length" description="尚未导入整本小说原文" />
      <div v-else>
        <div class="source-summary">
          <span>文件：{{ activeSourceImport.file_name }}</span>
          <span>总字数：{{ activeSourceImport.text_length }}</span>
          <span>识别章节：{{ activeSourceImport.chapter_count }}</span>
          <span>已分析：{{ activeSourceImport.analyzed_chapter_count || 0 }} / {{ activeSourceImport.chapter_count }}</span>
          <span>剩余：{{ activeSourceImport.unanalyzed_chapter_count || 0 }}</span>
          <span v-if="layeredSummaryCount">分层摘要：{{ layeredSummaryCount }} 个分组</span>
          <span>状态：{{ sourceStatusText(activeSourceImport.import_status) }}</span>
        </div>
        <el-progress
          class="source-analysis-progress"
          :percentage="sourceAnalysisPercent"
          :status="sourceProgressStatus"
          :stroke-width="8"
        />
        <div class="source-actions">
          <el-input v-model="sourceSearch" placeholder="搜索章节标题/原文/摘要" clearable @keyup.enter="loadSourceData" />
          <el-button @click="loadSourceData">搜索</el-button>
          <el-button type="primary" plain @click="analyzeSource('continue')" :disabled="!sourceImports.length || isTaskRunning || activeSourceImport.import_status === 'analyzed'">
            {{ activeSourceImport.import_status === 'analyzed' ? '原文已分析完成' : `继续分析剩余章节（${activeSourceImport.unanalyzed_chapter_count || 0}）` }}
          </el-button>
          <el-button type="warning" plain @click="analyzeSource('all')" :disabled="!sourceImports.length || isTaskRunning">全量分析</el-button>
          <el-button plain @click="showResplitDialog = true">重切设置</el-button>
        </div>
        <el-table :data="sourceChapters" size="small" class="source-table" max-height="360">
          <el-table-column prop="sequence" label="#" width="70" />
          <el-table-column prop="title" label="章节" min-width="220" show-overflow-tooltip />
          <el-table-column prop="raw_word_count" label="字数" width="100" />
          <el-table-column label="分析状态" width="130">
            <template #default="scope">
              <el-tooltip v-if="scope.row.analysis_error" :content="scope.row.analysis_error" placement="top">
                <el-tag :type="sourceChapterStatusType(scope.row.analysis_status)">{{ sourceChapterStatusText(scope.row.analysis_status) }}</el-tag>
              </el-tooltip>
              <el-tag v-else :type="sourceChapterStatusType(scope.row.analysis_status)">{{ sourceChapterStatusText(scope.row.analysis_status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="scope">
              <el-button link type="primary" size="small" @click="openSourceChapter(scope.row.id)">查看原文</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- Dialogs -->
    <el-dialog v-model="showResplitDialog" title="重切原文章节" width="720px">
      <el-alert title="留空使用自动切章。自定义正则可用第一个捕获组作为章节标题。确认重切会替换当前原文章节。" type="warning" :closable="false" class="mb-4" />
      <el-input v-model="splitPattern" type="textarea" :rows="4" placeholder="例如：^(第\\s*[0-9一二三四五六七八九十百千万零〇两]+\\s*章[^\\n]*)" />
      <div class="resplit-actions">
        <el-button @click="previewResplit">预览切章</el-button>
        <el-popconfirm title="确认重切？当前原文章节会被替换。" @confirm="confirmResplit">
          <template #reference>
            <el-button type="danger" :disabled="!resplitPreview">确认重切</el-button>
          </template>
        </el-popconfirm>
      </div>
      <div v-if="resplitPreview" class="resplit-preview">
        <div class="source-summary"><span>预览章节数：{{ resplitPreview.chapter_count }}</span><span>仅显示前 {{ resplitPreview.chapters.length }} 条</span></div>
        <el-table :data="resplitPreview.chapters" size="small" max-height="300">
          <el-table-column prop="sequence" label="#" width="70" />
          <el-table-column prop="title" label="章节" min-width="260" show-overflow-tooltip />
          <el-table-column prop="raw_word_count" label="字数" width="100" />
        </el-table>
      </div>
    </el-dialog>

    <el-dialog v-model="showSourceDialog" :title="currentSourceChapter?.title || '原文章节'" width="70%">
      <el-input
        type="textarea"
        :rows="22"
        :model-value="currentSourceChapter?.raw_text || ''"
        readonly
        resize="none"
        class="source-preview"
      />
    </el-dialog>

    <JsonEditorDialog
      v-model:visible="showGlobalConfig" 
      :content="globalConfigEditor" 
      title="全局配置"
      @save="handleGlobalConfigSave"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElNotification } from 'element-plus'
import JsonEditorDialog from './JsonEditorDialog.vue'

const props = defineProps({
  project: Object,
  projectId: [String, Number],
  isTaskRunning: Boolean,
  taskCompletionSignal: Object
})

const emit = defineEmits(['refresh-project', 'task-started'])

const storyInput = ref('')
const quickInitInput = ref('')
const fileName = ref('')
const fileInput = ref(null)
const globalConfigEditor = ref('')
const showGlobalConfig = ref(false)
const importingSource = ref(false)
const sourceImports = ref([])
const sourceChapters = ref([])
const currentSourceChapter = ref(null)
const showSourceDialog = ref(false)
const sourceSearch = ref('')
const splitPattern = ref('')
const resplitPreview = ref(null)
const showResplitDialog = ref(false)
const handledCompletionIds = new Set()

const activeSourceImport = computed(() => sourceImports.value[0] || {})
const layeredSummaryCount = computed(() => activeSourceImport.value?.summary_layers?.chunks?.length || 0)
const sourceAnalysisPercent = computed(() => {
  const total = activeSourceImport.value.chapter_count || 0
  if (!total) return 0
  return Math.min(100, Math.round(((activeSourceImport.value.analyzed_chapter_count || 0) / total) * 100))
})
const sourceProgressStatus = computed(() => {
  const status = activeSourceImport.value.import_status
  if (status === 'analyzed') return 'success'
  if (status === 'analysis_failed' || status === 'analyzed_with_errors') return 'exception'
  return ''
})
const sourceStatusText = (status) => ({
  imported: '已导入',
  partially_analyzed: '部分分析',
  analyzed: '已分析',
  analyzed_with_errors: '部分章节失败',
  analysis_failed: '分析失败'
}[status] || status || '未知')
const sourceChapterStatusText = (status) => ({ pending: '待分析', analyzed: '已分析', failed: '失败' }[status] || status || '待分析')
const sourceChapterStatusType = (status) => ({ analyzed: 'success', failed: 'danger', pending: 'info' }[status] || 'info')

// Initialize local state when project changes
watch(() => props.project, (newVal) => {
  if (newVal) {
    if (newVal.story_input && !storyInput.value) storyInput.value = newVal.story_input
    if (newVal.global_config) {
      globalConfigEditor.value = JSON.stringify(newVal.global_config.data, null, 2)
    }
  }
}, { immediate: true, deep: true })

watch(() => props.taskCompletionSignal, async (task) => {
  if (!task?.id || handledCompletionIds.has(task.id)) return
  if (task.type !== 'source_analysis') return
  if (!['completed', 'failed'].includes(task.status)) return

  handledCompletionIds.add(task.id)
  await loadSourceData()
}, { deep: true })

const saveSettings = async () => {
  try {
    await axios.put(`/api/v1/projects/${props.projectId}`, { 
      theme: props.project.theme,
      language: props.project.language,
      panel_count: props.project.panel_count,
      aspect_ratio: props.project.aspect_ratio,
      resolution: props.project.resolution
    })
    ElMessage.success('设置已保存')
  } catch (e) {
    ElMessage.error('保存设置失败')
  }
}

const saveStoryInput = async () => {
  try {
    await axios.put(`/api/v1/projects/${props.projectId}`, { story_input: storyInput.value })
    ElMessage.success('故事已保存')
  } catch (e) {
    console.error("保存故事输入失败", e)
  }
}

const decodeTextFile = async (file) => {
  const buffer = await file.arrayBuffer()
  const encodings = ['utf-8', 'gb18030', 'gbk']

  for (const encoding of encodings) {
    try {
      const decoder = new TextDecoder(encoding, { fatal: true })
      const text = decoder.decode(buffer)
      if (!text.includes('�')) return text
    } catch (e) {
      // 尝试下一种编码
    }
  }

  return new TextDecoder('utf-8').decode(buffer)
}

const handleFileUpload = async (event) => {
  const file = event.target.files[0]
  if (!file) return
  fileName.value = file.name

  try {
    storyInput.value = await decodeTextFile(file)
    saveStoryInput()
    ElMessage.success('文件读取成功')
  } catch (e) {
    console.error('读取文件失败', e)
    ElMessage.error('读取文件失败')
  } finally {
    event.target.value = ''
  }
}

const loadSourceData = async () => {
  try {
    const importsRes = await axios.get(`/api/v1/projects/${props.projectId}/source-imports`)
    sourceImports.value = importsRes.data
    if (sourceImports.value.length) {
      const chaptersRes = await axios.get(`/api/v1/projects/${props.projectId}/source-chapters`, {
        params: { source_import_id: sourceImports.value[0].id, limit: 500, q: sourceSearch.value || undefined }
      })
      sourceChapters.value = chaptersRes.data
    } else {
      sourceChapters.value = []
    }
  } catch (e) {
    console.error('加载原文导入数据失败', e)
  }
}

const importSourceText = async () => {
  if (!storyInput.value) return ElMessage.warning('请先导入或输入小说原文')
  importingSource.value = true
  try {
    await saveStoryInput()
    const res = await axios.post(`/api/v1/projects/${props.projectId}/source-imports`, {
      file_name: fileName.value || `${props.project?.title || '小说原文'}.txt`,
      raw_text: storyInput.value
    })
    await loadSourceData()
    ElNotification.success({
      title: '原文导入完成',
      message: `已识别 ${res.data.chapter_count} 章，共 ${res.data.text_length} 字`,
      duration: 6000
    })
  } catch (error) {
    const detail = error.response?.data?.detail || error.message
    ElNotification.error({ title: '原文导入失败', message: detail, duration: 8000 })
  } finally {
    importingSource.value = false
  }
}

const openSourceChapter = async (chapterId) => {
  try {
    const res = await axios.get(`/api/v1/projects/${props.projectId}/source-chapters/${chapterId}`)
    currentSourceChapter.value = res.data
    showSourceDialog.value = true
  } catch (e) {
    ElMessage.error('加载原文章节失败')
  }
}

const analyzeSource = async (mode = 'continue') => {
  try {
    await axios.post(`/api/v1/generate/source-analyze/${props.projectId}`, {
      mode,
      max_chapters: mode === 'all' ? null : 50
    })
    emit('task-started')
    ElMessage.info(mode === 'all' ? '全量原文分析任务已启动' : '原文续跑分析任务已启动')
  } catch (error) {
    ElNotification.error({ title: '启动原文分析失败', message: error.response?.data?.detail || error.message, duration: 8000 })
  }
}

const previewResplit = async () => {
  if (!activeSourceImport.value?.id) return
  try {
    const res = await axios.post(`/api/v1/projects/${props.projectId}/source-imports/${activeSourceImport.value.id}/resplit-preview`, {
      split_pattern: splitPattern.value || null
    })
    resplitPreview.value = res.data
  } catch (error) {
    ElNotification.error({ title: '预览切章失败', message: error.response?.data?.detail || error.message, duration: 8000 })
  }
}

const confirmResplit = async () => {
  if (!activeSourceImport.value?.id) return
  try {
    await axios.post(`/api/v1/projects/${props.projectId}/source-imports/${activeSourceImport.value.id}/resplit`, {
      split_pattern: splitPattern.value || null
    })
    showResplitDialog.value = false
    resplitPreview.value = null
    await loadSourceData()
    ElMessage.success('原文章节已重切')
  } catch (error) {
    ElNotification.error({ title: '重切失败', message: error.response?.data?.detail || error.message, duration: 8000 })
  }
}

const initializeFromSource = async () => {
  try {
    await axios.post(`/api/v1/generate/project-initialize-from-source/${props.projectId}`)
    emit('task-started')
    ElMessage.info('基于原文初始化任务已启动，请在右下角查看进度')
  } catch (error) {
    ElNotification.error({ title: '启动原文初始化失败', message: error.response?.data?.detail || error.message, duration: 8000 })
  }
}

const generateStoryboard = async () => {
  if (!storyInput.value) return ElMessage.warning('请输入故事内容')
  try {
    await saveStoryInput()
    await axios.post(`/api/v1/generate/storyboard/${props.projectId}`, {
      user_input: storyInput.value
    })
    emit('task-started')
    ElMessage.info('分镜生成任务已在后台启动...')
  } catch (error) {
    ElMessage.error('启动任务失败：' + (error.response?.data?.detail || error.message))
  }
}

const initializeProject = async () => {
  const prompt = quickInitInput.value.trim()
  if (!prompt) return ElMessage.warning('请输入一句话创意')

  try {
    storyInput.value = prompt
    await saveStoryInput()
    await axios.post(`/api/v1/generate/project-initialize/${props.projectId}`, {
      user_input: prompt
    })
    emit('task-started')
    ElMessage.info('AI 初始化任务已启动，请在右下角查看进度和日志')
  } catch (error) {
    const detail = error.response?.data?.detail || error.message
    ElNotification.error({
      title: '启动初始化失败',
      message: detail,
      duration: 8000,
      showClose: true
    })
  }
}

const openGlobalConfig = () => {
  // Ensure editor has latest
  if (props.project.global_config) {
    globalConfigEditor.value = JSON.stringify(props.project.global_config.data, null, 2)
  } else {
    globalConfigEditor.value = '{}'
  }
  showGlobalConfig.value = true
}

const handleGlobalConfigSave = async (newContent) => {
  try {
    const data = JSON.parse(newContent)
    await axios.put(`/api/v1/projects/${props.projectId}/global_config`, data)
    ElMessage.success('全局配置已同步')
    emit('refresh-project')
  } catch (e) {
    ElMessage.error('保存失败：' + e.message)
  }
}

onMounted(() => {
  loadSourceData()
})
</script>

<style scoped>
.story-tab-content {
  max-width: 1200px;
  margin: 0 auto;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.settings-form {
  /* padding: 10px 0; */
}
.w-200 { width: 200px; }
.w-150 { width: 150px; }

.quick-init-box {
  border: 1px solid #2f5f46;
  background: rgba(38, 120, 83, 0.12);
  border-radius: 8px;
  padding: 16px;
}
.quick-init-title {
  font-weight: 700;
  color: #67C23A;
  margin-bottom: 6px;
}
.quick-init-desc {
  color: #a8abb2;
  font-size: 0.9rem;
  line-height: 1.5;
  margin-bottom: 12px;
}
.quick-init-actions {
  display: flex;
  gap: 12px;
}
.quick-init-actions .el-input {
  flex: 1;
}

.source-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  color: #cfd3dc;
  margin-bottom: 12px;
}
.source-analysis-progress {
  margin-bottom: 12px;
}

.source-actions,
.resplit-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}
.source-actions .el-input {
  max-width: 320px;
}
.resplit-actions {
  margin-top: 12px;
}
.resplit-preview {
  margin-top: 12px;
}
.source-table {
  width: 100%;
}
.source-preview :deep(.el-textarea__inner) {
  font-family: inherit;
  line-height: 1.7;
}

.story-textarea :deep(.el-textarea__inner) {
  font-family: inherit;
  font-size: 1.05rem;
  line-height: 1.6;
  padding: 16px;
}
.upload-area { display: flex; align-items: center; }
.file-name { color: #888; font-size: 0.9em; }
.action-footer {
  display: flex;
  gap: 16px;
  justify-content: flex-start;
  border-top: 1px solid #333;
  padding-top: 20px;
}

.mb-4 { margin-bottom: 24px; }
.mt-4 { margin-top: 24px; }
.ml-2 { margin-left: 10px; }
</style>