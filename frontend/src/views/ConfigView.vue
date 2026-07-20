<template>
  <div class="config-view">
    <div class="header">
      <h2>模型配置</h2>
      <el-button type="primary" @click="openDialog()">新增配置</el-button>
    </div>

    <el-table :data="configs" style="width: 100%">
      <el-table-column prop="provider" label="供应商" />
      <el-table-column prop="model_name" label="模型名称" />
      <el-table-column prop="model_type" label="类型">
        <template #default="scope">
          {{ scope.row.model_type === 'text' ? '文本' : '图片' }}
        </template>
      </el-table-column>
      <el-table-column prop="is_active" label="启用">
        <template #default="scope">
          <el-tag :type="scope.row.is_active ? 'success' : 'info'">{{ scope.row.is_active ? '是' : '否' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作">
        <template #default="scope">
          <el-button size="small" @click="openDialog(scope.row)">编辑</el-button>
          <el-button size="small" type="danger" @click="deleteConfig(scope.row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑配置' : '新增配置'">
      <el-form :model="form" label-width="120px">
        <el-form-item label="供应商">
          <el-select v-model="form.provider" placeholder="请选择供应商">
            <el-option label="Google" value="google" />
            <el-option label="OpenAI 兼容" value="openai_compatible" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="form.model_name" placeholder="例如：gpt-5.5 / gpt-image-1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.model_type">
            <el-option label="文本" value="text" />
            <el-option label="图片" value="image" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL">
            <el-input v-model="form.base_url" placeholder="可选，例如：https://example.com/v1" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const configs = ref([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const form = ref({
  provider: 'openai_compatible',
  model_name: '',
  api_key: '',
  model_type: 'text',
  base_url: '',
  is_active: true
})

const fetchConfigs = async () => {
  try {
    const res = await axios.get('/api/v1/configs/')
    configs.value = res.data
  } catch (error) {
    ElMessage.error('获取配置失败')
  }
}

const openDialog = (row = null) => {
  if (row) {
    isEdit.value = true
    form.value = { ...row }
  } else {
    isEdit.value = false
    form.value = {
      provider: 'openai_compatible',
      model_name: '',
      api_key: '',
      model_type: 'text',
      base_url: '',
      is_active: true
    }
  }
  dialogVisible.value = true
}

const saveConfig = async () => {
  try {
    if (isEdit.value) {
      await axios.put(`/api/v1/configs/${form.value.id}`, form.value)
    } else {
      await axios.post('/api/v1/configs/', form.value)
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    fetchConfigs()
  } catch (error) {
    ElMessage.error('保存配置失败')
  }
}

const deleteConfig = async (id) => {
  try {
    await axios.delete(`/api/v1/configs/${id}`)
    ElMessage.success('删除成功')
    fetchConfigs()
  } catch (error) {
    ElMessage.error('删除配置失败')
  }
}

onMounted(fetchConfigs)
</script>

<style scoped>
.config-view {
    padding: 20px;
}
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}
</style>
