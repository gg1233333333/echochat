<template>
  <div class="container">
    <div class="input-area">
      <textarea
        ref="textarea"
        v-model="inputText"
        class="inputbox"
        :placeholder="placeholder"
        @input="resize"
        @keydown.enter.prevent="handleEnter"
      ></textarea>

      <transition-group name="fade" tag="div" class="attachments" v-if="attachments.length">
        <div v-for="file in attachments" :key="file.id" class="attachment-chip">
          <el-icon class="attachment-icon"><Paperclip /></el-icon>
          <div class="attachment-meta">
            <span class="attachment-name">{{ file.name }}</span>
            <span class="attachment-size">{{ formatSize(file.size) }}</span>
          </div>
          <button class="attachment-remove" type="button" @click="removeAttachment(file.id)">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </transition-group>

      <div v-if="speechPreview" class="speech-preview">
        <el-icon><Microphone /></el-icon>
        <span>{{ speechPreview }}</span>
      </div>

      <div class="toolbar">
        <button class="toolbar-btn" type="button" @click="triggerFilePicker">
          <el-icon><UploadFilled /></el-icon>
          <span>上传文件</span>
        </button>
        <button
          v-if="isSpeechSupported"
          class="toolbar-btn"
          :class="{ recording: isRecording }"
          type="button"
          @click="toggleRecording"
          :disabled="isTyping"
        >
          <el-icon><Microphone /></el-icon>
          <span>{{ isRecording ? "停止语音" : "语音输入" }}</span>
        </button>
        <span class="toolbar-hint">Shift + Enter 换行</span>
      </div>
    </div>

    <div class="action-area">
      <button
        v-if="!isTyping"
        class="send-button"
        type="button"
        :disabled="sendDisabled"
        @click="handleSubmit"
      >
        <span>发送</span>
        <el-icon><Promotion /></el-icon>
      </button>
      <button v-else class="stop-button" type="button" @click="stopGeneration">
        停止
        <el-icon class="stop-icon"><CircleClose /></el-icon>
      </button>
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

<script setup>
import {
  CircleClose,
  Close,
  Microphone,
  Paperclip,
  Promotion,
  UploadFilled,
} from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import JSZip from "jszip";
import {
  computed,
  defineEmits,
  defineProps,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";

import { abortStream } from "@/apis/deepseek";
import * as pdfjsLib from "pdfjs-dist/legacy/build/pdf.mjs";
import pdfWorker from "pdfjs-dist/build/pdf.worker?url";

defineOptions({ name: "ChatInput" });

if (pdfjsLib?.GlobalWorkerOptions) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker;
}

