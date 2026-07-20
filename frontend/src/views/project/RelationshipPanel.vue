<template>
  <div class="relationship-panel">
    <el-card shadow="never" class="panel-card mb-4">
      <template #header>
        <div class="card-header">
          <span>人物关系筛选</span>
          <div class="header-actions">
            <el-button @click="resetFilters">重置筛选</el-button>
            <el-button type="primary" @click="openRelationshipDialog()">新增关系</el-button>
          </div>
        </div>
      </template>

      <el-form inline class="filter-form">
        <el-form-item label="关联章节">
          <el-select v-model="filters.chapter_id" clearable placeholder="全部章节" class="filter-select">
            <el-option
              v-for="chapter in chapterOptions"
              :key="chapter.id"
              :label="chapterLabel(chapter.id)"
              :value="chapter.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="关系状态">
          <el-select v-model="filters.status" clearable placeholder="全部状态" class="filter-select">
            <el-option label="进行中" value="active" />
            <el-option label="已结束" value="ended" />
            <el-option label="已变化" value="changed" />
            <el-option label="冻结" value="paused" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="panel-card">
      <template #header>
        <div class="card-header">
          <span>人物关系列表</span>
          <span class="section-subtext">共 {{ relationships.length }} 条</span>
        </div>
      </template>

      <el-empty v-if="!relationships.length && !loading" description="暂无人物关系" />

      <div v-else v-loading="loading" class="relationship-list">
        <el-card v-for="relationship in relationships" :key="relationship.id" shadow="hover" class="relationship-card">
          <template #header>
            <div class="card-header relationship-card-header">
              <div>
                <div class="relationship-title">
                  {{ characterLabel(relationship.source_character_id) }}
                  <span class="arrow">→</span>
                  {{ characterLabel(relationship.target_character_id) }}
                </div>
                <div class="relationship-subtext">
                  {{ relationship.relationship_type || '未设置关系类型' }}
                </div>
              </div>
              <div class="relationship-actions">
                <el-button size="small" link type="primary" @click="openRelationshipDialog(relationship)">编辑</el-button>
                <el-popconfirm title="确定删除这条关系吗？" @confirm="deleteRelationship(relationship.id)">
                  <template #reference>
                    <el-button size="small" link type="danger">删除</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </div>
          </template>

          <div class="meta-row">
            <el-tag size="small" type="success">类型：{{ relationship.relationship_type || '未设置' }}</el-tag>
            <el-tag size="small" type="warning">强度：{{ relationship.intensity ?? '-' }}</el-tag>
            <el-tag size="small" :type="statusTagType(relationship.status)">状态：{{ relationship.status || '未设置' }}</el-tag>
            <el-tag size="small" type="info">章节：{{ chapterLabel(relationship.chapter_id) }}</el-tag>
          </div>

          <div v-if="relationship.description" class="relationship-description">
            {{ relationship.description }}
          </div>

          <div v-if="relationship.tags?.length" class="tag-list">
            <el-tag v-for="tag in relationship.tags" :key="tag" size="small" effect="dark">{{ tag }}</el-tag>
          </div>
        </el-card>
      </div>
    </el-card>

    <el-dialog v-model="showDialog" :title="editingRelationship ? '编辑人物关系' : '新增人物关系'" width="760px">
      <el-form :model="relationshipForm" label-width="110px">
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <el-form-item label="来源角色">
              <el-select v-model="relationshipForm.source_character_id" placeholder="请选择角色" class="w-full">
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
            <el-form-item label="目标角色">
              <el-select v-model="relationshipForm.target_character_id" placeholder="请选择角色" class="w-full">
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
            <el-form-item label="关系类型">
              <el-input v-model="relationshipForm.relationship_type" placeholder="例如：师徒、亲人、敌对" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="关系状态">
              <el-input v-model="relationshipForm.status" placeholder="例如：active、ended" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="关系强度">
              <el-input-number v-model="relationshipForm.intensity" :min="1" :max="5" class="w-full" />
            </el-form-item>
          </el-col>

          <el-col :xs="24" :md="12">
            <el-form-item label="关联章节">
              <el-select v-model="relationshipForm.chapter_id" clearable placeholder="可选" class="w-full">
                <el-option
                  v-for="chapter in chapterOptions"
                  :key="chapter.id"
                  :label="chapterLabel(chapter.id)"
                  :value="chapter.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="关系说明">
          <el-input
            v-model="relationshipForm.description"
            type="textarea"
            :rows="4"
            resize="vertical"
            placeholder="请输入关系背景、变化原因、约束等说明"
          />
        </el-form-item>

        <el-form-item label="标签">
          <el-input v-model="tagsText" placeholder="多个标签用逗号分隔，例如：主线,冲突,隐藏身份" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRelationship">保存</el-button>
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

const loading = ref(false)
const saving = ref(false)
const showDialog = ref(false)
const editingRelationship = ref(null)
const relationships = ref([])
const tagsText = ref('')

const filters = ref({
  chapter_id: null,
  status: null
})

