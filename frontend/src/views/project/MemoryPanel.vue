<template>
  <div class="memory-panel">
    <el-card shadow="never" class="panel-card mb-4">
      <template #header>
        <div class="card-header">
          <span>记忆筛选</span>
          <div class="header-actions">
            <el-button @click="resetFilters">重置筛选</el-button>
            <el-button type="primary" @click="openMemoryDialog()">新增记忆</el-button>
          </div>
        </div>
      </template>

      <el-form inline class="filter-form">
        <el-form-item label="记忆类型">
          <el-select v-model="filters.memory_type" clearable placeholder="全部类型" class="filter-select">
            <el-option v-for="item in memoryTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>

        <el-form-item label="关联章节">
          <el-select v-model="filters.chapter_id" clearable placeholder="全部章节" class="filter-select">
            <el-option
              v-for="chapter in chapterOptions"
              :key="chapter.id"
              :label="`第 ${chapter.sequence} 章：${chapter.title}`"
              :value="chapter.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="关联角色">
          <el-select v-model="filters.character_id" clearable placeholder="全部角色" class="filter-select">
            <el-option
              v-for="character in characterOptions"
              :key="character.id"
              :label="character.name"
              :value="character.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="启用状态">
          <el-select v-model="filters.is_active" placeholder="全部状态" class="filter-select">
            <el-option label="全部" value="all" />
            <el-option label="启用中" value="active" />
            <el-option label="已停用" value="inactive" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>记忆列表</span>
          <span class="section-subtext">共 {{ memories.length }} 条</span>
        </div>
      </template>

      <el-empty v-if="!memories.length && !loading" description="暂无记忆数据" />

      <div v-else v-loading="loading" class="memory-list">
        <el-card v-for="memory in memories" :key="memory.id" shadow="hover" class="memory-card">
          <template #header>
            <div class="card-header memory-card-header">
              <div class="memory-meta-group">
                <el-tag size="small">{{ scopeText(memory.scope) }}</el-tag>
                <el-tag size="small" type="success">{{ memoryTypeText(memory.memory_type) }}</el-tag>
                <el-tag size="small" type="warning">重要度 {{ memory.importance }}</el-tag>
                <el-tag v-if="memory.chapter_id" size="small" type="info">{{ chapterLabel(memory.chapter_id) }}</el-tag>
                <el-tag v-if="memory.character_id" size="small" type="info">{{ characterLabel(memory.character_id) }}</el-tag>
              </div>
              <div class="memory-actions">
                <span class="switch-label">启用</span>
                <el-switch
                  :model-value="memory.is_active"
                  @change="toggleMemoryActive(memory, $event)"
                />
                <el-button size="small" link type="primary" @click="openMemoryDialog(memory)">编辑</el-button>
                <el-popconfirm title="确定删除这条记忆吗？" @confirm="deleteMemory(memory.id)">
                  <template #reference>
                    <el-button size="small" link type="danger">删除</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </div>
          </template>

          <div class="memory-content">{{ memory.content }}</div>

          <div class="memory-footer">
            <div v-if="memory.tags?.length" class="tag-list">
              <el-tag v-for="tag in memory.tags" :key="tag" size="small" effect="dark">{{ tag }}</el-tag>
            </div>
            <span class="memory-status" :class="memory.is_active ? 'is-active' : 'is-inactive'">
              {{ memory.is_active ? '当前启用' : '当前停用' }}
            </span>
          </div>
        </el-card>
      </div>
    </el-card>

    <el-dialog v-model="showDialog" :title="editingMemory ? '编辑记忆' : '新增记忆'" width="720px">
      <el-form :model="memoryForm" label-width="100px">
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="作用范围">
              <el-select v-model="memoryForm.scope" class="w-full">
                <el-option v-for="item in scopeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="记忆类型">
              <el-select v-model="memoryForm.memory_type" class="w-full">
                <el-option v-for="item in memoryTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="关联章节">
              <el-select v-model="memoryForm.chapter_id" clearable placeholder="可选" class="w-full">
                <el-option
                  v-for="chapter in chapterOptions"
                  :key="chapter.id"
                  :label="`第 ${chapter.sequence} 章：${chapter.title}`"
                  :value="chapter.id"
                />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="关联角色">
              <el-select v-model="memoryForm.character_id" clearable placeholder="可选" class="w-full">
                <el-option
                  v-for="character in characterOptions"
                  :key="character.id"
                  :label="character.name"
                  :value="character.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="记忆内容">
          <el-input
            v-model="memoryForm.content"
            type="textarea"
            :rows="6"
            resize="vertical"
            placeholder="请输入需要保留的剧情、设定、人物信息或连续性约束"
          />
        </el-form-item>

        <el-form-item label="标签">
          <el-input v-model="tagsText" placeholder="多个标签用逗号分隔，例如：伏笔,主线,战斗" />
        </el-form-item>

        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="重要度">
              <el-input-number v-model="memoryForm.importance" :min="1" :max="5" class="w-full" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="启用状态">
              <el-switch v-model="memoryForm.is_active" active-text="启用" inactive-text="停用" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMemory">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const props = defineProps({
  projectId: [String, Number],
  project: {
    type: Object,
    default: () => ({})
  }
})

