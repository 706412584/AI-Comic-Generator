<template>
  <div class="progress-panel">
    <el-card shadow="never" class="panel-card mb-4">
      <template #header>
        <div class="card-header">
          <span>当前进度</span>
          <el-button type="primary" :loading="savingProgress" @click="saveProgress">保存进度</el-button>
        </div>
      </template>

      <el-form :model="progressForm" label-width="110px">
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="当前章节">
              <el-select v-model="progressForm.current_chapter_id" clearable placeholder="请选择章节" class="w-full">
                <el-option
                  v-for="chapter in chapterOptions"
                  :key="chapter.id"
                  :label="chapterLabel(chapter.id)"
                  :value="chapter.id"
                />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="当前篇章">
              <el-input v-model="progressForm.current_arc" placeholder="例如：学院篇、复仇篇" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="当前地点">
              <el-input v-model="progressForm.current_location" placeholder="例如：王都北区" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="当前时间">
              <el-input v-model="progressForm.current_time" placeholder="例如：深夜、三日后" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="主冲突">
          <el-input v-model="progressForm.main_conflict" type="textarea" :rows="3" resize="vertical" />
        </el-form-item>

        <el-row :gutter="16">
          <el-col :xs="24" :md="8">
            <el-form-item label="活跃线索">
              <el-input v-model="activeThreadsText" type="textarea" :rows="4" resize="vertical" placeholder="用逗号分隔输入" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="8">
            <el-form-item label="已解决线索">
              <el-input v-model="resolvedThreadsText" type="textarea" :rows="4" resize="vertical" placeholder="用逗号分隔输入" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="8">
            <el-form-item label="待回收钩子">
              <el-input v-model="pendingHooksText" type="textarea" :rows="4" resize="vertical" placeholder="用逗号分隔输入" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="备注">
          <el-input v-model="progressForm.notes" type="textarea" :rows="4" resize="vertical" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="panel-card mb-4">
      <template #header>
        <div class="card-header">
          <span>角色状态筛选</span>
          <div class="header-actions">
            <el-button @click="resetStateFilters">重置筛选</el-button>
            <el-button type="primary" @click="openStateDialog()">新增角色状态</el-button>
          </div>
        </div>
      </template>

      <el-form inline class="filter-form">
        <el-form-item label="关联章节">
          <el-select v-model="stateFilters.chapter_id" clearable placeholder="全部章节" class="filter-select">
            <el-option
              v-for="chapter in chapterOptions"
              :key="chapter.id"
              :label="chapterLabel(chapter.id)"
              :value="chapter.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="角色">
          <el-select v-model="stateFilters.character_id" clearable placeholder="全部角色" class="filter-select">
            <el-option
              v-for="character in characterOptions"
              :key="character.id"
              :label="character.name"
              :value="character.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>角色状态列表</span>
          <span class="section-subtext">共 {{ states.length }} 条</span>
        </div>
      </template>

      <el-empty v-if="!states.length && !loadingStates" description="暂无角色状态" />

      <div v-else v-loading="loadingStates" class="state-list">
        <el-card v-for="state in states" :key="state.id" shadow="hover" class="state-card">
          <template #header>
            <div class="card-header state-card-header">
              <div>
                <div class="state-title">{{ characterLabel(state.character_id) }}</div>
                <div class="state-subtext">{{ chapterLabel(state.chapter_id) }}</div>
              </div>
              <div class="state-actions">
                <el-button size="small" link type="primary" @click="openStateDialog(state)">编辑</el-button>
                <el-popconfirm title="确定删除这条角色状态吗？" @confirm="deleteState(state.id)">
                  <template #reference>
                    <el-button size="small" link type="danger">删除</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </div>
          </template>

          <div class="state-grid">
            <div class="state-item"><span class="label">身体状态</span><span class="value">{{ state.physical_state || '未设置' }}</span></div>
            <div class="state-item"><span class="label">情绪状态</span><span class="value">{{ state.emotional_state || '未设置' }}</span></div>
            <div class="state-item"><span class="label">所在地点</span><span class="value">{{ state.location || '未设置' }}</span></div>
            <div class="state-item"><span class="label">服饰方案</span><span class="value">{{ outfitLabel(state.character_id, state.outfit_id) }}</span></div>
            <div class="state-item"><span class="label">当前目标</span><span class="value">{{ state.goal || '未设置' }}</span></div>
            <div class="state-item"><span class="label">隐藏秘密</span><span class="value">{{ state.secret || '未设置' }}</span></div>
            <div class="state-item"><span class="label">战力等级</span><span class="value">{{ state.power_level || '未设置' }}</span></div>
            <div class="state-item"><span class="label">携带物品</span><span class="value">{{ listLabel(state.inventory) }}</span></div>
          </div>

          <div v-if="state.notes" class="state-notes">{{ state.notes }}</div>
        </el-card>
      </div>
    </el-card>

    <el-dialog v-model="showStateDialog" :title="editingState ? '编辑角色状态' : '新增角色状态'" width="820px">
      <el-form :model="stateForm" label-width="110px">
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="角色">
              <el-select v-model="stateForm.character_id" placeholder="请选择角色" class="w-full">
                <el-option
                  v-for="character in characterOptions"
                  :key="character.id"
                  :label="character.name"
                  :value="character.id"
                />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="关联章节">
              <el-select v-model="stateForm.chapter_id" clearable placeholder="可选" class="w-full">
                <el-option
                  v-for="chapter in chapterOptions"
                  :key="chapter.id"
                  :label="chapterLabel(chapter.id)"
                  :value="chapter.id"
                />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="身体状态">
              <el-input v-model="stateForm.physical_state" placeholder="例如：轻伤、疲惫" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="情绪状态">
              <el-input v-model="stateForm.emotional_state" placeholder="例如：愤怒、冷静" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="所在地点">
              <el-input v-model="stateForm.location" placeholder="例如：城门外营地" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="服饰方案">
              <el-select v-model="stateForm.outfit_id" clearable placeholder="可选" class="w-full" :loading="loadingOutfits">
                <el-option
                  v-for="outfit in stateOutfitOptions"
                  :key="outfit.id"
                  :label="outfit.name"
                  :value="outfit.id"
                />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="当前目标">
              <el-input v-model="stateForm.goal" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="隐藏秘密">
              <el-input v-model="stateForm.secret" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="战力等级">
              <el-input v-model="stateForm.power_level" placeholder="例如：一阶、宗师" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="携带物品">
              <el-input v-model="inventoryText" placeholder="用逗号分隔输入" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="备注">
          <el-input v-model="stateForm.notes" type="textarea" :rows="4" resize="vertical" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showStateDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingState" @click="saveState">保存</el-button>
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

