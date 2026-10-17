<script setup>
import { computed } from "vue";
import RunDetails from "./RunDetails.vue";
import { ArrowRight, Connection, Download } from "@element-plus/icons-vue";

const props = defineProps({
  runId: { type: String, default: null },
  calls: { type: Array, default: () => [] },
  artifacts: { type: Array, default: () => [] },
});
const emit = defineEmits(["resize"]);
const labels = {
  pending: "等待", running: "执行中", completed: "已完成",
  failed: "失败", cancelled: "已停止", interrupted: "已中断",
};
const active = computed(() => props.calls.find((call) => call.status === "running"));
const preview = (value) => {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (!text) return "";
  return text.length > 4000 ? `${text.slice(0, 4000)}\n…（预览已截断）` : text;
};
</script>

<template>
  <div v-if="calls.length || artifacts.length || runId" class="tool-activity">
    <RunDetails v-if="runId" :run-id="runId" />
    <details v-if="calls.length" class="tool-details" @toggle="emit('resize')">
      <summary>
        <el-icon class="tool-chevron"><ArrowRight /></el-icon>
        <el-icon><Connection /></el-icon>
        <span>{{ active ? `${active.label}…` : `工具记录 · ${calls.length}` }}</span>
      </summary>
      <ol class="tool-list">
        <li v-for="call in calls" :key="call.id" :data-tool-status="call.status">
          <details @toggle="emit('resize')">
            <summary>
              <span>{{ call.label }}</span>
              <span class="tool-status">{{ labels[call.status] || call.status }}</span>
            </summary>
            <div class="tool-payload">
              <p>参数</p><pre>{{ preview(call.arguments) }}</pre>
              <template v-if="call.result">
                <p>结果</p><pre>{{ preview(call.result) }}</pre>
              </template>
            </div>
          </details>
        </li>
      </ol>
    </details>
    <div v-if="artifacts.length" class="tool-artifacts">
      <a v-for="file in artifacts" :key="file.id" :href="file.download_url" download>
        <el-icon><Download /></el-icon><span>{{ file.name }}</span>
      </a>
    </div>
  </div>
</template>

<style scoped>
.tool-activity {
  min-width: 0;
  margin: 0 0 12px;
  color: var(--color-text-secondary);
  font-size: 13px;
}
summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  cursor: pointer;
  list-style: none;
  border-radius: var(--radius-control);
}
summary::-webkit-details-marker {
  display: none;
}
summary:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
.tool-chevron {
  transition: transform 150ms;
}
.tool-details[open] > summary .tool-chevron {
  transform: rotate(90deg);
}
.tool-list {
  list-style: none;
  padding: 4px 0 4px 12px;
  margin: 0 0 0 5px;
  border-left: 1px solid var(--color-border);
}
.tool-list summary {
  justify-content: space-between;
  gap: 12px;
  padding: 0 8px;
}
.tool-status {
  flex-shrink: 0;
  font-size: 12px;
}
[data-tool-status="running"] .tool-status {
  color: var(--color-accent);
}
[data-tool-status="failed"] .tool-status {
  color: var(--color-danger, #c2414b);
}
.tool-payload {
  padding: 4px 8px 12px;
}
.tool-payload p {
  margin: 4px 0;
  font-size: 12px;
}
pre {
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  background: var(--color-code-surface);
  color: var(--color-code-text);
  font-size: 12px;
  line-height: 1.6;
}
.tool-artifacts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.tool-artifacts a {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  min-height: 40px;
  padding: 6px 12px;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  color: var(--color-accent);
  text-decoration: none;
}
.tool-artifacts span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.tool-artifacts .el-icon {
  flex-shrink: 0;
}
</style>
