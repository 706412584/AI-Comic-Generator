<template>
  <div class="chapter-tab">
    <el-row :gutter="20">
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="panel-card chapter-list-card">
          <template #header>
            <div class="card-header">
              <span>章节列表</span>
              <el-button type="primary" size="small" @click="openChapterDialog()">新增章节</el-button>
            </div>
          </template>

          <el-empty v-if="!chapters.length" description="暂无章节" />
          <div v-else class="list">
            <div
              v-for="chapter in chapters"
              :key="chapter.id"
              class="list-item"
              :class="{ active: selectedChapterId === chapter.id }"
              @click="selectChapter(chapter.id)"
            >
              <div class="item-main">
                <div class="item-title">第 {{ chapter.sequence }} 章：{{ chapter.title }}</div>
                <div class="item-desc">{{ chapter.summary || '暂无摘要' }}</div>
                <div class="item-meta">
                  <el-tag size="small">{{ statusText(chapter.status) }}</el-tag>
                  <span class="word-count">{{ chapter.word_count || 0 }} 字</span>
                </div>
              </div>
              <div class="item-actions">
                <el-button size="small" link type="primary" @click.stop="openChapterDialog(chapter)">编辑</el-button>
                <el-popconfirm title="确定删除这个章节吗？" @confirm="deleteChapter(chapter.id)">
                  <template #reference>
                    <el-button size="small" link type="danger" @click.stop>删除</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="16">
        <el-card shadow="never" class="panel-card mb-4">
          <template #header>
            <div class="card-header">
              <span>章节详情</span>
              <div class="header-actions">
                <el-radio-group v-model="previewMode" size="small" :disabled="!selectedChapterId">
                  <el-radio-button label="edit">编辑模式</el-radio-button>
                  <el-radio-button label="preview">预览模式</el-radio-button>
                </el-radio-group>
                <el-button
                  type="success"
                  size="small"
                  :disabled="!selectedChapterId"
                  :loading="savingContent"
                  @click="saveChapterContent"
                >
                  保存正文
                </el-button>
                <el-button
                  type="primary"
                  size="small"
                  :disabled="!selectedChapterId"
                  :loading="generatingContent"
                  @click="generateChapterContent"
                >
                  生成章节正文
                </el-button>
                <el-button
                  type="info"
                  size="small"
                  plain
                  :disabled="!selectedChapterId"
                  :loading="reviewingContinuity"
                  @click="reviewChapterContinuity"
                >
                  连续性审查
                </el-button>
                <el-button
                  type="warning"
                  size="small"
                  plain
                  :disabled="!selectedChapterId"
                  :loading="generatingStoryboard"
                  @click="generateChapterStoryboard"
                >
                  生成章节分镜
                </el-button>
              </div>
            </div>
          </template>

          <el-empty v-if="!selectedChapter" description="请选择一个章节查看详情" />
          <template v-else>
            <div class="detail-block">
              <div class="detail-title-row">
                <div>
                  <h3 class="chapter-title">第 {{ selectedChapter.sequence }} 章：{{ selectedChapter.title }}</h3>
                  <p class="chapter-summary">{{ selectedChapter.summary || '暂无章节摘要' }}</p>
                </div>
                <el-tag>{{ statusText(selectedChapter.status) }}</el-tag>
              </div>

              <div class="chapter-detail-grid">
                <div class="meta-card">
                  <span class="meta-label">当前地点</span>
                  <span class="meta-value">{{ selectedChapter.current_location || '未设置' }}</span>
                </div>
                <div class="meta-card">
                  <span class="meta-label">当前时间</span>
                  <span class="meta-value">{{ selectedChapter.current_time || '未设置' }}</span>
                </div>
                <div class="meta-card">
                  <span class="meta-label">视角角色</span>
                  <span class="meta-value">{{ selectedChapter.pov_character || '未设置' }}</span>
                </div>
                <div class="meta-card">
                  <span class="meta-label">字数</span>
                  <span class="meta-value">{{ selectedChapter.word_count || 0 }}</span>
                </div>
              </div>

              <div class="mini-info-grid">
                <div class="mini-info-item">
                  <span class="mini-label">章节目标</span>
                  <span class="mini-value">{{ selectedChapter.goal || '未设置' }}</span>
                </div>
                <div class="mini-info-item">
                  <span class="mini-label">冲突点</span>
                  <span class="mini-value">{{ selectedChapter.conflict || '未设置' }}</span>
                </div>
              </div>
            </div>

            <div class="detail-block source-block">
              <div class="section-header">
                <span>关联原文章节</span>
                <div>
                  <el-button size="small" link type="primary" @click="showSourceDialog = true" :disabled="!currentSourceChapter">查看原文</el-button>
                  <el-button size="small" link type="warning" @click="openBindSourceDialog">重新绑定</el-button>
                </div>
              </div>
              <div class="source-info" v-if="currentSourceChapter">
                <div class="source-title">第 {{ currentSourceChapter.sequence }} 章原文：{{ currentSourceChapter.title }}</div>
                <div class="source-summary">{{ currentSourceChapter.summary_short || '暂无原文摘要，生成时会直接读取原文。' }}</div>
                <div class="source-meta">原文字数：{{ currentSourceChapter.raw_word_count || 0 }}</div>
              </div>
              <el-alert v-else title="当前章节未绑定原文章节，生成时只会使用项目设定和章节摘要。" type="warning" :closable="false" />
            </div>

            <div class="detail-block">
              <div class="section-header">
                <span>章节正文</span>
              </div>

              <el-input
                v-if="previewMode === 'edit'"
                v-model="chapterContent"
                type="textarea"
                :rows="18"
                resize="vertical"
                placeholder="请输入章节正文"
              />
              <div v-else class="content-preview">{{ chapterContent || '暂无章节正文' }}</div>
            </div>

            <div class="detail-block">
              <div class="section-header">
                <span>生成补充要求</span>
              </div>
              <el-input
                v-model="chapterGenerateInput"
                type="textarea"
                :rows="4"
                resize="vertical"
                placeholder="可选：补充本章风格、剧情重点、节奏等要求"
              />
            </div>

            <div class="detail-block">
              <div class="section-header">
                <span>版本历史</span>
                <span class="section-subtext">共 {{ versions.length }} 条</span>
              </div>
              <el-empty v-if="!versions.length" description="暂无版本记录" />
              <div v-else class="version-list">
                <div v-for="version in versions" :key="version.id" class="version-item">
                  <div class="version-main">
                    <div class="version-title">版本 {{ version.version_no }} · {{ version.title }}</div>
                    <div class="version-note">{{ version.change_note || '无备注' }}</div>
                  </div>
                  <div class="version-meta">
                    <span>{{ formatDateTime(version.created_at) }}</span>
                    <div class="version-actions">
                      <el-button size="small" link type="primary" @click="openVersionDetail(version)">详情</el-button>
                      <el-popconfirm title="确定回滚到这个版本吗？当前正文会先保存为快照。" @confirm="rollbackVersion(version)">
                        <template #reference>
                          <el-button size="small" link type="warning">回滚</el-button>
                        </template>
                      </el-popconfirm>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </el-card>

        <el-card shadow="never" class="panel-card mb-4">
          <template #header>
            <div class="card-header">
              <span>大纲 / 小纲</span>
              <el-button type="primary" size="small" @click="openOutlineDialog()">新增大纲</el-button>
            </div>
          </template>

          <el-empty v-if="!filteredOutlines.length" description="暂无大纲" />
          <div v-else class="cards-list">
            <el-card v-for="outline in filteredOutlines" :key="outline.id" shadow="hover" class="content-card">
              <template #header>
                <div class="card-header">
                  <div>
                    <span class="item-title">{{ outline.title }}</span>
                    <el-tag size="small" class="ml-2">{{ outline.scope === 'chapter' ? '章节小纲' : '项目总纲' }}</el-tag>
                  </div>
                  <div>
                    <el-button size="small" link type="primary" @click="openOutlineDialog(outline)">编辑</el-button>
                    <el-popconfirm title="确定删除这个大纲吗？" @confirm="deleteOutline(outline.id)">
                      <template #reference>
                        <el-button size="small" link type="danger">删除</el-button>
                      </template>
                    </el-popconfirm>
                  </div>
                </div>
              </template>
              <p class="content-text">{{ outline.content }}</p>
            </el-card>
          </div>
        </el-card>

        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-header">
              <span>章节任务</span>
              <el-button type="primary" size="small" @click="openTaskDialog()">新增任务</el-button>
            </div>
          </template>

          <el-empty v-if="!filteredTasks.length" description="暂无章节任务" />
          <el-table v-else :data="filteredTasks" style="width: 100%">
            <el-table-column prop="title" label="任务" min-width="160" />
            <el-table-column prop="type" label="类型" width="120" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag>{{ taskStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="openTaskDialog(row)">编辑</el-button>
                <el-popconfirm title="确定删除这个任务吗？" @confirm="deleteTask(row.id)">
                  <template #reference>
                    <el-button size="small" link type="danger">删除</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="showChapterDialog" :title="editingChapter ? '编辑章节' : '新增章节'" width="640px">
      <el-form :model="chapterForm" label-width="90px">
        <el-form-item label="序号"><el-input-number v-model="chapterForm.sequence" :min="1" /></el-form-item>
        <el-form-item label="标题"><el-input v-model="chapterForm.title" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="chapterForm.status" class="w-full">
            <el-option label="草稿" value="draft" />
            <el-option label="规划中" value="planning" />
            <el-option label="分镜中" value="storyboarding" />
            <el-option label="完成" value="done" />
          </el-select>
        </el-form-item>
        <el-form-item label="摘要"><el-input v-model="chapterForm.summary" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="章节目标"><el-input v-model="chapterForm.goal" /></el-form-item>
        <el-form-item label="冲突点"><el-input v-model="chapterForm.conflict" /></el-form-item>
        <el-form-item label="正文素材"><el-input v-model="chapterForm.content" type="textarea" :rows="5" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showChapterDialog = false">取消</el-button>
        <el-button type="primary" @click="saveChapter">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showOutlineDialog" :title="editingOutline ? '编辑大纲' : '新增大纲'" width="640px">
      <el-form :model="outlineForm" label-width="90px">
        <el-form-item label="范围">
          <el-select v-model="outlineForm.scope" class="w-full">
            <el-option label="项目总纲" value="project" />
            <el-option label="章节小纲" value="chapter" />
          </el-select>
        </el-form-item>
        <el-form-item label="章节" v-if="outlineForm.scope === 'chapter'">
          <el-select v-model="outlineForm.chapter_id" clearable class="w-full">
            <el-option v-for="chapter in chapters" :key="chapter.id" :label="`第 ${chapter.sequence} 章：${chapter.title}`" :value="chapter.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="outlineForm.title" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="outlineForm.content" type="textarea" :rows="8" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="outlineForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showOutlineDialog = false">取消</el-button>
        <el-button type="primary" @click="saveOutline">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showVersionDialog" title="章节版本详情" width="760px">
      <div v-if="selectedVersion" class="version-detail">
        <div class="detail-title-row">
          <div>
            <h3>版本 {{ selectedVersion.version_no }} · {{ selectedVersion.title }}</h3>
            <p class="version-note">{{ selectedVersion.change_note || '无备注' }}</p>
          </div>
          <el-tag>{{ formatDateTime(selectedVersion.created_at) }}</el-tag>
        </div>
        <div class="version-content">{{ selectedVersion.content || '暂无正文' }}</div>
      </div>
      <template #footer>
        <el-button @click="showVersionDialog = false">关闭</el-button>
        <el-popconfirm v-if="selectedVersion" title="确定回滚到这个版本吗？当前正文会先保存为快照。" @confirm="rollbackVersion(selectedVersion)">
          <template #reference>
            <el-button type="warning">回滚到此版本</el-button>
          </template>
        </el-popconfirm>
      </template>
    </el-dialog>

    <el-dialog v-model="showContinuityDialog" title="连续性审查结果" width="720px">
      <div v-if="continuityResult" class="continuity-result">
        <el-alert :title="continuityResult.summary" type="info" :closable="false" show-icon />
        <el-empty v-if="!continuityResult.issues?.length" description="未发现明显连续性问题" />
        <div v-else class="continuity-issues">
          <el-card v-for="(issue, index) in continuityResult.issues" :key="index" shadow="never" class="continuity-issue">
            <div class="issue-header">
              <el-tag :type="issueSeverityType(issue.severity)" size="small">{{ issueSeverityText(issue.severity) }}</el-tag>
              <span class="issue-category">{{ issue.category }}</span>
            </div>
            <p class="issue-message">{{ issue.message }}</p>
            <p v-if="issue.evidence" class="issue-detail"><strong>证据：</strong>{{ issue.evidence }}</p>
            <p v-if="issue.suggestion" class="issue-detail"><strong>建议：</strong>{{ issue.suggestion }}</p>
          </el-card>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="showBindSourceDialog" title="绑定原文章节" width="760px">
      <div class="source-bind-actions">
        <el-input v-model="sourceSearch" placeholder="搜索原文章节" clearable @keyup.enter="loadSourceCandidates" />
        <el-button @click="loadSourceCandidates">搜索</el-button>
      </div>
      <el-table :data="sourceCandidates" size="small" max-height="380">
        <el-table-column prop="sequence" label="#" width="70" />
        <el-table-column prop="title" label="原文章节" min-width="260" show-overflow-tooltip />
        <el-table-column prop="raw_word_count" label="字数" width="100" />
        <el-table-column label="操作" width="90">
          <template #default="scope">
            <el-button size="small" link type="primary" @click="bindSourceChapter(scope.row.id)">绑定</el-button>
          </template>
        </el-table-column>
      </el-table>
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

    <el-dialog v-model="showTaskDialog" :title="editingTask ? '编辑任务' : '新增任务'" width="520px">
      <el-form :model="taskForm" label-width="90px">
        <el-form-item label="章节">
          <el-select v-model="taskForm.chapter_id" clearable class="w-full">
            <el-option v-for="chapter in chapters" :key="chapter.id" :label="`第 ${chapter.sequence} 章：${chapter.title}`" :value="chapter.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="taskForm.title" /></el-form-item>
        <el-form-item label="类型"><el-input v-model="taskForm.type" placeholder="例如：分镜、审核、重绘" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="taskForm.status" class="w-full">
            <el-option label="待办" value="todo" />
            <el-option label="进行中" value="doing" />
            <el-option label="已完成" value="done" />
            <el-option label="阻塞" value="blocked" />
            <el-option label="已取消" value="cancelled" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述"><el-input v-model="taskForm.description" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTaskDialog = false">取消</el-button>
        <el-button type="primary" @click="saveTask">保存</el-button>
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
  taskCompletionSignal: Object
})

