<template>
  <div class="home-view">
    <div class="toolbar">
      <h2 class="page-title">我的项目</h2>
      <div class="toolbar-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索项目标题 / 描述"
          clearable
          class="search-input"
          :prefix-icon="Search"
        />
        <el-select v-model="sortBy" class="sort-select">
          <el-option label="最近更新" value="updated" />
          <el-option label="最近创建" value="created" />
          <el-option label="标题排序" value="title" />
        </el-select>
        <template v-if="!selectionMode">
          <el-button :icon="Upload" :loading="importingProject" @click="openImportPicker">导入项目</el-button>
          <el-button @click="enterSelectionMode">批量管理</el-button>
        </template>
        <template v-else>
          <el-button :disabled="!filteredProjects.length" @click="selectAllFiltered">全选</el-button>
          <el-button :disabled="!filteredProjects.length" @click="invertFilteredSelection">反选</el-button>
          <el-button
            :icon="Download"
            :disabled="selectedIds.size !== 1"
            :loading="exportingProject"
            @click="exportSelectedProject"
          >
            导出项目
          </el-button>
          <el-button
            type="danger"
            :icon="Delete"
            :disabled="!selectedIds.size"
            @click="batchDelete"
          >
            删除所选 ({{ selectedIds.size }})
          </el-button>
          <el-button @click="exitSelectionMode">退出批量</el-button>
        </template>
        <el-button type="primary" :icon="Plus" @click="openCreateDialog">新建项目</el-button>
        <input ref="importInput" type="file" accept=".zip,application/zip" hidden @change="importProjectZip" />
      </div>
    </div>

    <el-empty v-if="!loading && filteredProjects.length === 0" description="没有找到项目">
      <el-button type="primary" @click="openCreateDialog">创建第一个项目</el-button>
    </el-empty>

    <div class="project-grid">
      <div
        v-for="project in pagedProjects"
        :key="project.id"
        class="project-card"
        :class="{ selected: selectedIds.has(project.id), 'select-mode': selectionMode }"
        @click="handleCardClick(project.id)"
      >
        <div v-if="selectionMode" class="select-badge" @click.stop="toggleSelect(project.id)">
          <el-checkbox :model-value="selectedIds.has(project.id)" @click.stop />
        </div>
        <div class="cover">
          <img :src="project.cover_image || defaultCover" loading="lazy" :alt="`${project.title} 封面`" />
          <div class="cover-badges">
            <span class="badge" :class="project.workflow_mode === 'novel_comic' ? 'badge-novel' : 'badge-comic'">
              {{ project.workflow_mode === 'novel_comic' ? '小说改编' : '漫画创作' }}
            </span>
            <span v-if="project.chapter_count" class="badge badge-plain">{{ project.chapter_count }} 章</span>
          </div>
        </div>
        <div class="card-body">
          <div class="card-title-row">
            <span class="project-title" :title="project.title">{{ project.title }}</span>
            <div class="actions" @click.stop>
              <el-button link :icon="Edit" @click="openEditDialog(project)" />
              <el-button link :icon="Delete" @click="deleteProject(project.id)" />
            </div>
          </div>
          <p class="project-desc">{{ cardDescription(project) }}</p>
          <div class="card-footer">
            <span>{{ relativeTime(project.updated_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="pagination-wrap" v-if="filteredProjects.length > pageSize">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="filteredProjects.length"
        layout="prev, pager, next, total"
        background
      />
    </div>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑项目' : '新建项目'" width="480px">
      <el-form :model="form" label-width="60px">
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="给作品起个名字" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input type="textarea" v-model="form.description" :rows="3" placeholder="一句话介绍这个故事（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveProject">{{ isEdit ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, Edit, Delete, Download, Upload } from '@element-plus/icons-vue'

const router = useRouter()
const projects = ref([])
const loading = ref(true)
const dialogVisible = ref(false)
const isEdit = ref(false)
const form = ref({ id: '', title: '', description: '' })

const searchText = ref('')
const sortBy = ref('updated')
const selectionMode = ref(false)
const selectedIds = ref(new Set())
const defaultCover = '/default-project-cover.png'
const importInput = ref(null)
const importingProject = ref(false)
const exportingProject = ref(false)

const enterSelectionMode = () => {
  selectionMode.value = true
  selectedIds.value = new Set()
}

const exitSelectionMode = () => {
  selectionMode.value = false
  selectedIds.value = new Set()
}

const toggleSelect = (id) => {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

const selectAllFiltered = () => {
  selectedIds.value = new Set(filteredProjects.value.map(project => project.id))
}

const invertFilteredSelection = () => {
  selectedIds.value = new Set(
    filteredProjects.value
      .filter(project => !selectedIds.value.has(project.id))
      .map(project => project.id)
  )
}

const handleCardClick = (id) => {
  if (selectionMode.value) {
    toggleSelect(id)
  } else {
    goToProject(id)
  }
}

const openImportPicker = () => importInput.value?.click()

const importProjectZip = async (event) => {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.warning('请选择 ZIP 格式的项目备份')
    return
  }
  importingProject.value = true
  try {
    const res = await axios.post('/api/v1/projects/import', file, {
      headers: { 'Content-Type': 'application/zip' },
      maxBodyLength: Infinity
    })
    ElMessage.success(`项目“${res.data.title}”导入成功`)
    await fetchProjects()
  } catch (e) {
    ElMessage.error('项目导入失败：' + (e.response?.data?.detail || e.message))
  } finally {
    importingProject.value = false
  }
}

const exportSelectedProject = async () => {
  if (selectedIds.value.size !== 1) return
  const projectId = Array.from(selectedIds.value)[0]
  const project = projects.value.find(item => item.id === projectId)
  exportingProject.value = true
  try {
    const res = await axios.get(`/api/v1/projects/${projectId}/archive`, { responseType: 'blob' })
    const disposition = res.headers['content-disposition'] || ''
    const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
    const filename = encodedName ? decodeURIComponent(encodedName) : `${project?.title || 'project'}.zip`
    const url = URL.createObjectURL(res.data)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('项目 ZIP 导出完成')
  } catch (e) {
    ElMessage.error('项目导出失败：' + (e.response?.data?.detail || e.message))
  } finally {
    exportingProject.value = false
  }
}

const batchDelete = async () => {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${ids.length} 个项目？此操作不可恢复，项目下的章节、角色、分镜等都会一并删除。`,
      '批量删除项目',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const res = await axios.post('/api/v1/projects/batch-delete', { project_ids: ids })
    ElMessage.success(`已删除 ${res.data.deleted} 个项目`)
    exitSelectionMode()
    fetchProjects()
  } catch (e) {
    ElMessage.error('批量删除失败：' + (e.response?.data?.detail || e.message))
  }
}
const currentPage = ref(1)
const pageSize = 12

const filteredProjects = computed(() => {
  const kw = searchText.value.trim().toLowerCase()
  let list = projects.value
  if (kw) {
    list = list.filter(p =>
      (p.title || '').toLowerCase().includes(kw) ||
      (p.description || '').toLowerCase().includes(kw) ||
      (p.story_input || '').toLowerCase().includes(kw)
    )
  }
  const sorted = [...list]
  if (sortBy.value === 'updated') {
    sorted.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
  } else if (sortBy.value === 'created') {
    sorted.sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
  } else {
    sorted.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh-CN'))
  }
  return sorted
})

const pagedProjects = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredProjects.value.slice(start, start + pageSize)
})

watch([searchText, sortBy], () => {
  currentPage.value = 1
})

const cardDescription = (project) => {
  if (project.description) return project.description
  if (project.story_input) return project.story_input.slice(0, 60)
  return '还没有故事内容，点击进入开始创作'
}

const relativeTime = (dateStr) => {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

const fetchProjects = async () => {
  loading.value = true
  try {
    const res = await axios.get('/api/v1/projects/')
    projects.value = res.data
  } catch (error) {
    ElMessage.error('获取项目失败')
  } finally {
    loading.value = false
  }
}

const openCreateDialog = () => {
  isEdit.value = false
  form.value = { title: '', description: '' }
  dialogVisible.value = true
}

const openEditDialog = (project) => {
  isEdit.value = true
  form.value = { id: project.id, title: project.title, description: project.description }
  dialogVisible.value = true
}

const saveProject = async () => {
  if (isEdit.value) {
    await updateProject()
  } else {
    await createProject()
  }
}

const createProject = async () => {
  try {
    const res = await axios.post('/api/v1/projects/', form.value)
    ElMessage.success('创建成功')
    dialogVisible.value = false
    goToProject(res.data.id)
  } catch (error) {
    ElMessage.error('创建项目失败')
  }
}

const updateProject = async () => {
  try {
    await axios.put(`/api/v1/projects/${form.value.id}`, {
      title: form.value.title,
      description: form.value.description
    })
    ElMessage.success('更新成功')
    dialogVisible.value = false
    fetchProjects()
  } catch (error) {
    ElMessage.error('更新项目失败')
  }
}

const deleteProject = async (id) => {
  try {
    await ElMessageBox.confirm('删除后项目下的章节、角色、分镜等数据都会一并删除，确定吗？', '删除项目', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  try {
    await axios.delete(`/api/v1/projects/${id}`)
    ElMessage.success('删除成功')
    fetchProjects()
  } catch (error) {
    ElMessage.error('删除项目失败')
  }
}

const goToProject = (id) => {
  router.push(`/project/${id}`)
}

onMounted(fetchProjects)
</script>

<style scoped>
.home-view {
  padding: 24px 32px;
  max-width: 1400px;
  margin: 0 auto;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  gap: 16px;
  flex-wrap: wrap;
}
.page-title {
  margin: 0;
  font-size: 22px;
  letter-spacing: 0.5px;
}
.toolbar-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}
.search-input {
  width: 240px;
}
.sort-select {
  width: 130px;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 20px;
}

.project-card {
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.2s, box-shadow 0.2s;
}
.project-card:hover {
  transform: translateY(-3px);
  border-color: var(--app-accent);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.cover {
  position: relative;
  height: 140px;
  overflow: hidden;
  background: var(--app-surface-2);
}
.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.cover-badges {
  position: absolute;
  top: 8px;
  left: 8px;
  display: flex;
  gap: 6px;
}
.badge {
  font-size: 11px;
  line-height: 1;
  padding: 4px 8px;
  border-radius: 999px;
  backdrop-filter: blur(4px);
}
.badge-comic {
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.35);
}
.badge-novel {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.35);
}
.badge-plain {
  background: rgba(0, 0, 0, 0.45);
  color: #d1d5db;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.card-body {
  padding: 12px 14px 10px;
}
.card-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.project-title {
  font-weight: 600;
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.actions {
  display: flex;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.project-card:hover .actions {
  opacity: 1;
}
.project-desc {
  margin: 6px 0 10px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.8em;
  color: var(--app-text-secondary);
  font-size: 12.5px;
  line-height: 1.4;
}
.card-footer {
  font-size: 12px;
  color: #6b7280;
}

.pagination-wrap {
  display: flex;
  justify-content: center;
  margin-top: 28px;
}
</style>
