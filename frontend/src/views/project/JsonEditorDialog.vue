<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="emit('update:visible', $event)"
    :title="title || '编辑 JSON'"
    width="60%"
    :close-on-click-modal="false"
  >
    <div class="json-editor-container">
      <el-input
        type="textarea"
        :rows="20"
        v-model="localContent" 
        class="json-textarea"
        spellcheck="false"
      />
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="emit('update:visible', false)">取消</el-button>
        <el-button type="primary" @click="handleSave">保存修改</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  content: String, // Expecting stringified JSON
  title: String
})

const emit = defineEmits(['update:visible', 'save'])

const localContent = ref('')

watch(() => props.visible, (val) => {
  if (val) {
    localContent.value = props.content || ''
  }
})

const handleSave = () => {
  try {
    // Validate JSON
    const parsed = JSON.parse(localContent.value)
    emit('save', JSON.stringify(parsed, null, 2)) // Format it nicely
    emit('update:visible', false)
  } catch (e) {
    ElMessage.error('JSON 格式无效：' + e.message)
  }
}
</script>

<style scoped>
.json-textarea {
  font-family: monospace;
}
</style>