const emit = defineEmits(['task-started'])

const chapters = ref([])
const outlines = ref([])
const tasks = ref([])
const versions = ref([])
const selectedChapterId = ref(null)
const chapterContent = ref('')
const chapterGenerateInput = ref('')
const previewMode = ref('edit')
const savingContent = ref(false)
const generatingContent = ref(false)
const generatingStoryboard = ref(false)
const reviewingContinuity = ref(false)

const showChapterDialog = ref(false)
const showOutlineDialog = ref(false)
const showVersionDialog = ref(false)
const selectedVersion = ref(null)
const showContinuityDialog = ref(false)
const continuityResult = ref(null)
const showTaskDialog = ref(false)
const currentSourceChapter = ref(null)
const showSourceDialog = ref(false)
const showBindSourceDialog = ref(false)
const sourceSearch = ref('')
const sourceCandidates = ref([])
const editingChapter = ref(null)
const editingOutline = ref(null)
const editingTask = ref(null)

const chapterForm = ref({ sequence: 1, title: '', summary: '', content: '', goal: '', conflict: '', status: 'draft' })
const outlineForm = ref({ scope: 'project', title: '', content: '', chapter_id: null, sort_order: 0 })
const taskForm = ref({ chapter_id: null, title: '', description: '', type: '', status: 'todo', sort_order: 0 })

