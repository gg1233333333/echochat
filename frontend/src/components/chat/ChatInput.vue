<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { CircleClose, Close, Key, Microphone, Paperclip, Promotion, Connection } from "@element-plus/icons-vue";
import { useSessionStore } from "@/stores/session";
import { useSpeechInput } from "@/composables/useSpeechInput";

const emit = defineEmits(["submit"]);
const store = useSessionStore();
const toolPermissionsOpen = ref(false);
const textarea = ref(null);
const composerColumn = ref(null);
const composerExtras = ref(null);
const fileInput = ref(null);
const composing = ref(false);
const fileFeedback = ref("");
const speechError = ref("");
let resizeObserver;
let columnWidth = 0;
const inputText = computed({
  get: () => store.currentDraft.text,
  set: (value) => store.setDraftText(value),
});
const files = computed(() => store.currentDraft.files);
const limits = computed(() => store.options?.attachments);
const acceptAttribute = computed(() =>
  limits.value?.extensions
    .map((extension) => (extension.startsWith(".") ? extension : `.${extension}`))
    .join(","),
);
const sendDisabled = computed(
  () => !store.ready || store.pages[store.currentId]?.loading || store.isGenerating || (!inputText.value.trim() && !files.value.length),
);
const placeholder = "描述问题、任务，或一个还没成形的想法…";
const formatSize = (size) =>
  size < 1024
    ? `${size}B`
    : size < 1024 * 1024
      ? `${(size / 1024).toFixed(1)}KB`
      : `${(size / 1024 / 1024).toFixed(1)}MB`;
const resize = () => {
  if (!textarea.value) return;
  const maxHeight = Math.max(48, 164 - (composerExtras.value?.offsetHeight || 0));
  textarea.value.style.height = "auto";
  textarea.value.style.height = `${Math.min(textarea.value.scrollHeight, maxHeight)}px`;
};
const { supported, starting, recording, preview, stop, toggle } = useSpeechInput(
  (text) => {
    inputText.value = `${inputText.value} ${text}`.trim();
  },
  (message) => {
    speechError.value = message;
    ElMessage.error(message);
  },
);
const toggleSpeech = () => {
  speechError.value = "";
  toggle();
};
const handleSubmit = () => {
  if (sendDisabled.value) return;
  if (!store.configured) {
    store.keySettingsOpen = true;
    return;
  }
  stop();
  emit("submit");
};
const handleEnter = (event) => {
  if (event.isComposing || composing.value || event.keyCode === 229 || event.shiftKey) return;
  event.preventDefault();
  handleSubmit();
};
const handleFileChange = (event) => {
  const selected = Array.from(event.target.files || []);
  event.target.value = "";
  if (!limits.value) return;
  const warnings = [];
  fileFeedback.value = "";
  const warn = (message) => {
    warnings.push(message);
    ElMessage.warning(message);
  };
  const accepted = [];
  let total = files.value.reduce((sum, file) => sum + file.size, 0);
  for (const file of selected) {
    const extension = file.name.split(".").pop().toLowerCase();
    if (!limits.value.extensions.some((item) => item.replace(/^\./, "") === extension)) {
      warn(`${file.name} 的文件类型不支持`);
      continue;
    }
    if (file.size > limits.value.max_file_bytes) {
      warn(`${file.name} 超过 ${formatSize(limits.value.max_file_bytes)}`);
      continue;
    }
    if (
      files.value.length + accepted.length >= limits.value.max_files ||
      total + file.size > limits.value.max_total_bytes
    ) {
      warn(
        `每次最多 ${limits.value.max_files} 个文件，总大小不超过 ${formatSize(limits.value.max_total_bytes)}`,
      );
      break;
    }
    accepted.push(file);
    total += file.size;
  }
  fileFeedback.value = warnings.join("；");
  store.addFiles(accepted);
};
const stopGeneration = () => store.cancelGeneration().catch(store.reportError);
watch(
  () => store.currentId,
  () => {
    stop();
    fileFeedback.value = "";
    speechError.value = "";
  },
);
watch(
  () => store.isGenerating,
  (active) => {
    if (active) stop();
  },
);
watch(inputText, () => nextTick(resize));
watch(
  () => [files.value.length, preview.value, fileFeedback.value, speechError.value],
  () => nextTick(resize),
);
onMounted(() => {
  resize();
  resizeObserver = new ResizeObserver(([entry]) => {
    if (entry.contentRect.width === columnWidth) return;
    columnWidth = entry.contentRect.width;
    resize();
  });
  resizeObserver.observe(composerColumn.value);
});
onBeforeUnmount(() => resizeObserver?.disconnect());
</script>

