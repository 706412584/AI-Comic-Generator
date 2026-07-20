<template>
  <div class="storyboard-tab">
    <div class="comic-actions mb-4">
        <el-tooltip :disabled="hasCharacters" content="请先在角色工坊生成角色图片" placement="top">
          <div style="display: inline-block;">
            <el-popconfirm
                title="这将重新生成所有分镜图片并覆盖现有图片，是否继续？"
                confirm-button-text="确认覆盖"
                cancel-button-text="取消"
                @confirm="generateAllImages"
            >
              <template #reference>
                <el-button type="primary" size="large" :disabled="!hasCharacters || isTaskRunning">
                  生成全部分镜（覆盖）
                </el-button>
              </template>
            </el-popconfirm>
          </div>
        </el-tooltip>
      <div class="info-group">
        <span class="tip-text ml-2">将按分镜顺序生成，后续分镜会参考前序图片内容。</span>
        <span v-if="!hasCharacters" class="warning-text ml-2"><el-icon><Warning /></el-icon> 请先生成角色！</span>
      </div>
    </div>
    
    <el-card class="filter-card mb-4" shadow="never">
      <el-form inline>
        <el-form-item label="章节筛选">
          <el-select v-model="selectedChapterFilter" class="chapter-filter">
            <el-option label="全部分镜" value="all" />
            <el-option label="未分章" value="unassigned" />
            <el-option
              v-for="chapter in sortedChapters"
              :key="chapter.id"
              :label="`第 ${chapter.sequence} 章：${chapter.title}`"
              :value="String(chapter.id)"
            />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <div v-for="item in filteredStoryboard" :key="item.id" class="comic-row">
      <el-card class="panel-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <div>
              <span class="panel-title">分镜 {{ item.sequence }}</span>
              <el-tag size="small" class="ml-2">{{ getChapterLabel(item.chapter_id) }}</el-tag>
            </div>
            <div class="header-actions">
              <el-button size="small" type="primary" link @click="openJsonEditor(item)">编辑 JSON</el-button>
              <el-tooltip :disabled="hasCharacters" content="请先在角色工坊生成角色图片" placement="top">
                <el-button size="small" type="primary" plain @click="generatePanel(item.id)" :disabled="!hasCharacters">重新生成</el-button>
              </el-tooltip>
            </div>
          </div>
        </template>
        <el-row :gutter="24">
          <!-- Left: 分镜 Details -->
          <el-col :xs="24" :sm="10" :md="8" :lg="8">
            <div class="panel-details">
              <!-- Scene Info -->
              <div class="detail-group" v-if="item.data.scene">
                <label>场景：</label>
                <div class="detail-content">{{ item.data.scene }}</div>
              </div>

              <!-- Action Info -->
              <div class="detail-group" v-if="item.data.action">
                <label>动作：</label>
                <div class="detail-content">{{ item.data.action }}</div>
              </div>

              <!-- Dialogue Info -->
              <div class="detail-group" v-if="item.data.dialogue">
                <label>对白：</label>
                <div class="detail-content">{{ item.data.dialogue }}</div>
              </div>

              <!-- Prompt (Existing) -->
              <div class="detail-group mt-3">
                <label>完整提示词：</label>
                <div class="detail-content prompt-text">
                  {{ item.data.prompt || '未设置提示词' }}
                </div>
              </div>
              
              <div class="detail-group mt-3" v-if="item.data.negative_prompt">
                <label>负面提示词：</label>
                <div class="detail-content sm-text text-gray">
                  {{ item.data.negative_prompt }}
                </div>
              </div>

              <div class="detail-group mt-3">
                <label>出场角色：</label>
                <div class="detail-content">
                  <div v-if="getPanelCharacters(item.id).length" class="tags-wrapper">
                    <el-tag v-for="name in getPanelCharacters(item.id)" :key="name" size="small" effect="dark">{{ name }}</el-tag>
                  </div>
                  <span v-else class="text-gray sm-text">未指定角色</span>
                </div>
              </div>
            </div>
          </el-col>
          
          <!-- Right: Image Preview -->
          <el-col :xs="24" :sm="14" :md="16" :lg="16">
            <div class="image-area">
              <div class="image-wrapper">
                <el-image 
                  v-if="item.image_url" 
                  :src="`${item.image_url}?v=${imageVersion}`" 
                  fit="contain" 
                  class="comic-preview"
                  :preview-src-list="[`${item.image_url}?v=${imageVersion}`]"
                >
                  <template #error>
                    <div class="image-slot">
                      <el-icon><icon-picture /></el-icon>
                    </div>
                  </template>
                </el-image>
                <div v-else class="no-image">
                  <span>尚未生成图片</span>
                </div>
              </div>
              
              <div v-if="item.image_url" class="image-actions mt-2">
                <a :href="item.image_url" :download="`panel_${item.sequence}.png`" target="_blank" class="mr-2">
                  <el-button size="small" type="info" plain>下载</el-button>
                </a>
                <el-button size="small" @click="emit('open-history', 'panel', item.id)">历史</el-button>
              </div>
            </div>
          </el-col>
        </el-row>
      </el-card>
    </div>

    <JsonEditorDialog 
      v-model:visible="showJsonEditor" 
      :content="currentEditorContent" 
      :title="`编辑分镜 ${currentEditingItem?.sequence || ''}`"
      @save="handleJsonSave"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Warning, Picture as IconPicture } from '@element-plus/icons-vue'
import JsonEditorDialog from './JsonEditorDialog.vue'

