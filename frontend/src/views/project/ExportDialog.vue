<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="emit('update:visible', $event)"
    title="导出漫画"
    width="30%"
  >
    <span>确认导出当前项目漫画？</span>
    <div class="mt-2">
      <el-checkbox v-model="splitImages">自动拆分四格分镜（1:1 切分）</el-checkbox>
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="emit('update:visible', false)">取消</el-button>
        <el-button type="primary" @click="confirmExport" :loading="loading">确认导出</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  projectId: [String, Number]
})

const emit = defineEmits(['update:visible'])

const splitImages = ref(false)
const loading = ref(false)

const confirmExport = async () => {
  loading.value = true
  try {
    const res = await axios.get(`/api/v1/export/${props.projectId}`, {
      params: { split_images: splitImages.value }
    })
    window.open(res.data.download_url, '_blank')
    emit('update:visible', false)
    ElMessage.success('导出下载已开始')
  } catch (error) {
    ElMessage.error('导出失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.mt-2 { margin-top: 10px; }
</style>