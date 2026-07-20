<template>
  <div class="character-tab">
    <div class="mb-2 flex-row-between">
      <div class="left-actions">
        <el-popconfirm
            title="这将重新生成所有角色图片并覆盖现有图片，是否继续？"
            confirm-button-text="确认覆盖"
            cancel-button-text="取消"
            @confirm="generateAllCharacters"
        >
          <template #reference>
            <el-button type="primary" size="large" :disabled="!project.characters.length || isTaskRunning">
              绘制全部角色（覆盖）
            </el-button>
          </template>
        </el-popconfirm>

        <el-button @click="emit('open-merge-dialog')" size="large" :disabled="project.characters.length < 2">
          合并角色
        </el-button>
      </div>
    </div>
    
    <el-container class="char-studio-container">
      <el-aside width="250px" class="char-list-aside">
        <el-menu 
          :default-active="activeCharId" 
          @select="handleCharSelect"
          background-color="#1e1e1e"
          text-color="#fff"
          active-text-color="#409EFF"
          class="char-menu"
        >
          <el-menu-item v-for="char in project.characters" :key="char.id" :index="String(char.id)">
            <span class="text-truncate">{{ char.name }}</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      
      <el-main class="char-main">
        <div v-if="selectedChar" class="char-detail">
          <div class="char-header">
            <h2>{{ selectedChar.name }}</h2>
            <div class="header-actions">
              <el-popconfirm title="确定要删除这个角色吗？" @confirm="deleteCharacter(selectedChar.id)">
                <template #reference>
                  <el-button type="danger" plain>删除</el-button>
                </template>
              </el-popconfirm>
              <el-button @click="emit('open-history', 'character', selectedChar.id)">历史</el-button>
              <el-button type="primary" @click="generateCharacter(selectedChar.id)" :loading="loading">
                绘制 / 重绘（后台）
              </el-button>
            </div>
          </div>
          
          <el-row :gutter="24">
            <!-- Left: Attributes -->
            <el-col :xs="24" :sm="10" :md="8" :lg="8">
              <div class="info-card">
                <div class="info-header">
                  <h4>角色属性</h4>
                  <el-button size="small" type="primary" link @click="openJsonEditor">编辑 JSON</el-button>
                </div>
                
                <el-scrollbar max-height="600px">
                  <div v-if="Object.keys(displayData).length" class="attributes-list">
                    <div v-for="(value, key) in displayData" :key="key" class="attr-wrapper">
                      
                      <!-- Complex Data (Array or Object) -->
                      <div v-if="isComplex(value)" class="complex-attr">
                          <div class="complex-label">{{ formatKey(key) }}</div>
                          
                          <!-- Array -->
                          <div v-if="Array.isArray(value)" class="array-list">
                              <div v-for="(item, idx) in value" :key="idx" class="array-item">
                                  <template v-if="isComplex(item)">
                                      <div v-for="(v, k) in item" :key="k" class="nested-item">
                                          <span class="nested-label">{{ formatKey(k) }}:</span>
                                          <span class="nested-value">{{ v }}</span>
                                      </div>
                                  </template>
                                  <template v-else>{{ item }}</template>
                              </div>
                          </div>
                          
                          <!-- Object -->
                          <div v-else class="object-grid">
                               <div v-for="(v, k) in value" :key="k" class="grid-item">
                                  <span class="nested-label">{{ formatKey(k) }}:</span>
                                  <span class="nested-value">{{ v }}</span>
                               </div>
                          </div>
                      </div>

                      <!-- Simple Data -->
                      <div v-else class="attr-item">
                        <span class="attr-label">{{ formatKey(key) }}:</span>
                        <span class="attr-value">{{ value }}</span>
                      </div>

                    </div>
                  </div>
                  <div v-else class="text-gray p-2">
                    未找到结构化属性。点击编辑 JSON 添加详情。
                  </div>
                  
                  <div v-if="selectedChar.data?.description" class="mt-4">
                     <span class="attr-label">描述：</span>
                     <p class="desc-text">{{ selectedChar.data.description }}</p>
                  </div>
                </el-scrollbar>
              </div>

              <div class="info-card outfit-card mt-4">
                <div class="info-header">
                  <h4>服饰方案</h4>
                  <el-button size="small" type="primary" link @click="openOutfitDialog()">新增服饰</el-button>
                </div>

                <div v-if="outfits.length" class="outfit-list">
                  <div v-for="outfit in outfits" :key="outfit.id" class="outfit-item">
                    <div>
                      <div class="outfit-title">
                        {{ outfit.name }}
                        <el-tag v-if="outfit.is_default" size="small" type="success" class="ml-2">默认</el-tag>
                      </div>
                      <div class="outfit-desc">{{ outfit.description }}</div>
                      <div v-if="outfit.state" class="outfit-meta">状态：{{ outfit.state }}</div>
                    </div>
                    <div class="outfit-actions">
                      <el-button size="small" link type="primary" @click="openOutfitDialog(outfit)">编辑</el-button>
                      <el-popconfirm title="确定删除这个服饰方案吗？" @confirm="deleteOutfit(outfit.id)">
                        <template #reference>
                          <el-button size="small" link type="danger">删除</el-button>
                        </template>
                      </el-popconfirm>
                    </div>
                  </div>
                </div>
                <div v-else class="text-gray p-2">暂无服饰方案。可先添加默认服饰用于后续图片生成。</div>
              </div>
            </el-col>

            <!-- Right: Preview -->
            <el-col :xs="24" :sm="14" :md="16" :lg="16">
              <div class="preview-card">
                <h4>角色预览</h4>
                <div class="image-wrapper">
                  <el-image 
                    v-if="selectedChar.image_url" 
                    :src="`${selectedChar.image_url}?v=${imageVersion}`" 
                    fit="contain" 
                    class="image-preview"
                    :preview-src-list="[`${selectedChar.image_url}?v=${imageVersion}`]"
                  >
                    <template #error>
                      <div class="image-slot">
                        <el-icon><icon-picture /></el-icon>
                      </div>
                    </template>
                  </el-image>
                  <div v-else class="no-image">
                    <span>尚未生成图片</span>
                    <span class="sub-text">点击“绘制 / 重绘”生成</span>
                  </div>
                </div>

                <div v-if="selectedChar.image_url" class="image-actions mt-2" style="text-align: center;">
                    <a :href="selectedChar.image_url" :download="`${selectedChar.name}.png`" target="_blank">
                      <el-button size="small" type="info" plain>下载图片</el-button>
                    </a>
                </div>
              </div>
            </el-col>
          </el-row>
        </div>
        <div v-else class="empty-state">
          <el-empty description="请选择角色查看详情" />
        </div>
      </el-main>
    </el-container>

    <JsonEditorDialog
      v-model:visible="showJsonEditor"
      :content="characterEditor"
      :title="`编辑 ${selectedChar?.name || 'Character'}`"
      @save="handleJsonSave"
    />

    <el-dialog v-model="showOutfitDialog" :title="editingOutfit ? '编辑服饰' : '新增服饰'" width="560px">
      <el-form :model="outfitForm" label-width="90px">
        <el-form-item label="名称"><el-input v-model="outfitForm.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="outfitForm.description" type="textarea" :rows="4" /></el-form-item>
        <el-form-item label="场景"><el-input v-model="outfitForm.scene" placeholder="例如：日常、战斗、宴会" /></el-form-item>
        <el-form-item label="颜色"><el-input v-model="outfitForm.colors" /></el-form-item>
        <el-form-item label="材质"><el-input v-model="outfitForm.materials" /></el-form-item>
        <el-form-item label="配饰"><el-input v-model="outfitForm.accessories" /></el-form-item>
        <el-form-item label="状态"><el-input v-model="outfitForm.state" placeholder="例如：干净、破损、受伤" /></el-form-item>
        <el-form-item label="参考图"><el-input v-model="outfitForm.reference_image_url" placeholder="图片 URL" /></el-form-item>
        <el-form-item label="默认服饰"><el-switch v-model="outfitForm.is_default" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showOutfitDialog = false">取消</el-button>
        <el-button type="primary" @click="saveOutfit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Picture as IconPicture } from '@element-plus/icons-vue'
