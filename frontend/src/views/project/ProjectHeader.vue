<template>
  <div class="header">
    <div class="title-area">
      <el-button link :icon="ArrowLeft" class="back-btn" @click="router.push('/')">返回</el-button>
      <span class="divider"></span>
      <h2 class="title" :title="title">{{ title }}</h2>
    </div>
    <div class="actions">
      <el-button :icon="ChatDotRound" @click="emit('open-assistant')">创作助手</el-button>
      <el-button type="primary" :icon="Download" @click="emit('export')">导出漫画</el-button>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { ArrowLeft, ChatDotRound, Download } from '@element-plus/icons-vue'

defineProps({
  title: String
})
const emit = defineEmits(['export', 'open-assistant'])
const router = useRouter()
</script>

<style scoped>
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
}
.title-area {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
}
.back-btn {
    flex-shrink: 0;
}
.divider {
    width: 1px;
    height: 18px;
    background: var(--app-border-strong);
    flex-shrink: 0;
}
.title {
    margin: 0;
    font-size: 18px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.actions {
    display: flex;
    gap: 10px;
    flex-shrink: 0;
}
</style>