<template>
  <div class="container">
    <div ref="composerColumn" class="composer-column">
      <div class="composer-frame">
        <textarea
          ref="textarea"
          v-model="inputText"
          class="inputbox"
          rows="1"
          :placeholder="placeholder"
          :disabled="!store.ready"
          aria-label="消息输入"
          @input="resize"
          @keydown.enter="handleEnter"
          @compositionstart="composing = true"
          @compositionend="composing = false"
        ></textarea>
        <div ref="composerExtras" class="composer-extras">
          <transition-group
            v-if="files.length"
            name="fade"
            tag="div"
            class="attachments"
            @after-enter="resize"
            @after-leave="resize"
          >
            <div
              v-for="(file, index) in files"
              :key="`${file.name}-${index}`"
              class="attachment-chip"
            >
              <el-icon class="attachment-icon"><Paperclip /></el-icon>
              <div class="attachment-meta">
                <span class="attachment-name">{{ file.name }}</span
                ><span class="attachment-size"
                  >{{ file.type || file.name.split(".").pop().toUpperCase() }} ·
                  {{ formatSize(file.size) }} · 随消息发送</span
                >
              </div>
              <button
                class="attachment-remove"
                type="button"
                :aria-label="`移除 ${file.name}`"
                @click="store.removeFile(index)"
              >
                <el-icon><Close /></el-icon>
              </button>
            </div>
          </transition-group>
          <div v-if="preview" class="speech-preview">
            <el-icon><Microphone /></el-icon><span>{{ preview }}</span>
          </div>
          <p v-if="fileFeedback" class="composer-feedback" role="alert">
            <span>{{ fileFeedback }}</span>
            <button type="button" aria-label="关闭文件提示" @click="fileFeedback = ''">
              <el-icon><Close /></el-icon>
            </button>
          </p>
          <p v-if="speechError" class="composer-feedback" role="alert">
            <span>{{ speechError }}</span>
            <button type="button" aria-label="关闭语音提示" @click="speechError = ''">
              <el-icon><Close /></el-icon>
            </button>
          </p>
        </div>
        <div class="toolbar">
          <el-popover v-model:visible="toolPermissionsOpen" trigger="click" placement="top-start" :width="280" :persistent="false" popper-class="tool-permissions-popover">
            <template #reference>
              <button class="toolbar-btn agent-toggle" :class="{ enabled: store.agentEnabled && store.allowedTools.length }"
                type="button" aria-label="允许使用工具" :aria-pressed="store.agentEnabled" :aria-expanded="toolPermissionsOpen"
                :disabled="!store.ready || store.isGenerating">
                <el-icon><Connection /></el-icon><span>工具</span>
              </button>
            </template>
            <div class="tool-permissions">
              <el-checkbox :model-value="store.agentEnabled" :disabled="store.isGenerating" @change="store.toggleAgent">允许使用工具</el-checkbox>
              <p>只对下一次发送生效。联网搜索会向搜索引擎发送关键词。</p>
              <el-checkbox v-for="tool in store.options?.tools || []" :key="tool.name"
                :model-value="store.allowedTools.includes(tool.name)" :disabled="!store.agentEnabled || store.isGenerating"
                @change="(enabled) => store.setTool(tool.name, enabled)">{{ tool.label }}</el-checkbox>
              <el-button text @click="toolPermissionsOpen = false">完成</el-button>
            </div>
          </el-popover>
          <el-tooltip content="上传文件" placement="top"
            ><button
              class="toolbar-btn"
              type="button"
              aria-label="上传文件"
              :disabled="!store.ready"
              @click="fileInput?.click()"
            >
              <el-icon><Paperclip /></el-icon><span>上传文件</span>
            </button></el-tooltip
          >
          <el-tooltip
            :content="starting ? '取消语音启动' : recording ? '停止语音' : '语音输入'"
            placement="top"
            ><button
              v-if="supported"
              class="toolbar-btn"
              :class="{ recording }"
              type="button"
              :aria-label="starting ? '取消语音启动' : recording ? '停止语音' : '语音输入'"
              :disabled="store.isGenerating || !store.ready"
              @click="toggleSpeech"
            >
              <el-icon><Microphone /></el-icon
              ><span>{{ starting ? "启动中…" : recording ? "停止语音" : "语音输入" }}</span>
            </button></el-tooltip
          >
          <div class="action-area">
            <button
              v-if="!store.configured && !store.isGenerating"
              class="send-button"
              type="button"
              aria-label="配置 API Key"
              :disabled="!store.ready"
              @click="store.keySettingsOpen = true"
            >
              <span class="action-label">配置 API Key</span><el-icon><Key /></el-icon>
            </button>
            <button
              v-else-if="!store.isGenerating"
              class="send-button"
              type="button"
              aria-label="发送"
              :disabled="sendDisabled"
              @click="handleSubmit"
            >
              <span class="action-label">发送</span><el-icon><Promotion /></el-icon>
            </button>
            <button
              v-else
              class="stop-button"
              type="button"
              :aria-label="store.activeGeneration?.cancelling ? '停止中…' : '停止'"
              :disabled="store.activeGeneration?.cancelling"
              @click="stopGeneration"
            >
              <span class="action-label">{{
                store.activeGeneration?.cancelling ? "停止中…" : "停止"
              }}</span
              ><el-icon class="stop-icon"><CircleClose /></el-icon>
            </button>
          </div>
        </div>
      </div>
      <p class="toolbar-hint">Enter 发送 · Shift + Enter 换行</p>
    </div>
    <input
      ref="fileInput"
      class="file-input"
      type="file"
      multiple
      :accept="acceptAttribute"
      @change="handleFileChange"
    />
  </div>