const createDefaultProgressForm = () => ({
  current_chapter_id: null,
  current_arc: '',
  current_location: '',
  current_time: '',
  main_conflict: '',
  active_threads: [],
  resolved_threads: [],
  pending_hooks: [],
  notes: ''
})

const createDefaultStateForm = () => ({
  character_id: null,
  chapter_id: null,
  physical_state: '',
  emotional_state: '',
  location: '',
  outfit_id: null,
  goal: '',
  secret: '',
  power_level: '',
  inventory: [],
  notes: ''
})

const progressForm = ref(createDefaultProgressForm())
const activeThreadsText = ref('')
const resolvedThreadsText = ref('')
const pendingHooksText = ref('')
const savingProgress = ref(false)

const states = ref([])
const loadingStates = ref(false)
const savingState = ref(false)
const showStateDialog = ref(false)
const editingState = ref(null)
const stateForm = ref(createDefaultStateForm())
const inventoryText = ref('')
const loadingOutfits = ref(false)
const outfitOptionsMap = ref({})

const stateFilters = ref({
  chapter_id: null,
  character_id: null
})

const chapterOptions = computed(() => {
  const chapters = props.project?.chapters || []
  return [...chapters].sort((a, b) => a.sequence - b.sequence)
})

const characterOptions = computed(() => {
  const characters = props.project?.characters || []
  return [...characters].sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
})

