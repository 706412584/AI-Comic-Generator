<template>
  <div class="header">
    <h2>{{ title }}</h2>
    <div class="actions">
      <el-button :icon="ChatDotRound" @click="emit('open-assistant')">创作助手</el-button>
      <el-button type="success" @click="emit('export')">导出漫画</el-button>
    </div>
  </div>
</template>

<script setup>
import { ChatDotRound } from '@element-plus/icons-vue'

defineProps({
  title: String
})
const emit = defineEmits(['export', 'open-assistant'])
</script>

<style scoped>
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}
.actions {
    display: flex;
    gap: 10px;
}
</style>