</template>

<style scoped>
.tool-permissions { display: flex; flex-direction: column; max-height: min(420px, 60vh); overflow: auto; }
.tool-permissions p { color: var(--color-text-secondary); font-size: 12px; line-height: 1.5; margin: 4px 0 8px; }
.tool-permissions .el-checkbox { margin-right: 0; min-height: 36px; }
.container {
  flex-shrink: 0;
  min-width: 0;
  padding: 6px var(--chat-gutter);
  background: transparent;
}
.composer-column {
  width: 100%;
  max-width: var(--chat-column-width);
  margin: 0 auto;
}
.composer-frame {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-composer);
  background: var(--color-input-background);
  box-shadow: var(--shadow-composer, var(--shadow-soft));
  overflow: hidden;
  transition:
    border-color var(--motion-fast) ease,
    box-shadow var(--motion-fast) ease;
}
.composer-frame:focus-within {
  border-color: var(--color-accent);
  box-shadow:
    0 0 0 3px var(--color-toolbar-bg),
    var(--shadow-composer, var(--shadow-soft));
}
.inputbox {
  display: block;
  width: 100%;
  min-height: 48px;
  max-height: 164px;
  padding: 12px var(--space-4);
  border: 0;
  outline: none;
  resize: none;
  overflow-y: auto;
  background: transparent;
  color: var(--color-text-primary);
  font: inherit;
  font-size: 16px;
  line-height: 24px;
}
.inputbox::placeholder {
  color: var(--color-text-secondary);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2) var(--space-1);
}
.toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition:
    color var(--motion-fast) ease,
    background var(--motion-fast) ease,
    transform var(--motion-fast) ease;
}
.toolbar-btn .el-icon {
  font-size: 18px;
}
.toolbar-btn:hover,
.toolbar-btn:focus-visible {
  background: var(--color-panel-alt);
  color: var(--color-text-primary);
}
.toolbar-btn:focus-visible,
.attachment-remove:focus-visible,
.send-button:focus-visible,
.stop-button:focus-visible,
.composer-feedback button:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
.toolbar-btn:not(:disabled):active,
.send-button:not(:disabled):active,
.stop-button:not(:disabled):active {
  transform: scale(0.96);
}
.toolbar-btn.recording {
  background: var(--color-stop-button-bg);
  color: var(--color-stop-button-text);
}
.agent-toggle.enabled {
  background: var(--color-accent-soft, var(--color-panel-alt));
  color: var(--color-accent);
}
.toolbar-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.toolbar-hint {
  margin-top: 2px;
  color: var(--color-text-secondary);
  text-align: center;
  font-size: 12px;
  line-height: 16px;
}
.action-area {
  display: flex;
  margin-left: auto;
}
.send-button,
.stop-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 40px;
  height: 36px;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-control);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition:
    background var(--motion-fast) ease,
    transform var(--motion-fast) ease;
}
.send-button .el-icon,
.stop-button .el-icon {
  font-size: 18px;
}
.send-button {
  background: var(--color-accent);
  color: var(--color-accent-contrast);
}
.send-button:not(:disabled):hover {
  background: var(--color-accent-strong);
}
.send-button:disabled,
.stop-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.stop-button {
  background: var(--color-stop-button-bg);
  color: var(--color-stop-button-text);
}
.composer-extras {
  max-height: 108px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.attachments {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  padding: 0 var(--space-3) var(--space-2);
  overscroll-behavior: contain;
}
.attachment-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  min-width: 0;
  max-width: min(360px, 100%);
  padding: 5px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-panel-alt);
  color: var(--color-text-secondary);
}
.attachment-icon {
  flex-shrink: 0;
  color: var(--color-accent);
}
.attachment-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.attachment-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 270px;
  color: var(--color-text-primary);
  font-size: 13px;
}
.attachment-size {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attachment-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.attachment-remove:hover {
  color: var(--color-danger);
}
.speech-preview {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: 0 var(--space-4) var(--space-2);
  color: var(--color-text-secondary);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.composer-feedback {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 var(--space-3) var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-control);
  color: var(--color-danger);
  background: var(--color-stop-button-bg);
  font-size: 12px;
  line-height: 1.5;
}
.composer-feedback span {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.composer-feedback button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.file-input {
  display: none;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--motion-fast) ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
@media (max-width: 767px) {
  .container {
    padding-bottom: max(6px, env(safe-area-inset-bottom));
  }
  .toolbar-btn span,
  .action-label,
  .toolbar-hint {
    display: none;
  }
  .toolbar-btn,
  .send-button,
  .stop-button {
    width: 44px;
    height: 44px;
    padding: 0;
    justify-content: center;
  }
  .attachment-remove,
  .composer-feedback button {
    width: 44px;
    height: 44px;
  }
  .attachment-chip {
    max-width: 100%;
  }
}
@media (prefers-reduced-motion: reduce) {
  .composer-frame,
  .toolbar-btn,
  .send-button,
  .stop-button,
  .fade-enter-active,
  .fade-leave-active {
    transition: none;
  }
}
</style>
