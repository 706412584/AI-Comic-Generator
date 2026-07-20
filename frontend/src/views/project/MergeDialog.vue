<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="emit('update:visible', $event)"
    title="合并角色"
    width="40%"
    @open="resetForm"
  >
    <div class="merge-container">
      <p class="mb-2">将重复角色合并到目标角色。被合并的角色会被删除，分镜中的角色名称会自动更新为目标角色。</p>
      
      <el-form label-width="120px">
        <el-form-item label="保留角色">
          <el-select v-model="mergeTargetId" placeholder="选择要保留的角色（目标）" style="width: 100%">
            <el-option v-for="c in characters" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="合并来源">
          <el-select v-model="mergeSourceIds" multiple placeholder="选择要合并的角色（将被删除）" style="width: 100%">
            <el-option 
              v-for="c in characters" 
              :key="c.id" 
              :label="c.name" 
              :value="c.id" 
              :disabled="c.id === mergeTargetId"
            />
          </el-select>
        </el-form-item>
      </el-form>
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="emit('update:visible', false)">取消</el-button>
        <el-button type="primary" @click="confirmMerge" :disabled="!mergeTargetId || !mergeSourceIds.length" :loading="loading">确认合并</el-button>
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
  characters: Array,
  projectId: [String, Number]
})

const emit = defineEmits(['update:visible', 'merged'])

const mergeTargetId = ref(null)
const mergeSourceIds = ref([])
const loading = ref(false)

const resetForm = () => {
  mergeTargetId.value = null
  mergeSourceIds.value = []
}

const confirmMerge = async () => {
  loading.value = true
  try {
    await axios.post(`/api/v1/projects/${props.projectId}/characters/merge`, {
      target_char_id: mergeTargetId.value,
      source_char_ids: mergeSourceIds.value
    })
    ElMessage.success('合并成功')
    emit('update:visible', false)
    emit('merged', { targetId: mergeTargetId.value, sourceIds: mergeSourceIds.value })
  } catch (e) {
    ElMessage.error('合并失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.mb-2 { margin-bottom: 10px; }
</style>