const props = defineProps({
  msg: {
    type: String,
    default: "",
  },
  isTyping: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["update:msg", "update:isTyping", "submit"]);

/**
 * 文本输入框的双向绑定代理，直接透传给父组件维护的状态，
 * 方便 ChatMessage 统一管理消息体。
 */
const inputText = computed({
  get: () => props.msg,
  set: (val) => emit("update:msg", val),
});

/**
 * 父组件会告知当前是否在生成回答，根据该状态控制按钮和语音录制。
 */
const isTyping = computed({
  get: () => props.isTyping,
  set: (val) => emit("update:isTyping", val),
});

const textarea = ref(null);
const fileInput = ref(null);
const attachments = ref([]);
const speechPreview = ref("");
const isRecording = ref(false);
const recognition = ref(null);

/**
 * 允许上传的文件扩展名，涵盖常见文本、文档以及代码类型。
 */
const ALLOWED_EXTENSIONS = new Set([
  "txt",
  "md",
  "csv",
  "json",
  "log",
  "pdf",
  "doc",
  "docx",
  "xml",
  "yml",
  "yaml",
  "html",
  "css",
  "scss",
  "less",
  "js",
  "jsx",
  "ts",
  "tsx",
  "vue",
  "py",
  "java",
  "c",
  "cpp",
  "cc",
  "h",
  "hpp",
  "cs",
  "php",
  "rb",
  "go",
  "rs",
  "kt",
  "swift",
  "sql",
  "sh",
]);

/**
 * 部分浏览器在读取文件时只提供 MIME Type，因此补充一份允许的类型列表。
 */
const ALLOWED_MIME_TYPES = new Set([
  "text/plain",
  "text/csv",
  "text/markdown",
  "application/json",
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/xml",
  "text/xml",
  "text/html",
  "text/css",
  "text/x-python",
  "text/x-java-source",
  "text/x-c",
  "text/x-c++",
  "text/x-script.python",
  "application/javascript",
  "text/javascript",
]);

/**
 * 文件选择框需要的 accept 属性，帮助用户只挑选受支持的格式。
 */
const acceptAttribute = computed(() =>
  Array.from(ALLOWED_EXTENSIONS)
    .map((ext) => `.${ext}`)
    .join(","),
);

const placeholder = computed(() =>
  isSpeechSupported.value
    ? "输入你的问题，或点击语音输入按钮试试看…"
    : "输入你的问题…",
);

const sendDisabled = computed(
  () => !inputText.value.trim() && attachments.value.length === 0,
);

const isSpeechSupported = computed(
  () =>
    typeof window !== "undefined" &&
    ("webkitSpeechRecognition" in window || "SpeechRecognition" in window),
);

const resize = () => {
  const el = textarea.value;
  if (!el) return;

  const minHeight = 120;
  const maxHeight = 240;
  el.style.height = "auto";
  const nextHeight = Math.min(Math.max(el.scrollHeight, minHeight), maxHeight);
  el.style.height = `${nextHeight}px`;
  el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden";
};

const formatSize = (size) => {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

const MAX_FILE_SIZE = 8 * 1024 * 1024;
const MAX_TEXT_PREVIEW = 8000;

const createAttachmentId = () => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
};

const truncatePreview = (text = "") => {
  const trimmed = text.trim();
  const body = trimmed.slice(0, MAX_TEXT_PREVIEW);
  const note =
    trimmed.length > MAX_TEXT_PREVIEW
      ? "内容已截断，仅展示前 8000 字符"
      : "";
  return { body, note };
};

const readAsPlainText = (file) =>
  new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = (reader.result ?? "").toString();
      resolve(truncatePreview(result));
    };
    reader.readAsText(file, "utf-8");
  });

const extractDocxText = async (file) => {
  try {
    const arrayBuffer = await file.arrayBuffer();
    const zip = await JSZip.loadAsync(arrayBuffer);
    const documentFile = zip.file("word/document.xml");
    if (!documentFile) {
      return {
        body: "",
        note: "未能解析 DOCX 正文内容，已附带文件信息。",
      };
    }
    const xml = await documentFile.async("string");
    const parser = new DOMParser();
    const doc = parser.parseFromString(xml, "application/xml");
    const paragraphs = Array.from(doc.getElementsByTagName("w:p"));
    const text = paragraphs
      .map((p) =>
        Array.from(p.getElementsByTagName("w:t"))
          .map((node) => node.textContent)
          .join(""),
      )
      .join("\n")
      .replace(/\n{3,}/g, "\n\n");
    if (!text.trim()) {
      return {
        body: "",
        note: "DOCX 文件未检测到可提取的文本内容。",
      };
    }
    return truncatePreview(text);
  } catch (error) {
    console.error("Failed to extract DOCX", error);
    return {
      body: "",
      note: "解析 DOCX 文件时出错，已附带文件元信息。",
    };
  }
};

const extractPdfText = async (file) => {
  try {
    const arrayBuffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
    const chunks = [];
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      const content = await page.getTextContent();
      const pageText = content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      if (pageText) {
        chunks.push(pageText);
      }
      if (chunks.join("\n\n").length > MAX_TEXT_PREVIEW * 1.5) {
        break;
      }
    }
    const combined = chunks.join("\n\n");
    if (!combined.trim()) {
      return {
        body: "",
        note: "PDF 文件未检测到可提取的文本内容。",
      };
    }
    return truncatePreview(combined);
  } catch (error) {
    console.error("Failed to extract PDF", error);
    return {
      body: "",
      note: "解析 PDF 文件时出错，已附带文件元信息。",
    };
  }
};

const readFileContent = async (file) => {
  const name = file.name || "";
  const type = file.type || "";

  /**
   * 读取纯文本或结构化文本类型，避免误判导致的编码问题。
   */

  if (
    type.startsWith("text/") ||
    type.includes("json") ||
    /\.(md|txt|csv|json|log)$/i.test(name)
  ) {
    return readAsPlainText(file);
  }

  if (/\.docx$/i.test(name) || type.includes("officedocument.wordprocessingml")) {
    return extractDocxText(file);
  }

  if (/\.pdf$/i.test(name) || type === "application/pdf") {
    return extractPdfText(file);
  }

  return {
    body: "",
    note: "该文件为非文本格式，已附带元信息供参考。",
  };
};