const props = defineProps({
  project: Object,
  projectId: [String, Number],
  isTaskRunning: Boolean,
  imageVersion: Number
})

const emit = defineEmits(['task-started', 'refresh-project', 'open-history'])

const showJsonEditor = ref(false)
const currentEditingItem = ref(null)
const currentEditorContent = ref('')
const selectedChapterFilter = ref('all')

const sortedChapters = computed(() => {
  if (!props.project.chapters) return []
  return [...props.project.chapters].sort((a, b) => a.sequence - b.sequence)
})

const sortedStoryboard = computed(() => {
  if (!props.project.storyboard_items) return []
  // data 可能为 null（生成中断/旧数据），统一兜底为空对象，避免模板访问 item.data.xxx 抛错白屏
  return props.project.storyboard_items
    .map(item => (item.data ? item : { ...item, data: {} }))
    .sort((a, b) => a.sequence - b.sequence)
})

const filteredStoryboard = computed(() => {
  if (selectedChapterFilter.value === 'all') return sortedStoryboard.value
  if (selectedChapterFilter.value === 'unassigned') {
    return sortedStoryboard.value.filter(item => !item.chapter_id)
  }
  return sortedStoryboard.value.filter(item => String(item.chapter_id) === selectedChapterFilter.value)
})

const hasCharacters = computed(() => {
  if (!props.project.characters) return false
  return props.project.characters.some(c => c.image_url)
})

const getChapterLabel = (chapterId) => {
  if (!chapterId) return '未分章'
  const chapter = props.project.chapters?.find(item => item.id === chapterId)
  return chapter ? `第 ${chapter.sequence} 章` : '未知章节'
}

const getPanelCharacters = (itemId) => {
  const item = props.project.storyboard_items?.find(i => i.id === itemId)
  if (!item || !item.data?.characters) return []
  
  let chars = item.data.characters
  if (typeof chars === 'string') return [chars]
  if (Array.isArray(chars)) {
    return chars.map(c => typeof c === 'string' ? c : c.name)
  }
  return []
}

const openJsonEditor = (item) => {
  currentEditingItem.value = item
  currentEditorContent.value = JSON.stringify(item.data || {}, null, 2)
  showJsonEditor.value = true
}

const handleJsonSave = async (newContent) => {
  if (!currentEditingItem.value) return
  try {
    const data = JSON.parse(newContent)
    await axios.put(`/api/v1/projects/${props.projectId}/storyboard/${currentEditingItem.value.id}`, data)
    ElMessage.success('分镜内容已保存')
    emit('refresh-project')
  } catch (e) {
    ElMessage.error('JSON 格式错误或保存失败：' + e.message)
  }
}

const generateAllImages = async () => {
  try {
    await axios.post(`/api/v1/generate/all-images/${props.projectId}`)
    emit('task-started')
    ElMessage.info('全量图片生成任务已在后台启动...')
  } catch (error) {
    ElMessage.error('启动任务失败：' + (error.response?.data?.detail || error.message))
  }
}

const generatePanel = async (itemId) => {
  try {
    await axios.post(`/api/v1/generate/panel/${itemId}`)
    emit('task-started')
    ElMessage.info('分镜绘制任务已在后台启动...')
  } catch (error) {
    console.error(error)
    ElMessage.error('启动任务失败：' + (error.response?.data?.detail || error.message))
  }
}
</script>

<style scoped>
.storyboard-tab {
  padding-bottom: 40px;
}
.filter-card {
    border: 1px solid #333;
    background-color: #1e1e1e;
}
.chapter-filter {
    width: 260px;
}
.comic-actions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
}
.info-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
}
.comic-row {
    margin-bottom: 24px;
}
.panel-card {
    border: 1px solid #333;
    background-color: #1e1e1e;
}
.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.panel-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: #409EFF;
}
.header-actions {
    display: flex;
    gap: 10px;
}
.panel-details {
    padding-right: 16px;
}
.detail-group {
    margin-bottom: 12px;
}
.detail-group label {
    display: block;
    color: #909399;
    font-size: 0.9rem;
    margin-bottom: 4px;
    font-weight: 500;
}
.detail-content {
    color: #E5EAF3;
    line-height: 1.5;
}
.prompt-text {
    background: #252525;
    padding: 10px;
    border-radius: 4px;
    font-size: 0.95rem;
    max-height: 200px;
    overflow-y: auto;
}
.tags-wrapper {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
.image-area {
    display: flex;
    flex-direction: column;
    align-items: center;
}
.image-wrapper {
    width: 100%;
    /* Flexible height */
    min-height: 300px;
    display: flex;
    justify-content: center;
    background: #1a1a1a;
    border-radius: 4px;
    padding: 10px;
}
.comic-preview {
    width: 100%;
    height: auto;
    display: block;
}
.no-image {
    width: 100%;
    height: 300px;
    display: flex;
    justify-content: center;
    align-items: center;
    background: #2a2a2a;
    color: #666;
    border-radius: 4px;
}
.image-actions {
    display: flex;
    justify-content: center;
    width: 100%;
}
.tip-text { color: #888; font-size: 0.9em; }
.warning-text { color: #E6A23C; font-size: 0.9em; display: inline-flex; align-items: center; gap: 4px; }
.text-gray { color: #888; }
.sm-text { font-size: 0.85em; }
.mt-2 { margin-top: 10px; }
.mt-3 { margin-top: 16px; }
.mb-4 { margin-bottom: 24px; }
.ml-2 { margin-left: 10px; }
.mr-2 { margin-right: 10px; }
</style>