const scopeOptions = [
  { label: '项目级', value: 'project' },
  { label: '章节级', value: 'chapter' },
  { label: '角色级', value: 'character' }
]

const memoryTypeOptions = [
  { label: '事件', value: 'event' },
  { label: '人物关系', value: 'relationship' },
  { label: '伏笔', value: 'foreshadowing' },
  { label: '世界状态', value: 'world_state' },
  { label: '角色状态', value: 'character_state' },
  { label: '约束', value: 'constraint' }
]

const loading = ref(false)
const saving = ref(false)
const showDialog = ref(false)
const editingMemory = ref(null)
const memories = ref([])
const tagsText = ref('')

const filters = ref({
  memory_type: null,
  chapter_id: null,
  character_id: null,
  is_active: 'all'
})

const createDefaultForm = () => ({
  scope: 'project',
  memory_type: 'event',
  chapter_id: null,
  character_id: null,
  content: '',
  tags: [],
  importance: 3,
  is_active: true
})

const memoryForm = ref(createDefaultForm())

const chapterOptions = computed(() => {
  const chapters = props.project?.chapters || []
  return [...chapters].sort((a, b) => a.sequence - b.sequence)
})

const characterOptions = computed(() => {
  const characters = props.project?.characters || []
  return [...characters].sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
})

const scopeText = (value) => {
  return scopeOptions.find(item => item.value === value)?.label || value || '未设置'
}

const memoryTypeText = (value) => {
  return memoryTypeOptions.find(item => item.value === value)?.label || value || '未设置'
}

const chapterLabel = (chapterId) => {
  const chapter = chapterOptions.value.find(item => item.id === chapterId)
  return chapter ? `第 ${chapter.sequence} 章：${chapter.title}` : `章节 #${chapterId}`
}

const characterLabel = (characterId) => {
  const character = characterOptions.value.find(item => item.id === characterId)
  return character?.name || `角色 #${characterId}`
}