import JsonEditorDialog from './JsonEditorDialog.vue'

const props = defineProps({
  project: Object,
  projectId: [String, Number],
  isTaskRunning: Boolean,
  imageVersion: Number
})

const emit = defineEmits(['task-started', 'refresh-project', 'open-merge-dialog', 'open-history'])

const activeCharId = ref('')
const characterEditor = ref('')
const loading = ref(false)
const showJsonEditor = ref(false)
const outfits = ref([])
const showOutfitDialog = ref(false)
const editingOutfit = ref(null)
const outfitForm = ref({
  name: '',
  description: '',
  scene: '',
  colors: '',
  materials: '',
  accessories: '',
  state: '',
  reference_image_url: '',
  is_default: false
})

const selectedChar = computed(() => {
  if (!activeCharId.value) return null
  return props.project.characters.find(c => String(c.id) === activeCharId.value)
})

const displayData = computed(() => {
  if (!selectedChar.value || !selectedChar.value.data) return {}
  const data = selectedChar.value.data
  const ignoredKeys = ['description', 'id', 'name', 'image_url', 'created_at']
  const result = {}
  for (const key in data) {
    if (ignoredKeys.includes(key)) continue
    if (data[key] !== null && data[key] !== undefined) {
        result[key] = data[key]
    }
  }
  return result
})