const selectedChapter = computed(() => chapters.value.find(item => item.id === selectedChapterId.value) || null)
const handledCompletionIds = new Set()

const normalizeId = (value) => (value === null || value === undefined ? null : String(value))
const taskChapterId = (task) => normalizeId(task?.scope_id || task?.result?.chapter_id || task?.input_payload?.chapter_id)

const filteredOutlines = computed(() => {
  if (!selectedChapterId.value) return outlines.value
  return outlines.value.filter(item => item.scope === 'project' || item.chapter_id === selectedChapterId.value)
})

const filteredTasks = computed(() => {
  if (!selectedChapterId.value) return tasks.value
  return tasks.value.filter(item => item.chapter_id === selectedChapterId.value)
})

const statusText = (status) => ({ draft: '草稿', planning: '规划中', storyboarding: '分镜中', done: '完成' }[status] || status)
const taskStatusText = (status) => ({ todo: '待办', doing: '进行中', done: '已完成', blocked: '阻塞', cancelled: '已取消' }[status] || status)
const issueSeverityText = (severity) => ({ low: '低', medium: '中', high: '高' }[severity] || '中')
const issueSeverityType = (severity) => ({ low: 'info', medium: 'warning', high: 'danger' }[severity] || 'warning')

const formatDateTime = (value) => {
  if (!value) return '未知时间'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

const loadData = async () => {
  const [chapterRes, outlineRes, taskRes] = await Promise.all([
    axios.get(`/api/v1/projects/${props.projectId}/chapters`),
    axios.get(`/api/v1/projects/${props.projectId}/outlines`),
    axios.get(`/api/v1/projects/${props.projectId}/chapter-tasks`)
  ])

  chapters.value = chapterRes.data
  outlines.value = outlineRes.data
  tasks.value = taskRes.data

  if (!chapters.value.length) {
    selectedChapterId.value = null
    chapterContent.value = ''
    versions.value = []
    return
  }

  if (!selectedChapterId.value || !chapters.value.some(item => item.id === selectedChapterId.value)) {
    selectedChapterId.value = chapters.value[0].id
  }
}

const loadChapterDetail = async (chapterId) => {
  if (!chapterId) {
    chapterContent.value = ''
    versions.value = []
    return
  }

  const [detailRes, versionsRes] = await Promise.all([
    axios.get(`/api/v1/projects/${props.projectId}/chapters/${chapterId}`),
    axios.get(`/api/v1/projects/${props.projectId}/chapters/${chapterId}/versions`)
  ])

  const detail = detailRes.data
  chapters.value = chapters.value.map(item => (item.id === chapterId ? detail : item))
  chapterContent.value = detail.content || ''
  versions.value = versionsRes.data
  currentSourceChapter.value = null
  if (detail.source_chapter_id) {
    try {
      const sourceRes = await axios.get(`/api/v1/projects/${props.projectId}/source-chapters/${detail.source_chapter_id}`)
      currentSourceChapter.value = sourceRes.data
    } catch (e) {
      console.error('加载关联原文章节失败', e)
    }
  }
}

const selectChapter = async (chapterId) => {
  selectedChapterId.value = chapterId
  await loadChapterDetail(chapterId)
}

const refreshSelectedChapter = async () => {
  if (!selectedChapterId.value) return
  await loadData()
  await loadChapterDetail(selectedChapterId.value)
}

watch(selectedChapterId, (chapterId) => {
  if (!chapterId) {
    chapterContent.value = ''
    versions.value = []
  }
})

watch(() => props.taskCompletionSignal, async (task) => {
  if (!task?.id || handledCompletionIds.has(task.id)) return
  if (task.status !== 'completed') return
  if (!['chapter_content_generation', 'chapter_storyboard'].includes(task.type)) return

  handledCompletionIds.add(task.id)
  const completedChapterId = taskChapterId(task)
  const isCurrentChapter = completedChapterId && completedChapterId === normalizeId(selectedChapterId.value)

  try {
    if (task.type === 'chapter_content_generation') {
      if (isCurrentChapter) {
        await refreshSelectedChapter()
        ElMessage.success('章节正文已自动刷新')
      } else {
        await loadData()
      }
      return
    }

    if (task.type === 'chapter_storyboard') {
      await loadData()
      if (isCurrentChapter) {
        await loadChapterDetail(selectedChapterId.value)
      }
    }
  } catch (error) {
    console.error('任务完成后刷新章节数据失败', error)
  }
}, { deep: true })

const openVersionDetail = (version) => {
  selectedVersion.value = version
  showVersionDialog.value = true
}

const rollbackVersion = async (version) => {
  if (!selectedChapterId.value || !version?.id) return

  try {
    await axios.post(`/api/v1/projects/${props.projectId}/chapters/${selectedChapterId.value}/versions/${version.id}/rollback`)
    ElMessage.success(`已回滚到版本 ${version.version_no}`)
    showVersionDialog.value = false
    selectedVersion.value = null
    await refreshSelectedChapter()
    previewMode.value = 'preview'
  } catch (error) {
    ElMessage.error('回滚失败：' + (error.response?.data?.detail || error.message))
  }
}

const openChapterDialog = (chapter = null) => {
  editingChapter.value = chapter
  chapterForm.value = chapter
    ? { sequence: chapter.sequence, title: chapter.title, summary: chapter.summary || '', content: chapter.content || '', goal: chapter.goal || '', conflict: chapter.conflict || '', status: chapter.status }
    : { sequence: chapters.value.length + 1, title: '', summary: '', content: '', goal: '', conflict: '', status: 'draft' }
  showChapterDialog.value = true
}

const saveChapter = async () => {
  if (!chapterForm.value.title) return ElMessage.warning('请输入章节标题')
  if (editingChapter.value) {
    await axios.put(`/api/v1/projects/${props.projectId}/chapters/${editingChapter.value.id}`, chapterForm.value)
  } else {
    await axios.post(`/api/v1/projects/${props.projectId}/chapters`, chapterForm.value)
  }
  ElMessage.success('章节已保存')
  showChapterDialog.value = false
  await loadData()
  if (selectedChapterId.value) {
    await loadChapterDetail(selectedChapterId.value)
  }
}

const saveChapterContent = async () => {
  if (!selectedChapterId.value) return ElMessage.warning('请先选择章节')

  savingContent.value = true
  try {
    const chapter = selectedChapter.value
    await axios.put(`/api/v1/projects/${props.projectId}/chapters/${selectedChapterId.value}/content`, {
      title: chapter?.title,
      content: chapterContent.value,
      preview_text: chapterContent.value ? chapterContent.value.slice(0, 500) : '',
      change_note: '手动保存'
    })

    ElMessage.success('章节正文已保存')
    await refreshSelectedChapter()
  } catch (error) {
    ElMessage.error('保存失败：' + (error.response?.data?.detail || error.message))
  } finally {
    savingContent.value = false
  }
}

const loadSourceCandidates = async () => {
  const res = await axios.get(`/api/v1/projects/${props.projectId}/source-chapters`, {
    params: { limit: 200, q: sourceSearch.value || undefined }
  })
  sourceCandidates.value = res.data
}

const openBindSourceDialog = async () => {
  showBindSourceDialog.value = true
  await loadSourceCandidates()
}

const bindSourceChapter = async (sourceChapterId) => {
  if (!selectedChapterId.value) return
  await axios.put(`/api/v1/projects/${props.projectId}/chapters/${selectedChapterId.value}`, {
    source_chapter_id: sourceChapterId
  })
  ElMessage.success('已绑定原文章节')
  showBindSourceDialog.value = false
  await refreshSelectedChapter()
}

const generateChapterContent = async () => {
  if (!selectedChapterId.value) return ElMessage.warning('请先选择章节')

  generatingContent.value = true
  try {
    await axios.post(`/api/v1/generate/chapter-content-task/${selectedChapterId.value}`, {
      user_input: chapterGenerateInput.value || undefined,
      save_version: true
    })
    emit('task-started')
    ElMessage.success('章节正文生成任务已启动')
  } catch (error) {
    ElMessage.error('启动章节正文生成失败：' + (error.response?.data?.detail || error.message))
  } finally {
    generatingContent.value = false
  }
}

const reviewChapterContinuity = async () => {
  if (!selectedChapterId.value) return ElMessage.warning('请先选择章节')
  if (!chapterContent.value.trim()) return ElMessage.warning('请先填写或生成章节正文')

  reviewingContinuity.value = true
  try {
    const chapter = selectedChapter.value
    await axios.put(`/api/v1/projects/${props.projectId}/chapters/${selectedChapterId.value}/content`, {
      title: chapter?.title,
      content: chapterContent.value,
      preview_text: chapterContent.value.slice(0, 500),
      change_note: '连续性审查前保存'
    })
    const res = await axios.post(`/api/v1/generate/chapter-continuity/${selectedChapterId.value}`)
    continuityResult.value = res.data
    showContinuityDialog.value = true
    await refreshSelectedChapter()
  } catch (error) {
    ElMessage.error('连续性审查失败：' + (error.response?.data?.detail || error.message))
  } finally {
    reviewingContinuity.value = false
  }
}

const generateChapterStoryboard = async () => {
  if (!selectedChapterId.value) return ElMessage.warning('请先选择章节')

  generatingStoryboard.value = true
  try {
    await axios.post(`/api/v1/generate/chapter-storyboard/${selectedChapterId.value}`, {
      user_input: chapterGenerateInput.value || undefined,
      save_version: false
    })
    emit('task-started')
    ElMessage.success('章节分镜生成任务已启动')
  } catch (error) {
    ElMessage.error('启动章节分镜失败：' + (error.response?.data?.detail || error.message))
  } finally {
    generatingStoryboard.value = false
  }
}

const deleteChapter = async (chapterId) => {
  await axios.delete(`/api/v1/projects/${props.projectId}/chapters/${chapterId}`)
  if (selectedChapterId.value === chapterId) selectedChapterId.value = null
  ElMessage.success('章节已删除')
  await loadData()
  if (selectedChapterId.value) {
    await loadChapterDetail(selectedChapterId.value)
  }
}

const openOutlineDialog = (outline = null) => {
  editingOutline.value = outline
  outlineForm.value = outline
    ? { scope: outline.scope, title: outline.title, content: outline.content, chapter_id: outline.chapter_id, sort_order: outline.sort_order || 0 }
    : { scope: selectedChapterId.value ? 'chapter' : 'project', title: '', content: '', chapter_id: selectedChapterId.value, sort_order: 0 }
  showOutlineDialog.value = true
}

const saveOutline = async () => {
  if (!outlineForm.value.title || !outlineForm.value.content) return ElMessage.warning('请输入大纲标题和内容')
  const payload = { ...outlineForm.value, chapter_id: outlineForm.value.scope === 'chapter' ? outlineForm.value.chapter_id : null }
  if (editingOutline.value) {
    await axios.put(`/api/v1/projects/${props.projectId}/outlines/${editingOutline.value.id}`, payload)
  } else {
    await axios.post(`/api/v1/projects/${props.projectId}/outlines`, payload)
  }
  ElMessage.success('大纲已保存')
  showOutlineDialog.value = false
  await loadData()
}

const deleteOutline = async (outlineId) => {
  await axios.delete(`/api/v1/projects/${props.projectId}/outlines/${outlineId}`)
  ElMessage.success('大纲已删除')
  await loadData()
}

const openTaskDialog = (task = null) => {
  editingTask.value = task
  taskForm.value = task
    ? { chapter_id: task.chapter_id, title: task.title, description: task.description || '', type: task.type || '', status: task.status, sort_order: task.sort_order || 0 }
    : { chapter_id: selectedChapterId.value, title: '', description: '', type: '', status: 'todo', sort_order: 0 }
  showTaskDialog.value = true
}

const saveTask = async () => {
  if (!taskForm.value.title) return ElMessage.warning('请输入任务标题')
  if (editingTask.value) {
    await axios.put(`/api/v1/projects/${props.projectId}/chapter-tasks/${editingTask.value.id}`, taskForm.value)
  } else {
    await axios.post(`/api/v1/projects/${props.projectId}/chapter-tasks`, taskForm.value)
  }
  ElMessage.success('任务已保存')
  showTaskDialog.value = false
  await loadData()
}

const deleteTask = async (taskId) => {
  await axios.delete(`/api/v1/projects/${props.projectId}/chapter-tasks/${taskId}`)
  ElMessage.success('任务已删除')
  await loadData()
}

onMounted(async () => {
  await loadData()
  if (selectedChapterId.value) {
    await loadChapterDetail(selectedChapterId.value)
  }
})
</script>

<style scoped>
.chapter-tab {
  padding-bottom: 40px;
}

.panel-card {
  border: 1px solid #333;
  background-color: #1e1e1e;
}

.chapter-list-card {
  height: 100%;
}

.card-header,
.header-actions,
.section-header,
.detail-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.header-actions {
  flex-wrap: wrap;
}

.list,
.cards-list,
.version-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.list-item,
.version-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid #333;
  border-radius: 6px;
  cursor: pointer;
  background: #252525;
}