const loadMemories = async () => {
  loading.value = true
  try {
    const params = {}
    if (filters.value.memory_type) params.memory_type = filters.value.memory_type
    if (filters.value.chapter_id) params.chapter_id = filters.value.chapter_id
    if (filters.value.character_id) params.character_id = filters.value.character_id

    const response = await axios.get(`/api/v1/projects/${props.projectId}/memories`, { params })
    let data = response.data || []

    if (filters.value.is_active === 'active') {
      data = data.filter(item => item.is_active)
    } else if (filters.value.is_active === 'inactive') {
      data = data.filter(item => !item.is_active)
    }

    memories.value = data
  } catch (error) {
    ElMessage.error('加载记忆失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

const resetFilters = () => {
  filters.value = {
    memory_type: null,
    chapter_id: null,
    character_id: null,
    is_active: 'all'
  }
}

const openMemoryDialog = (memory = null) => {
  editingMemory.value = memory
  memoryForm.value = memory
    ? {
        scope: memory.scope || 'project',
        memory_type: memory.memory_type || 'event',
        chapter_id: memory.chapter_id ?? null,
        character_id: memory.character_id ?? null,
        content: memory.content || '',
        tags: memory.tags || [],
        importance: memory.importance ?? 3,
        is_active: memory.is_active ?? true
      }
    : createDefaultForm()
  tagsText.value = (memoryForm.value.tags || []).join(',')
  showDialog.value = true
}

const buildPayload = () => ({
  ...memoryForm.value,
  chapter_id: memoryForm.value.chapter_id || null,
  character_id: memoryForm.value.character_id || null,
  tags: tagsText.value.split(',').map(tag => tag.trim()).filter(Boolean)
})

const saveMemory = async () => {
  if (!memoryForm.value.content.trim()) return ElMessage.warning('请输入记忆内容')

  saving.value = true
  try {
    const payload = buildPayload()
    if (editingMemory.value) {
      await axios.put(`/api/v1/projects/${props.projectId}/memories/${editingMemory.value.id}`, payload)
    } else {
      await axios.post(`/api/v1/projects/${props.projectId}/memories`, payload)
    }
    ElMessage.success(editingMemory.value ? '记忆已更新' : '记忆已创建')
    showDialog.value = false
    await loadMemories()
  } catch (error) {
    ElMessage.error('保存失败：' + (error.response?.data?.detail || error.message))
  } finally {
    saving.value = false
  }
}

const deleteMemory = async (memoryId) => {
  try {
    await axios.delete(`/api/v1/projects/${props.projectId}/memories/${memoryId}`)
    ElMessage.success('记忆已删除')
    await loadMemories()
  } catch (error) {
    ElMessage.error('删除失败：' + (error.response?.data?.detail || error.message))
  }
}

const toggleMemoryActive = async (memory, value) => {
  try {
    await axios.put(`/api/v1/projects/${props.projectId}/memories/${memory.id}`, {
      is_active: value
    })
    memory.is_active = value
    ElMessage.success(value ? '记忆已启用' : '记忆已停用')

    if (filters.value.is_active !== 'all') {
      await loadMemories()
    }
  } catch (error) {
    ElMessage.error('更新状态失败：' + (error.response?.data?.detail || error.message))
  }
}

watch(filters, () => {
  loadMemories()
}, { deep: true })

watch(() => props.projectId, () => {
  loadMemories()
})

onMounted(() => {
  loadMemories()
})
</script>

<style scoped>
.memory-panel {
  padding-bottom: 40px;
}

.panel-card {
  border: 1px solid #333;
  background-color: var(--app-surface-2);
}

.card-header,
.header-actions,
.memory-card-header,
.memory-actions,
.memory-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.header-actions,
.memory-actions,
.memory-meta-group,
.tag-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-form {
  display: flex;
  flex-wrap: wrap;
}

.filter-select {
  width: 180px;
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.memory-card {
  border: 1px solid #333;
  background: #252525;
}

.memory-content {
  color: #ddd;
  white-space: pre-wrap;
  line-height: 1.7;
}

.memory-footer {
  margin-top: 16px;
  align-items: flex-end;
}

.memory-status {
  font-size: 12px;
}

.memory-status.is-active {
  color: #67c23a;
}

.memory-status.is-inactive {
  color: #909399;
}

.switch-label,
.section-subtext {
  color: #909399;
  font-size: 12px;
}

.w-full {
  width: 100%;
}

.mb-4 {
  margin-bottom: 24px;
}

@media (max-width: 768px) {
  .card-header,
  .memory-card-header,
  .memory-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .filter-select {
    width: 100%;
  }
}
</style>