const stateOutfitOptions = computed(() => {
  const characterId = stateForm.value.character_id
  if (!characterId) return []
  return outfitOptionsMap.value[characterId] || []
})

const splitCommaText = (value) => {
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean)
}

const chapterLabel = (chapterId) => {
  if (!chapterId) return '未关联章节'
  const chapter = chapterOptions.value.find(item => item.id === chapterId)
  return chapter ? `第 ${chapter.sequence} 章：${chapter.title}` : `章节 #${chapterId}`
}

const characterLabel = (characterId) => {
  const character = characterOptions.value.find(item => item.id === characterId)
  return character?.name || `角色 #${characterId}`
}

const listLabel = (items) => {
  return items?.length ? items.join('，') : '未设置'
}

const outfitLabel = (characterId, outfitId) => {
  if (!outfitId) return '未设置'
  const outfits = outfitOptionsMap.value[characterId] || []
  const outfit = outfits.find(item => item.id === outfitId)
  return outfit?.name || `服饰 #${outfitId}`
}

const applyProgressForm = (data = {}) => {
  progressForm.value = {
    current_chapter_id: data.current_chapter_id ?? null,
    current_arc: data.current_arc || '',
    current_location: data.current_location || '',
    current_time: data.current_time || '',
    main_conflict: data.main_conflict || '',
    active_threads: data.active_threads || [],
    resolved_threads: data.resolved_threads || [],
    pending_hooks: data.pending_hooks || [],
    notes: data.notes || ''
  }
  activeThreadsText.value = (progressForm.value.active_threads || []).join(',')
  resolvedThreadsText.value = (progressForm.value.resolved_threads || []).join(',')
  pendingHooksText.value = (progressForm.value.pending_hooks || []).join(',')
}

const loadProgress = async () => {
  try {
    const response = await axios.get(`/api/v1/projects/${props.projectId}/progress`)
    applyProgressForm(response.data || {})
  } catch (error) {
    ElMessage.error('加载当前进度失败：' + (error.response?.data?.detail || error.message))
  }
}

const saveProgress = async () => {
  savingProgress.value = true
  try {
    const payload = {
      ...progressForm.value,
      current_chapter_id: progressForm.value.current_chapter_id || null,
      active_threads: splitCommaText(activeThreadsText.value),
      resolved_threads: splitCommaText(resolvedThreadsText.value),
      pending_hooks: splitCommaText(pendingHooksText.value)
    }
    const response = await axios.put(`/api/v1/projects/${props.projectId}/progress`, payload)
    applyProgressForm(response.data || payload)
    ElMessage.success('当前进度已保存')
  } catch (error) {
    ElMessage.error('保存进度失败：' + (error.response?.data?.detail || error.message))
  } finally {
    savingProgress.value = false
  }
}