const isComplex = (val) => {
    return typeof val === 'object' && val !== null
}

watch(() => props.project.characters, (newChars) => {
  if (newChars && newChars.length > 0 && !activeCharId.value) {
    activeCharId.value = String(newChars[0].id)
  }
}, { immediate: true })

watch(selectedChar, (newChar) => {
  if (newChar) {
    characterEditor.value = JSON.stringify(newChar.data, null, 2)
    loadOutfits()
  } else {
    characterEditor.value = ''
    outfits.value = []
  }
})

const handleCharSelect = (index) => {
  activeCharId.value = index
}

const formatKey = (key) => {
  // Convert snake_case or camelCase to Title Case
  return key.replace(/([A-Z])/g, ' $1')
            .replace(/^./, str => str.toUpperCase())
            .replace(/_/g, ' ')
}

const loadOutfits = async () => {
  if (!selectedChar.value) return
  try {
    const res = await axios.get(`/api/v1/projects/${props.projectId}/characters/${selectedChar.value.id}/outfits`)
    outfits.value = res.data
  } catch (e) {
    ElMessage.error('加载服饰失败')
  }
}

const openJsonEditor = () => {
  if (!selectedChar.value) return
  // Ensure editor has latest data
  characterEditor.value = JSON.stringify(selectedChar.value.data, null, 2)
  showJsonEditor.value = true
}

const handleJsonSave = async (newContent) => {
  characterEditor.value = newContent
  await updateCharacter(selectedChar.value.id)
}

const updateCharacter = async (charId) => {
  try {
    const data = JSON.parse(characterEditor.value)
    await axios.put(`/api/v1/projects/${props.projectId}/characters/${charId}`, data)
    ElMessage.success('角色设定已保存')
    emit('refresh-project')
  } catch (e) {
    ElMessage.error('JSON 格式错误或保存失败：' + e.message)
  }
}

const openOutfitDialog = (outfit = null) => {
  editingOutfit.value = outfit
  outfitForm.value = outfit
    ? {
        name: outfit.name,
        description: outfit.description,
        scene: outfit.scene || '',
        colors: outfit.colors || '',
        materials: outfit.materials || '',
        accessories: outfit.accessories || '',
        state: outfit.state || '',
        reference_image_url: outfit.reference_image_url || '',
        is_default: outfit.is_default
      }
    : {
        name: '',
        description: '',
        scene: '',
        colors: '',
        materials: '',
        accessories: '',
        state: '',
        reference_image_url: '',
        is_default: false
      }
  showOutfitDialog.value = true
}

const saveOutfit = async () => {
  if (!selectedChar.value) return
  if (!outfitForm.value.name || !outfitForm.value.description) return ElMessage.warning('请输入服饰名称和描述')
  if (editingOutfit.value) {
    await axios.put(`/api/v1/projects/${props.projectId}/characters/${selectedChar.value.id}/outfits/${editingOutfit.value.id}`, outfitForm.value)
  } else {
    await axios.post(`/api/v1/projects/${props.projectId}/characters/${selectedChar.value.id}/outfits`, outfitForm.value)
  }
  ElMessage.success('服饰已保存')
  showOutfitDialog.value = false
  await loadOutfits()
  emit('refresh-project')
}

const deleteOutfit = async (outfitId) => {
  if (!selectedChar.value) return
  await axios.delete(`/api/v1/projects/${props.projectId}/characters/${selectedChar.value.id}/outfits/${outfitId}`)
  ElMessage.success('服饰已删除')
  await loadOutfits()
  emit('refresh-project')
}

const generateCharacter = async (charId) => {
  try {
    await axios.post(`/api/v1/generate/character/${charId}`)
    emit('task-started')
    ElMessage.info('角色绘制任务已在后台启动...')
  } catch (error) {
    console.error(error)
    ElMessage.error('生成失败：' + (error.response?.data?.detail || error.message))
  }
}

