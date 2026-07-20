<template>
  <div class="setting-tab">
    <el-row :gutter="20">
      <el-col :xs="24" :md="8">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-header">
              <span>设定分类</span>
              <el-button type="primary" size="small" @click="openCategoryDialog()">新增分类</el-button>
            </div>
          </template>

          <el-empty v-if="!categories.length" description="暂无分类" />
          <div v-else class="list">
            <div
              v-for="category in categories"
              :key="category.id"
              class="list-item"
              :class="{ active: selectedCategoryId === category.id }"
              @click="selectedCategoryId = category.id"
            >
              <div>
                <div class="item-title">{{ category.name }}</div>
                <div class="item-desc">{{ category.description || '暂无描述' }}</div>
              </div>
              <div class="item-actions">
                <el-button size="small" link type="primary" @click.stop="openCategoryDialog(category)">编辑</el-button>
                <el-popconfirm title="确定删除这个分类吗？" @confirm="deleteCategory(category.id)">
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
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="card-header">
              <span>设定项</span>
              <el-button type="primary" size="small" @click="openSettingDialog()">新增设定</el-button>
            </div>
          </template>

          <el-empty v-if="!filteredSettings.length" description="暂无设定项" />
          <div v-else class="setting-list">
            <el-card v-for="setting in filteredSettings" :key="setting.id" shadow="hover" class="setting-card">
              <template #header>
                <div class="card-header">
                  <div>
                    <span class="item-title">{{ setting.title }}</span>
                    <el-tag size="small" class="ml-2">重要度 {{ setting.importance }}</el-tag>
                    <el-tag v-if="!setting.is_active" size="small" type="info" class="ml-2">停用</el-tag>
                  </div>
                  <div>
                    <el-button size="small" link type="primary" @click="openSettingDialog(setting)">编辑</el-button>
                    <el-popconfirm title="确定删除这个设定吗？" @confirm="deleteSetting(setting.id)">
                      <template #reference>
                        <el-button size="small" link type="danger">删除</el-button>
                      </template>
                    </el-popconfirm>
                  </div>
                </div>
              </template>
              <p class="setting-content">{{ setting.content }}</p>
              <div v-if="setting.tags?.length" class="tags">
                <el-tag v-for="tag in setting.tags" :key="tag" size="small" effect="dark">{{ tag }}</el-tag>
              </div>
            </el-card>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="showCategoryDialog" :title="editingCategory ? '编辑分类' : '新增分类'" width="420px">
      <el-form :model="categoryForm" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="categoryForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="categoryForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="categoryForm.sort_order" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCategoryDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCategory">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showSettingDialog" :title="editingSetting ? '编辑设定' : '新增设定'" width="640px">
      <el-form :model="settingForm" label-width="90px">
        <el-form-item label="分类">
          <el-select v-model="settingForm.category_id" clearable placeholder="未分类" class="w-full">
            <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="settingForm.title" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="settingForm.content" type="textarea" :rows="6" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="tagsText" placeholder="用逗号分隔，例如：境界,战力" />
        </el-form-item>
        <el-form-item label="重要度">
          <el-input-number v-model="settingForm.importance" :min="1" :max="5" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="settingForm.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSettingDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSetting">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const props = defineProps({
  projectId: [String, Number]
})

const categories = ref([])
const settings = ref([])
const selectedCategoryId = ref(null)
const showCategoryDialog = ref(false)
const showSettingDialog = ref(false)
const editingCategory = ref(null)
const editingSetting = ref(null)
const tagsText = ref('')

const categoryForm = ref({ name: '', description: '', sort_order: 0 })
const settingForm = ref({ category_id: null, title: '', content: '', tags: [], importance: 3, is_active: true })

const filteredSettings = computed(() => {
  if (!selectedCategoryId.value) return settings.value
  return settings.value.filter(item => item.category_id === selectedCategoryId.value)
})

const loadData = async () => {
  const [categoryRes, settingRes] = await Promise.all([
    axios.get(`/api/v1/projects/${props.projectId}/setting-categories`),
    axios.get(`/api/v1/projects/${props.projectId}/settings`)
  ])
  categories.value = categoryRes.data
  settings.value = settingRes.data
}

const openCategoryDialog = (category = null) => {
  editingCategory.value = category
  categoryForm.value = category
    ? { name: category.name, description: category.description || '', sort_order: category.sort_order || 0 }
    : { name: '', description: '', sort_order: 0 }
  showCategoryDialog.value = true
}

const saveCategory = async () => {
  if (!categoryForm.value.name) return ElMessage.warning('请输入分类名称')
  if (editingCategory.value) {
    await axios.put(`/api/v1/projects/${props.projectId}/setting-categories/${editingCategory.value.id}`, categoryForm.value)
  } else {
    await axios.post(`/api/v1/projects/${props.projectId}/setting-categories`, categoryForm.value)
  }
  ElMessage.success('分类已保存')
  showCategoryDialog.value = false
  await loadData()
}

const deleteCategory = async (categoryId) => {
  await axios.delete(`/api/v1/projects/${props.projectId}/setting-categories/${categoryId}`)
  if (selectedCategoryId.value === categoryId) selectedCategoryId.value = null
  ElMessage.success('分类已删除')
  await loadData()
}

const openSettingDialog = (setting = null) => {
  editingSetting.value = setting
  settingForm.value = setting
    ? {
        category_id: setting.category_id,
        title: setting.title,
        content: setting.content,
        tags: setting.tags || [],
        importance: setting.importance,
        is_active: setting.is_active
      }
    : { category_id: selectedCategoryId.value, title: '', content: '', tags: [], importance: 3, is_active: true }
  tagsText.value = settingForm.value.tags.join(',')
  showSettingDialog.value = true
}

const saveSetting = async () => {
  if (!settingForm.value.title || !settingForm.value.content) return ElMessage.warning('请输入标题和内容')
  const payload = {
    ...settingForm.value,
    tags: tagsText.value.split(',').map(tag => tag.trim()).filter(Boolean)
  }
  if (editingSetting.value) {
    await axios.put(`/api/v1/projects/${props.projectId}/settings/${editingSetting.value.id}`, payload)
  } else {
    await axios.post(`/api/v1/projects/${props.projectId}/settings`, payload)
  }
  ElMessage.success('设定已保存')
  showSettingDialog.value = false
  await loadData()
}

const deleteSetting = async (settingId) => {
  await axios.delete(`/api/v1/projects/${props.projectId}/settings/${settingId}`)
  ElMessage.success('设定已删除')
  await loadData()
}

onMounted(loadData)
</script>

<style scoped>
.setting-tab {
  padding-bottom: 40px;
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
.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.list-item {
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
  border-color: #409EFF;
}
.item-title {
  color: #E5EAF3;
  font-weight: 600;
}
.item-desc {
  color: #888;
  font-size: 0.85em;
  margin-top: 4px;
}
.item-actions {
  display: flex;
  flex-shrink: 0;
}
.setting-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.setting-card {
  border: 1px solid #333;
  background: #252525;
}
.setting-content {
  color: #ddd;
  white-space: pre-wrap;
  line-height: 1.6;
}
.tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.w-full {
  width: 100%;
}
.ml-2 {
  margin-left: 8px;
}
</style>
