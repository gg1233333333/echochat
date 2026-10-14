<script setup>
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { Setting, Key, Upload, Delete, RefreshRight } from "@element-plus/icons-vue";
import { useSessionStore } from "@/stores/session";

const store = useSessionStore();
defineProps({ compact: Boolean, historyBusy: Boolean });
const emit = defineEmits(["clear-history", "replay-opening"]);
const keyDialog = computed({
  get: () => store.keySettingsOpen,
  set: (value) => {
    store.keySettingsOpen = value;
  },
});
const importDialog = ref(false);
const apiKey = ref("");
const busy = ref(false);
const keyAction = ref("");
const keyError = ref("");
const importError = ref("");
const importResult = ref("");
const importFile = ref(null);
const hasLegacy = ref(!!localStorage.getItem("session"));
watch(keyDialog, (open) => {
  if (open) keyError.value = "";
});
watch(importDialog, (open) => {
  if (open) {
    importError.value = "";
    importResult.value = "";
  }
});
const settingsCommand = (command) => {
  if (busy.value) return;
  if (command === "key") keyDialog.value = true;
  else if (command === "import" && !store.isGenerating) importDialog.value = true;
  else if (command === "clear") emit("clear-history");
  else if (command === "opening" && !store.isGenerating) emit("replay-opening");
};
const useKey = async () => {
  if (!apiKey.value.trim() || busy.value) return;
  busy.value = true;
  keyAction.value = "save";
  keyError.value = "";
  try {
    await store.configureKey(apiKey.value.trim());
    apiKey.value = "";
    keyDialog.value = false;
    ElMessage.success("密钥已保存");
  } catch (error) {
    keyError.value = error.message;
  } finally {
    busy.value = false;
    keyAction.value = "";
  }
};
const clearKey = async () => {
  if (busy.value || !store.configured) return;
  busy.value = true;
  keyAction.value = "clear";
  keyError.value = "";
  try {
    await store.clearKey();
    apiKey.value = "";
    ElMessage.success("密钥已清除");
  } catch (error) {
    keyError.value = error.message;
  } finally {
    busy.value = false;
    keyAction.value = "";
  }
};
const importSnapshot = async (source) => {
  if (busy.value || store.isGenerating) return;
  busy.value = true;
  importResult.value = "";
  importError.value = "";
  try {
    const snapshot = JSON.parse(await source);
    if (store.isGenerating) {
      importError.value = "请等待当前回复完成或停止生成后再导入记录";
      return;
    }
    const result = await store.importHistory(snapshot);
    importResult.value = `已导入 ${result.imported_conversations} 个对话、${result.imported_messages} 条消息，跳过 ${result.skipped_conversations} 个已导入对话。`;
  } catch (error) {
    importError.value = error instanceof SyntaxError ? "文件不是有效的 JSON 快照" : error.message;
  } finally {
    busy.value = false;
  }
};
const importCurrent = () => {
  if (busy.value || store.isGenerating) return;
  const snapshot = localStorage.getItem("session");
  if (snapshot) importSnapshot(snapshot);
  else importError.value = "当前地址没有旧版记录，请选择旧页面导出的 JSON 文件";
};
const chooseImport = (event) => {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file || busy.value || store.isGenerating) return;
  importSnapshot(
    file.text().catch(() => {
      throw new Error("无法读取导入文件");
    }),
  );
};
const exportLegacy = () => {
  if (busy.value) return;
  const snapshot = localStorage.getItem("session");
  if (!snapshot) return;
  const url = URL.createObjectURL(new Blob([snapshot], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "vue-llm-history.json";
  anchor.click();
  URL.revokeObjectURL(url);
};
</script>

<template>
  <div class="backend-tools" :class="{ 'is-compact': compact }">
    <button
      class="key-shortcut"
      :class="{ 'needs-key': !store.configured }"
      type="button"
      :aria-label="store.configured ? 'API Key 已保存，修改配置' : '配置 API Key'"
      :title="store.configured ? 'API Key 已保存在后端内存' : '配置 API Key 后开始对话'"
      :disabled="!store.ready || busy"
      @click="keyDialog = true"
    >
      <el-icon :size="16"><Key /></el-icon>
      <span class="key-label"
        >API Key <span class="key-status">{{ store.configured ? "已保存" : "未配置" }}</span></span
      >
    </button>
    <el-dropdown trigger="click" :disabled="!store.ready || busy" @command="settingsCommand">
      <button
        class="settings-trigger"
        type="button"
        aria-label="设置"
        title="设置"
        :disabled="!store.ready || busy"
      >
        <el-icon :size="16"><Setting /></el-icon>
      </button>
      <template #dropdown
        ><el-dropdown-menu>
          <el-dropdown-item command="key" :icon="Key"
            >API Key 设置 · {{ store.configured ? "已保存" : "未配置" }}</el-dropdown-item
          >
          <el-dropdown-item command="import" :icon="Upload" :disabled="store.isGenerating"
            >导入旧记录</el-dropdown-item
          >
          <el-dropdown-item
            command="opening"
            :icon="RefreshRight"
            :disabled="store.isGenerating"
            :title="store.isGenerating ? '回复生成结束后可重播' : '重播品牌开场'"
            >重播开场</el-dropdown-item
          >
          <el-dropdown-item
            command="clear"
            :icon="Delete"
            :disabled="historyBusy || !store.visibleConversations.length"
            divided
            >清空对话</el-dropdown-item
          >
        </el-dropdown-menu></template
      >
    </el-dropdown>
  </div>
  <el-dialog
    v-model="keyDialog"
    title="API Key 设置"
    width="min(460px, 92vw)"
    class="echo-settings-dialog"
    append-to-body
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    :show-close="!busy"
    @closed="apiKey = ''"
  >
    <p class="settings-note">
      密钥仅保存在本次后端运行内存中，刷新页面仍可使用；清除或重启后端后需重新填写。
    </p>
    <el-input
      v-model="apiKey"
      type="password"
      show-password
      autocomplete="off"
      :disabled="busy"
      placeholder="输入 DeepSeek API Key"
      aria-label="DeepSeek API Key"
      @keyup.enter="useKey"
    />
    <p class="settings-status">
      <el-icon><Key /></el-icon>{{ store.configured ? "API Key 已保存" : "尚未配置 API Key" }}
    </p>
    <el-alert
      v-if="keyError"
      :title="keyError"
      type="error"
      :closable="false"
      show-icon
      role="alert"
    />
    <template #footer>
      <el-button
        :loading="keyAction === 'clear'"
        :disabled="!store.configured || busy"
        @click="clearKey"
        >清除密钥</el-button
      >
      <el-button
        type="primary"
        :loading="keyAction === 'save'"
        :disabled="!apiKey.trim() || busy"
        @click="useKey"
        >{{ store.configured ? "更换密钥" : "使用密钥" }}</el-button
      >
    </template>
  </el-dialog>
  <el-dialog
    v-model="importDialog"
    title="导入旧记录"
    width="min(520px, 92vw)"
    class="echo-settings-dialog"
    append-to-body
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    :show-close="!busy"
  >
    <p class="settings-note">
      可导入当前地址的旧版浏览器记录，或选择从旧页面导出的 JSON
      快照。原缓存保留，相同快照重复导入会跳过。
    </p>
    <div class="import-actions">
      <el-button :disabled="!hasLegacy || busy || store.isGenerating" @click="importCurrent"
        >导入当前旧缓存</el-button
      >
      <el-button :disabled="busy || store.isGenerating" @click="importFile?.click()"
        >导入 JSON 文件</el-button
      >
      <el-button text :disabled="!hasLegacy || busy" @click="exportLegacy">导出旧缓存</el-button>
    </div>
    <p v-if="!hasLegacy" class="settings-note">
      当前地址未发现旧缓存；从原 vue-llm 页面导出的文件可在此导入，操作方法见项目 README。
    </p>
    <p v-if="store.isGenerating" class="settings-note" role="status">
      请等待当前回复完成或停止生成后再导入记录。
    </p>
    <el-alert v-if="importResult" :title="importResult" type="success" :closable="false" />
    <el-alert
      v-if="importError"
      :title="importError"
      type="error"
      :closable="false"
      show-icon
      role="alert"
    />
    <p v-if="busy" class="settings-note" role="status">正在导入记录…</p>
    <input
      ref="importFile"
      type="file"
      accept=".json,application/json"
      :disabled="busy || store.isGenerating"
      hidden
      @change="chooseImport"
    />
  </el-dialog>
</template>

<style scoped>
.backend-tools {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: var(--space-1);
}
.settings-trigger,
.key-shortcut {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 32px;
  padding: var(--space-2);
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-sidebar-muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition:
    background var(--motion-fast),
    color var(--motion-fast);
}
.key-shortcut {
  min-width: 0;
  flex: 1;
  justify-content: flex-start;
}
.key-shortcut > .el-icon {
  flex-shrink: 0;
}
.key-label {
  white-space: nowrap;
}
.key-status {
  margin-left: var(--space-1);
}
.key-shortcut.needs-key {
  color: var(--color-sidebar-text);
}
.key-shortcut.needs-key > .el-icon {
  color: var(--color-brand-mint);
}
.settings-trigger:hover,
.settings-trigger:focus-visible,
.key-shortcut:hover,
.key-shortcut:focus-visible {
  background: var(--color-sidebar-hover);
  color: var(--color-sidebar-text);
}
.settings-trigger:focus-visible,
.key-shortcut:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
.settings-trigger:disabled,
.key-shortcut:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.settings-note {
  font-size: 13px;
  line-height: 1.65;
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-4);
}
.settings-note + .settings-note,
.el-input + .settings-note {
  margin-top: var(--space-3);
}
.settings-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: var(--space-3) 0 var(--space-4);
  color: var(--color-text-secondary);
  font-size: 13px;
}
.settings-status > .el-icon {
  color: var(--color-accent);
}
.import-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.import-actions .el-button + .el-button {
  margin-left: 0;
}
.is-compact {
  flex-direction: column;
  gap: var(--space-2);
}
.is-compact .settings-trigger,
.is-compact .key-shortcut {
  width: 40px;
  min-height: 40px;
  justify-content: center;
}
.is-compact .key-label {
  display: none;
}
@media (prefers-reduced-motion: reduce) {
  .settings-trigger,
  .key-shortcut {
    transition: none;
  }
}
@media (max-width: 767px) {
  .settings-trigger,
  .key-shortcut {
    min-height: 44px;
  }
  .settings-trigger {
    min-width: 44px;
  }
}
</style>