const createDefaultForm = () => ({
  source_character_id: null,
  target_character_id: null,
  relationship_type: '',
  description: '',
  status: 'active',
  intensity: 3,
  chapter_id: null,
  tags: []
})

const relationshipForm = ref(createDefaultForm())

const chapterOptions = computed(() => {
  const chapters = props.project?.chapters || []
  return [...chapters].sort((a, b) => a.sequence - b.sequence)
})

const characterOptions = computed(() => {
  const characters = props.project?.characters || []
  return [...characters].sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
})

const chapterLabel = (chapterId) => {
  if (!chapterId) return '未关联章节'
  const chapter = chapterOptions.value.find(item => item.id === chapterId)
  return chapter ? `第 ${chapter.sequence} 章：${chapter.title}` : `章节 #${chapterId}`
}

const characterLabel = (characterId) => {
  const character = characterOptions.value.find(item => item.id === characterId)
  return character?.name || `角色 #${characterId}`
}

const statusTagType = (status) => {
  if (status === 'active') return 'success'
  if (status === 'ended') return 'info'
  if (status === 'changed') return 'warning'
  if (status === 'paused') return 'danger'
  return ''
}

const loadRelationships = async () => {
  loading.value = true
  try {
    const response = await axios.get(`/api/v1/projects/${props.projectId}/relationships`)
    let data = response.data || []

    if (filters.value.chapter_id) {
      data = data.filter(item => item.chapter_id === filters.value.chapter_id)
    }
    if (filters.value.status) {
      data = data.filter(item => item.status === filters.value.status)
    }

    relationships.value = data
  } catch (error) {
    ElMessage.error('加载人物关系失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

const resetFilters = () => {
  filters.value = {
    chapter_id: null,
    status: null
  }
}

const openRelationshipDialog = (relationship = null) => {
  editingRelationship.value = relationship
  relationshipForm.value = relationship
    ? {
        source_character_id: relationship.source_character_id,
        target_character_id: relationship.target_character_id,
        relationship_type: relationship.relationship_type || '',
        description: relationship.description || '',
        status: relationship.status || 'active',
        intensity: relationship.intensity ?? 3,
        chapter_id: relationship.chapter_id ?? null,
        tags: relationship.tags || []
      }
    : createDefaultForm()
  tagsText.value = (relationshipForm.value.tags || []).join(',')
  showDialog.value = true
}

const buildPayload = () => ({
  ...relationshipForm.value,
  chapter_id: relationshipForm.value.chapter_id || null,
  tags: tagsText.value.split(',').map(tag => tag.trim()).filter(Boolean)
})

const saveRelationship = async () => {
  if (!relationshipForm.value.source_character_id || !relationshipForm.value.target_character_id) {
    return ElMessage.warning('请选择来源角色和目标角色')
  }
  if (!relationshipForm.value.relationship_type.trim()) {
    return ElMessage.warning('请输入关系类型')
  }

  saving.value = true
  try {
    const payload = buildPayload()
    if (editingRelationship.value) {
      await axios.put(`/api/v1/projects/${props.projectId}/relationships/${editingRelationship.value.id}`, payload)
    } else {
      await axios.post(`/api/v1/projects/${props.projectId}/relationships`, payload)
    }
    ElMessage.success(editingRelationship.value ? '人物关系已更新' : '人物关系已创建')
    showDialog.value = false
    await loadRelationships()
  } catch (error) {
    ElMessage.error('保存失败：' + (error.response?.data?.detail || error.message))
  } finally {
    saving.value = false
  }
}

const deleteRelationship = async (relationshipId) => {
  try {
    await axios.delete(`/api/v1/projects/${props.projectId}/relationships/${relationshipId}`)
    ElMessage.success('人物关系已删除')
    await loadRelationships()
  } catch (error) {
    ElMessage.error('删除失败：' + (error.response?.data?.detail || error.message))
  }
}

watch(filters, () => {
  loadRelationships()
}, { deep: true })

watch(() => props.projectId, () => {
  loadRelationships()
})

onMounted(() => {
  loadRelationships()
})
</script>

<style scoped>
.relationship-panel {
  padding-bottom: 40px;
}

.panel-card {
  border: 1px solid #333;
  background-color: #1e1e1e;
}

.card-header,
.header-actions,
.relationship-card-header,
.relationship-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.header-actions,
.relationship-actions,
.tag-list,
.meta-row {
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

.relationship-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.relationship-card {
  border: 1px solid #333;
  background: #252525;
}

.relationship-title {
  color: #e5eaf3;
  font-weight: 600;
}

.relationship-subtext,
.relationship-description,
.section-subtext {
  color: #a3a6ad;
}

.relationship-subtext {
  margin-top: 4px;
  font-size: 12px;
}

.relationship-description {
  margin-top: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.meta-row {
  margin-top: 4px;
}

.arrow {
  margin: 0 8px;
  color: #909399;
}

.w-full {
  width: 100%;
}

.mb-4 {
  margin-bottom: 24px;
}

@media (max-width: 768px) {
  .card-header,
  .relationship-card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .filter-select {
    width: 100%;
  }
}
</style>