const generateAllCharacters = async () => {
  try {
    await axios.post(`/api/v1/generate/all-characters/${props.projectId}`)
    emit('task-started')
    ElMessage.info('批量角色绘制任务已在后台启动...')
  } catch (error) {
    ElMessage.error('启动任务失败：' + (error.response?.data?.detail || error.message))
  }
}

const deleteCharacter = async (charId) => {
  try {
    await axios.delete(`/api/v1/projects/${props.projectId}/characters/${charId}`)
    ElMessage.success('角色已删除')
    if (activeCharId.value === String(charId)) {
      activeCharId.value = ''
    }
    emit('refresh-project')
  } catch (e) {
    ElMessage.error('删除 failed')
  }
}
</script>

<style scoped>
.flex-row-between {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.left-actions {
    display: flex;
    gap: 12px;
}
.char-studio-container {
    height: calc(100vh - 200px); /* Dynamic height based on viewport */
    min-height: 600px;
    border: 1px solid #333;
    background: #1e1e1e;
    border-radius: 8px;
    overflow: hidden;
}
.char-list-aside {
    background-color: #1a1a1a;
    border-right: 1px solid #333;
}
.char-menu {
    border-right: none;
    background-color: transparent;
}
.char-main {
    padding: 24px;
    overflow-y: auto;
}
.char-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid #333;
}
.header-actions {
    display: flex;
    gap: 12px;
}
.info-card, .preview-card {
    background: #252525;
    border-radius: 8px;
    padding: 20px;
    height: 100%;
    box-shadow: 0 4px 6px rgba(0,0,0,0.2);
}
.info-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
}
.info-header h4, .preview-card h4 {
    margin: 0;
    color: #eee;
    font-size: 1.1rem;
}
.attributes-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.attr-item {
    display: flex;
    justify-content: space-between;
    border-bottom: 1px solid #333;
    padding-bottom: 8px;
}
.attr-label {
    color: #909399;
    font-weight: 500;
}
.attr-value {
    color: #E5EAF3;
    text-align: right;
    max-width: 60%;
    white-space: pre-wrap;
    word-break: break-word;
}
.desc-text {
    color: #ccc;
    line-height: 1.6;
    margin-top: 8px;
    font-size: 0.95rem;
}
.image-wrapper {
    margin-top: 16px;
    width: 100%;
    /* Flexible height container */
    min-height: 400px;
    display: flex;
    justify-content: center;
    background: #1a1a1a;
    border-radius: 4px;
    padding: 10px;
}
.image-preview {
    width: 100%;
    height: auto; /* Allow height to grow */
    display: block;
}
.no-image {
    width: 100%;
    height: 400px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    background: #2a2a2a;
    color: #666;
    border-radius: 4px;
    gap: 10px;
}
.sub-text {
    font-size: 0.8rem;
    color: #555;
}
.text-truncate {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
}
.mb-2 { margin-bottom: 16px; }
.mt-4 { margin-top: 24px; }

/* Complex Attributes Styling */
.complex-attr {
    margin-bottom: 16px;
    background: #2a2a2a;
    border-radius: 6px;
    padding: 10px;
}
.complex-label {
    color: #409EFF;
    font-weight: 600;
    margin-bottom: 8px;
    font-size: 0.95rem;
    border-bottom: 1px solid #333;
    padding-bottom: 4px;
}
.array-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.array-item {
    background: #333;
    padding: 8px;
    border-radius: 4px;
    font-size: 0.9em;
}
.object-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 6px;
}
.nested-item {
    margin-bottom: 4px;
}
.nested-label {
    color: #bbb;
    font-weight: 500;
    margin-right: 4px;
}
.nested-value {
    color: #eee;
}
.outfit-card {
    height: auto;
}
.outfit-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.outfit-item {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 10px;
    border: 1px solid #333;
    border-radius: 6px;
    background: #2a2a2a;
}
.outfit-title {
    color: #E5EAF3;
    font-weight: 600;
}
.outfit-desc {
    color: #ccc;
    margin-top: 4px;
    white-space: pre-wrap;
}
.outfit-meta {
    color: #888;
    font-size: 0.85em;
    margin-top: 4px;
}
.outfit-actions {
    display: flex;
    flex-shrink: 0;
}
.p-2 { padding: 8px; }
.ml-2 { margin-left: 8px; }
</style>