.list-item.active {
  border-color: #409eff;
}

.item-main,
.version-main {
  min-width: 0;
  flex: 1;
}

.item-title,
.version-title {
  color: #e5eaf3;
  font-weight: 600;
}

.item-desc,
.chapter-summary,
.version-note,
.section-subtext {
  color: #a3a6ad;
}

.item-desc,
.version-note {
  font-size: 0.85em;
  margin-top: 4px;
}

.item-actions {
  display: flex;
  flex-shrink: 0;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.word-count,
.version-meta {
  color: #909399;
  font-size: 12px;
}

.detail-block {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-block + .detail-block {
  margin-top: 24px;
}

.chapter-title {
  margin: 0;
  color: #e5eaf3;
}

.chapter-summary {
  margin: 8px 0 0;
  line-height: 1.6;
}

.source-block {
  border: 1px solid #2f5f46;
  background: rgba(38, 120, 83, 0.08);
  border-radius: 8px;
  padding: 14px;
}

.source-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #cfd3dc;
}

.source-title {
  font-weight: 700;
  color: #67C23A;
}

.source-summary {
  color: #a8abb2;
  line-height: 1.6;
}

.source-meta {
  color: #909399;
  font-size: 0.9rem;
}

.source-preview :deep(.el-textarea__inner) {
  font-family: inherit;
  line-height: 1.7;
}

.source-bind-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.source-bind-actions .el-input {
  max-width: 360px;
}

.chapter-detail-grid,
.mini-info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.meta-card,
.mini-info-item,
.content-card {
  border: 1px solid #333;
  background: #252525;
}

.meta-card,
.mini-info-item {
  padding: 12px;
  border-radius: 8px;
}

.meta-label,
.mini-label {
  display: block;
  color: #909399;
  font-size: 12px;
  margin-bottom: 6px;
}

.meta-value,
.mini-value,
.content-text {
  color: #ddd;
  white-space: pre-wrap;
  line-height: 1.6;
}

.content-preview {
  min-height: 360px;
  padding: 16px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #252525;
  color: #ddd;
  white-space: pre-wrap;
  line-height: 1.8;
}

.w-full {
  width: 100%;
}

.mb-4 {
  margin-bottom: 24px;
}

.ml-2 {
  margin-left: 8px;
}

.version-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.version-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.version-content {
  max-height: 520px;
  overflow-y: auto;
  padding: 16px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #252525;
  color: #ddd;
  white-space: pre-wrap;
  line-height: 1.8;
}

.continuity-result,
.continuity-issues {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.continuity-issues {
  margin-top: 16px;
}

.continuity-issue {
  border: 1px solid #333;
  background: #252525;
}

.issue-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.issue-category {
  color: #909399;
}

.issue-message {
  color: #eee;
  margin: 8px 0;
}

.issue-detail {
  color: #bbb;
  margin: 6px 0 0;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .chapter-detail-grid,
  .mini-info-grid {
    grid-template-columns: 1fr;
  }

  .detail-title-row,
  .card-header,
  .section-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .list-item,
  .version-item {
    flex-direction: column;
  }
}
</style>