const loadStates = async () => {
  loadingStates.value = true
  try {
    const params = {}
    if (stateFilters.value.chapter_id) params.chapter_id = stateFilters.value.chapter_id
    if (stateFilters.value.character_id) params.character_id = stateFilters.value.character_id

    const response = await axios.get(`/api/v1/projects/${props.projectId}/character-states`, { params })
    const data = response.data || []
    states.value = data

    const uniqueCharacterIds = [...new Set(data.map(item => item.character_id).filter(Boolean))]
    await Promise.all(uniqueCharacterIds.map(characterId => ensureOutfitsLoaded(characterId)))
  } catch (error) {
    ElMessage.error('加载角色状态失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loadingStates.value = false
  }
}

const resetStateFilters = () => {
  stateFilters.value = {
    chapter_id: null,
    character_id: null
  }
}

const ensureOutfitsLoaded = async (characterId) => {
  if (!characterId || outfitOptionsMap.value[characterId]) return

  loadingOutfits.value = true
  try {
    const response = await axios.get(`/api/v1/projects/${props.projectId}/characters/${characterId}/outfits`)
    outfitOptionsMap.value = {
      ...outfitOptionsMap.value,
      [characterId]: response.data || []
    }
  } catch (error) {
    ElMessage.error('加载服饰方案失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loadingOutfits.value = false
  }
}

const openStateDialog = async (state = null) => {
  editingState.value = state
  stateForm.value = state
    ? {
        character_id: state.character_id,
        chapter_id: state.chapter_id ?? null,
        physical_state: state.physical_state || '',
        emotional_state: state.emotional_state || '',
        location: state.location || '',
        outfit_id: state.outfit_id ?? null,
        goal: state.goal || '',
        secret: state.secret || '',
        power_level: state.power_level || '',
        inventory: state.inventory || [],
        notes: state.notes || ''
      }
    : createDefaultStateForm()
  inventoryText.value = (stateForm.value.inventory || []).join(',')
  if (stateForm.value.character_id) {
    await ensureOutfitsLoaded(stateForm.value.character_id)
  }
  showStateDialog.value = true
}

const saveState = async () => {
  if (!stateForm.value.character_id) {
    return ElMessage.warning('请选择角色')
  }

  savingState.value = true
  try {
    const payload = {
      ...stateForm.value,
      chapter_id: stateForm.value.chapter_id || null,
      outfit_id: stateForm.value.outfit_id || null,
      inventory: splitCommaText(inventoryText.value)
    }
    if (editingState.value) {
      await axios.put(`/api/v1/projects/${props.projectId}/character-states/${editingState.value.id}`, payload)
    } else {
      await axios.post(`/api/v1/projects/${props.projectId}/character-states`, payload)
    }
    ElMessage.success(editingState.value ? '角色状态已更新' : '角色状态已创建')
    showStateDialog.value = false
    await loadStates()
  } catch (error) {
    ElMessage.error('保存角色状态失败：' + (error.response?.data?.detail || error.message))
  } finally {
    savingState.value = false
  }
}

const deleteState = async (stateId) => {
  try {
    await axios.delete(`/api/v1/projects/${props.projectId}/character-states/${stateId}`)
    ElMessage.success('角色状态已删除')
    await loadStates()
  } catch (error) {
    ElMessage.error('删除角色状态失败：' + (error.response?.data?.detail || error.message))
  }
}

watch(() => stateForm.value.character_id, async (characterId, oldCharacterId) => {
  if (!characterId) {
    stateForm.value.outfit_id = null
    return
  }
  await ensureOutfitsLoaded(characterId)
  if (oldCharacterId && oldCharacterId !== characterId) {
    stateForm.value.outfit_id = null
  }
})

watch(stateFilters, () => {
  loadStates()
}, { deep: true })

watch(() => props.projectId, () => {
  loadProgress()
  loadStates()
})

onMounted(() => {
  loadProgress()
  loadStates()
})
</script>

<style scoped>
.progress-panel {
  padding-bottom: 40px;
}

.panel-card {
  border: 1px solid #333;
  background-color: var(--app-surface-2);
}

.card-header,
.header-actions,
.state-card-header,
.state-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.header-actions,
.state-actions,
.filter-form {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-select {
  width: 180px;
}

.state-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.state-card {
  border: 1px solid #333;
  background: #252525;
}

.state-title {
  color: #e5eaf3;
  font-weight: 600;
}

.state-subtext,
.section-subtext,
.label {
  color: #909399;
}

.state-subtext {
  margin-top: 4px;
  font-size: 12px;
}

.state-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.state-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #1f1f1f;
}

.value,
.state-notes {
  color: #ddd;
  white-space: pre-wrap;
  line-height: 1.6;
}

.state-notes {
  margin-top: 16px;
}

.w-full {
  width: 100%;
}

.mb-4 {
  margin-bottom: 24px;
}

@media (max-width: 768px) {
  .card-header,
  .state-card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .state-grid {
    grid-template-columns: 1fr;
  }

  .filter-select {
    width: 100%;
  }
}
</style>