/**
 * 根据扩展名或 MIME Type 判断文件是否受支持。
 */
const isFileTypeAllowed = (file) => {
  const name = file.name || "";
  const extension = name.split(".").pop()?.toLowerCase() || "";
  const type = (file.type || "").toLowerCase();

  if (extension && ALLOWED_EXTENSIONS.has(extension)) {
    return true;
  }

  if (type && ALLOWED_MIME_TYPES.has(type)) {
    return true;
  }

  return false;
};

/**
 * 当文件类型不在允许范围内时，弹出置中的警告弹窗进行说明。
 */
const showUnsupportedFileAlert = (file) =>
  ElMessageBox.alert(
    `${file.name || "该文件"} 的格式暂不支持，请上传文本、文档或常见代码文件。`,
    "文件类型不支持",
    {
      confirmButtonText: "我知道了",
      center: true,
    },
  );

const handleFileChange = async (event) => {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;

  for (const file of files) {
    if (!isFileTypeAllowed(file)) {
      await showUnsupportedFileAlert(file);
      continue;
    }

    if (file.size > MAX_FILE_SIZE) {
      ElMessage.warning(`${file.name} 超过 ${formatSize(MAX_FILE_SIZE)}，已忽略`);
      continue;
    }

    const { body, note } = await readFileContent(file);
    attachments.value.push({
      id: createAttachmentId(),
      name: file.name,
      size: file.size,
      type: file.type || "unknown",
      body,
      note,
      addedAt: Date.now(),
    });
  }

  event.target.value = "";
  await nextTick();
  resize();
};

const removeAttachment = (id) => {
  attachments.value = attachments.value.filter((item) => item.id !== id);
};

const triggerFilePicker = () => {
  fileInput.value?.click();
};

const handleSubmit = () => {
  if (sendDisabled.value) return;
  emit("submit", {
    attachments: attachments.value.map((item) => ({ ...item })),
  });
  attachments.value = [];
  speechPreview.value = "";
  nextTick(() => {
    resize();
  });
};

const handleEnter = (event) => {
  if (event.shiftKey) {
    const el = textarea.value;
    if (!el) return;
    const { selectionStart, selectionEnd } = el;
    const value = inputText.value;
    const newValue = `${value.slice(0, selectionStart)}\n${value.slice(selectionEnd)}`;
    inputText.value = newValue;
    nextTick(() => {
      el.selectionStart = el.selectionEnd = selectionStart + 1;
      resize();
    });
    return;
  }

  handleSubmit();
};

const stopGeneration = () => {
  abortStream();
  isTyping.value = false;
};

const ensureRecognition = () => {
  if (!isSpeechSupported.value || recognition.value) return;

  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  const instance = new SpeechRecognition();
  instance.lang = "zh-CN";
  instance.interimResults = true;
  instance.continuous = true;

  instance.onresult = (event) => {
    let finalText = "";
    let interimText = "";

    for (const result of event.results) {
      if (result.isFinal) {
        finalText += result[0].transcript;
      } else {
        interimText += result[0].transcript;
      }
    }

    if (finalText) {
      inputText.value = `${inputText.value} ${finalText}`.trim();
      nextTick(resize);
    }

    speechPreview.value = interimText;
  };

  instance.onerror = () => {
    stopRecording();
  };

  instance.onend = () => {
    stopRecording();
  };

  recognition.value = instance;
};

const startRecording = () => {
  if (!isSpeechSupported.value || isRecording.value) return;
  ensureRecognition();
  try {
    recognition.value?.start();
    isRecording.value = true;
    speechPreview.value = "正在听…";
  } catch (error) {
    console.error(error);
    ElMessage.error("无法启动语音识别");
    isRecording.value = false;
  }
};

const stopRecording = () => {
  if (recognition.value && typeof recognition.value.stop === "function") {
    recognition.value.stop();
  }
  isRecording.value = false;
  speechPreview.value = "";
};

const toggleRecording = () => {
  if (isRecording.value) {
    stopRecording();
  } else {
    startRecording();
  }
};

