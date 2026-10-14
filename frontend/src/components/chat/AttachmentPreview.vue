<template>
  <div v-if="attachments.length" class="attachment-list">
    <div v-for="file in attachments" :key="file.id || file.name" class="attachment-item">
      <div class="attachment-icon">
        <el-icon><Paperclip /></el-icon>
      </div>
      <div class="attachment-content">
        <div class="attachment-title">
          <span class="attachment-name">{{ file.name }}</span>
          <span class="attachment-meta">
            {{ formatSize(file.size) }} · {{ file.mime || "未知类型" }}
          </span>
        </div>
        <p v-if="file.extracted_text" class="attachment-preview">
          {{ truncate(file.extracted_text) }}
        </p>
        <p v-if="file.note || file.truncated" class="attachment-preview">
          {{ file.note || "正文已截断，仅发送前 8000 字符" }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Paperclip } from "@element-plus/icons-vue";
import { computed } from "vue";

const props = defineProps({
  attachments: {
    type: Array,
    default: () => [],
  },
  maxPreviewLength: {
    type: Number,
    default: 160,
  },
});

const attachments = computed(() => props.attachments ?? []);

const formatSize = (size) => {
  if (!size && size !== 0) return "";
  if (size < 1024) return `${size}B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`;
  return `${(size / (1024 * 1024)).toFixed(1)}MB`;
};

const truncate = (text = "") => {
  if (!text) return "";
  if (text.length <= props.maxPreviewLength) {
    return text;
  }
  return `${text.slice(0, props.maxPreviewLength)}…`;
};
</script>

<style scoped>
.attachment-list {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.attachment-item {
  display: flex;
  gap: var(--space-3);
  min-width: 0;
  padding: 10px var(--space-3);
  border-radius: var(--radius-list);
  background: var(--color-panel-alt);
  border: 1px solid var(--color-border);
}

.attachment-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--radius-control);
  background: var(--color-toolbar-bg);
  color: var(--color-accent-strong);
}

.attachment-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  color: var(--color-text-secondary);
}

.attachment-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-1) var(--space-3);
}

.attachment-name {
  font-weight: 600;
  font-size: 14px;
  overflow-wrap: anywhere;
  color: var(--color-text-primary);
}

.attachment-meta {
  font-size: 12px;
  color: var(--color-text-secondary);
  overflow-wrap: anywhere;
}

.attachment-preview {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