onMounted(() => {
  resize();
});

onBeforeUnmount(() => {
  stopRecording();
});

// 当内容被清空时重新计算高度，保持输入框紧凑
watch(inputText, (value) => {
  if (!value.trim()) {
    nextTick(resize);
  }
});

// 一旦开始生成回答立即停止语音识别，避免录音状态悬挂
watch(isTyping, (value) => {
  if (value) {
    stopRecording();
  }
});
</script>

<style scoped>
.container {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  justify-content: space-between;
  padding: 20px 24px;
  background: var(--color-panel);
  border-top: 1px solid var(--color-border);
  position: relative;
}

.container::before {
  content: '';
  position: absolute;
  top: 0;
  left: 24px;
  right: 24px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--color-border), transparent);
  opacity: 0.5;
}

.input-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.inputbox {
  width: 100%;
  min-height: 120px;
  max-height: 240px;
  font-size: 15px;
  line-height: 1.6;
  padding: 12px 16px;
  border-radius: 16px;
  border: 1px solid var(--color-border);
  background: var(--color-input-background);
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.08);
  resize: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  outline: none;
}

.inputbox:focus {
  border-color: var(--color-accent);
  box-shadow: 0 4px 18px rgba(59, 130, 246, 0.18);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 12px;
  border: none;
  background: var(--color-toolbar-bg);
  color: var(--color-toolbar-text);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.toolbar-btn:hover {
  background: var(--color-toolbar-hover-bg);
  color: var(--color-accent-strong);
}

.toolbar-btn.recording {
  background: var(--color-stop-button-bg);
  color: var(--color-stop-button-text);
}

.toolbar-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.toolbar-hint {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-toolbar-muted);
}

.attachments {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 12px;
  background: var(--color-toolbar-bg);
  color: var(--color-text-secondary);
  border: 1px solid rgba(59, 130, 246, 0.18);
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.08);
}

.attachment-icon {
  font-size: 14px;
}

.attachment-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.attachment-name {
  font-size: 13px;
  font-weight: 500;
}

.attachment-size {
  font-size: 11px;
  color: var(--color-muted);
}

.attachment-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--color-muted);
  transition: color 0.2s ease;
}

.attachment-remove:hover {
  color: var(--color-danger);
}

.speech-preview {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-text-secondary);
  padding: 6px 10px;
  border-radius: 10px;
  background: var(--color-toolbar-bg);
  border: 1px solid rgba(59, 130, 246, 0.18);
}

.action-area {
  display: flex;
  align-items: center;
}

.send-button,
.stop-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 24px;
  height: 48px;
  border-radius: 16px;
  border: none;
  cursor: pointer;
  font-size: 15px;
  font-weight: 500;
  transition: all 0.2s ease;
}

.send-button {
  background: linear-gradient(135deg, var(--color-accent-strong), var(--color-accent));
  color: var(--color-accent-contrast);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
  position: relative;
  overflow: hidden;
}

.send-button::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.15), transparent);
  transition: left 0.5s ease;
}

.send-button:not(:disabled):hover::before {
  left: 100%;
}

.send-button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
  box-shadow: none;
}

.send-button:not(:disabled):hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.4);
}

.stop-button {
  background: var(--color-stop-button-bg);
  color: var(--color-stop-button-text);
  box-shadow: 0 6px 12px var(--color-stop-button-shadow);
}

.stop-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 18px var(--color-stop-button-shadow);
}

.stop-icon {
  font-size: 16px;
}

.file-input {
  display: none;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 960px) {
  .container {
    flex-direction: column;
    align-items: stretch;
  }

  .action-area {
    justify-content: flex-end;
  }
}

@media (max-width: 768px) {
  .container {
    padding: 16px 18px;
    gap: 12px;
  }

  .toolbar {
    gap: 10px;
  }

  .toolbar-hint {
    margin-left: 0;
    width: 100%;
    text-align: right;
  }

  .action-area {
    width: 100%;
  }

  .send-button,
  .stop-button {
    width: 100%;
    justify-content: center;
  }
}

@media (max-width: 480px) {
  .container {
    padding: 14px 14px;
  }

  .toolbar-btn span {
    display: none;
  }

  .toolbar-hint {
    font-size: 11px;
  }
}
</style>
