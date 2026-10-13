<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  onUpdated,
  ref,
  watch,
} from "vue";
import MarkdownIt from "markdown-it";
import hljs from "highlight.js";
import "highlight.js/styles/github.css";
import { markdownItTable } from "markdown-it-table";
import {
  CopyDocument,
  EditPen,
  Close,
  Delete,
  RefreshRight,
  DocumentCopy,
} from "@element-plus/icons-vue";
import { DynamicScroller, DynamicScrollerItem } from "vue-virtual-scroller";

import { chatStream } from "@/apis/deepseek";
import { createStreamQueue } from "@/utils/streamQueue";
import {
  getAllRoles,
  getRoleById,
  isDeveloperMode,
  isLikelyNonTechnical,
} from "@/utils/aiRoles";
import AttachmentPreview from "@/components/chat/AttachmentPreview.vue";
import ChatInput from "@/components/chat/ChatInput.vue";
import { useSessionStore } from "@/stores/session";
import userAvatar from "@/assets/avatars/user.svg";
import assistantAvatarGeneral from "@/assets/avatars/assistant.svg";
import assistantAvatarDeveloper from "@/assets/avatars/faviconcode.svg";

defineOptions({ name: "ChatMessage" });

const sessionStore = useSessionStore();
const msg = ref("");
const isTyping = ref(false);
const showNewMessageIndicator = ref(false);

const streamQueue = createStreamQueue();

const selectedModel = computed({
  get: () => sessionStore.model,
  set: (value) => sessionStore.setModel(value),
});

const modelOptions = computed(() => sessionStore.modelOptions);

const aiRoles = computed(() => getAllRoles());
const selectedRole = computed({
  get: () => sessionStore.currentRole,
  set: (value) => sessionStore.setRole(value),
});
const currentRoleId = computed(() => selectedRole.value);
const currentRole = computed(() => sessionStore.getCurrentRole());
const showDeveloperModeWarning = ref(false);
let developerWarningTimer = null;

const messages = computed(() => sessionStore.getcurmsgs());

watch(
  () => sessionStore.curname,
  async () => {
    autoScroll = true;
    showNewMessageIndicator.value = false;
    await forceScrollToBottom();
  },
);

const md = new MarkdownIt({
  highlight: (code, lang) => {
    const validLang = !!(lang && hljs.getLanguage(lang));
    const highlighted = validLang
      ? hljs.highlight(code, { language: lang }).value
      : hljs.highlightAuto(code).value;
    return `<pre><code class="hljs ${validLang ? `language-${lang}` : ""}">${highlighted}</code></pre>`;
  },
  html: true,
  linkify: true,
  breaks: true,
  typographer: true,
  tables: true,
});

md.use(markdownItTable);

const CHAT_CONTAINER_SELECTOR = ".content";
const CHAT_EVENTS = ["wheel", "touchstart", "mousedown", "keydown"];

const getChatContainer = () => document.querySelector(CHAT_CONTAINER_SELECTOR);

const forceScrollToBottom = async () => {
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 200));
  const container = getChatContainer();
  if (container) {
    container.scrollTop = container.scrollHeight;
    setTimeout(() => {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: "smooth",
      });
    }, 100);
  }
};

let autoScroll = true;

const scrollToBottom = async () => {
  if (!autoScroll) return;
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 100));
  const container = getChatContainer();
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
};

const scrollToBottomOnClick = async () => {
  autoScroll = true;
  showNewMessageIndicator.value = false;
  await scrollToBottom();
};

const handleUserInteraction = () => {
  autoScroll = false;
  if (isTyping.value) {
    showNewMessageIndicator.value = true;
  }
};

const handleScroll = () => {
  const container = getChatContainer();
  if (!container) return;
  const { scrollTop, scrollHeight, clientHeight } = container;
  if (scrollTop + clientHeight < scrollHeight - 10) {
    autoScroll = false;
    if (isTyping.value) {
      showNewMessageIndicator.value = true;
    }
  } else {
    autoScroll = true;
    showNewMessageIndicator.value = false;
  }
};

const registerChatListeners = () => {
  const container = getChatContainer();
  if (!container) return;
  CHAT_EVENTS.forEach((event) =>
    container.addEventListener(event, handleUserInteraction, { passive: true }),
  );
  container.addEventListener("scroll", handleScroll, { passive: true });
};

const removeChatListeners = () => {
  const container = getChatContainer();
  if (!container) return;
  CHAT_EVENTS.forEach((event) =>
    container.removeEventListener(event, handleUserInteraction),
  );
  container.removeEventListener("scroll", handleScroll);
};

const flushBuffer = () => {
  streamQueue.clear();
};

const onDelta = (delta) => {
  if (!delta) return;
  streamQueue.enqueueContent(delta);
};

const handleStreamFinished = () => {
  isTyping.value = false;
  showNewMessageIndicator.value = false;
};

onMounted(async () => {
  addCopyButtons();
  await forceScrollToBottom();
  registerChatListeners();
  
  streamQueue.setCallbacks((delta) => {
    sessionStore.adddelta(delta);
    requestAnimationFrame(() => {
      scrollToBottom();
    });
  });
});

onUpdated(() => {
  addCopyButtons();
});

onBeforeUnmount(() => {
  removeChatListeners();
  streamQueue.destroy();
  if (developerWarningTimer) {
    window.clearTimeout(developerWarningTimer);
  }
});

const triggerDeveloperModeWarning = (text) => {
  if (
    !isDeveloperMode(currentRoleId.value) ||
    !text?.trim() ||
    !isLikelyNonTechnical(text)
  ) {
    return;
  }

  showDeveloperModeWarning.value = true;
  if (developerWarningTimer) {
    window.clearTimeout(developerWarningTimer);
  }
  developerWarningTimer = window.setTimeout(() => {
    showDeveloperModeWarning.value = false;
  }, 3000);
};

const buildMessagesWithSystem = () => {
  const systemPrompt = currentRole.value.systemPrompt;
  const payloadMessages = sessionStore.getMessagesForModel();

  if (payloadMessages.length) {
    payloadMessages.pop();
  }

  return [{ role: "system", content: systemPrompt }, ...payloadMessages];
};

const submit = async ({ attachments = [] } = {}) => {
  const trimmed = msg.value.trim();
  if (!trimmed && !attachments.length) return;

  triggerDeveloperModeWarning(trimmed);

  sessionStore.sessionpush({
    role: "user",
    content: trimmed,
    attachments,
  });
  msg.value = "";
  await scrollToBottom();

  const aiMessage = { role: "assistant", content: "", attachments: [] };
  sessionStore.sessionpush(aiMessage);
  isTyping.value = true;
  autoScroll = true;

  try {
    await chatStream(
      buildMessagesWithSystem(),
      onDelta,
      handleStreamFinished,
      selectedModel.value,
    );
  } catch (error) {
    isTyping.value = false;
    aiMessage.content = "抱歉，回复生成出错";
    showNewMessageIndicator.value = false;
    flushBuffer();
    console.error(error);
  } finally {
    autoScroll = true;
  }
};

const renderMarkdown = (raw) => md.render(raw || "");

const addCopyButtons = () => {
  nextTick(() => {
    const codeBlocks = document.querySelectorAll(
      `${CHAT_CONTAINER_SELECTOR} pre`,
    );
    codeBlocks.forEach((block) => {
      if (block.querySelector(".copy-btn")) return;
      const button = document.createElement("button");
      button.className = "copy-btn";
      button.innerHTML = "复制";
      button.addEventListener("click", () => {
        const code = block.querySelector("code")?.textContent ?? "";
        navigator.clipboard.writeText(code).then(() => {
          button.textContent = "已复制！";
          setTimeout(() => {
            button.textContent = "复制";
          }, 2000);
        });
      });
      block.appendChild(button);
    });
  });
};

const copyMessage = (text) => {
  navigator.clipboard.writeText((text ?? "").trim());
};

const copyMessageMarkdown = (text) => {
  navigator.clipboard.writeText(text ?? "");
};

const handleDeleteMessage = (index) => {
  sessionStore.removeMessageAt(index);
};

const handleRegenerateMessage = async (index) => {
  const target = messages.value[index];
  if (!target || target.role !== "assistant" || isTyping.value) {
    return;
  }

  const userMessage = messages.value[index - 1];
  const userMessageText = userMessage?.content || "";

  sessionStore.trimMessagesFrom(index);

  const aiMessage = { role: "assistant", content: "", attachments: [] };
  sessionStore.sessionpush(aiMessage);
  isTyping.value = true;
  autoScroll = true;

  try {
    triggerDeveloperModeWarning(userMessageText);

    await chatStream(
      buildMessagesWithSystem(),
      onDelta,
      handleStreamFinished,
      selectedModel.value,
    );
  } catch (error) {
    isTyping.value = false;
    aiMessage.content = "抱歉，重新生成时出错";
    showNewMessageIndicator.value = false;
    flushBuffer();
    console.error(error);
  } finally {
    autoScroll = true;
  }
};

const getAssistantAvatar = (roleId) =>
  roleId === "developer" ? assistantAvatarDeveloper : assistantAvatarGeneral;

const avatarForMessage = (item) => {
  if (item.role === "user") {
    return userAvatar;
  }

  return getAssistantAvatar(item.roleId || currentRoleId.value);
};

const assistantNameForMessage = (item) =>
  getRoleById(item.roleId || currentRoleId.value).name;

const isStreamingAssistantMessage = (item, index) =>
  item.role === "assistant" &&
  isTyping.value &&
  index === messages.value.length - 1;

const hasAssistantContent = (item) => !!item.content?.trim();

const shouldShowPendingState = (item, index) =>
  isStreamingAssistantMessage(item, index) &&
  !hasAssistantContent(item);

const pendingStateLabel = (item, index) => {
  if (!isStreamingAssistantMessage(item, index)) {
    return "";
  }

  return "正在生成回复";
};

const shouldShowPendingSkeleton = (item, index) =>
  shouldShowPendingState(item, index) && !hasAssistantContent(item);

const isEditingTitle = ref(false);
const tempTitle = ref("");

const startEditing = () => {
  tempTitle.value = sessionStore.curname;
  isEditingTitle.value = true;
  nextTick(() => {
    document.querySelector(".title-input input")?.focus();
  });
};

const saveTitle = () => {
  if (tempTitle.value.trim()) {
    sessionStore.updateTitle(tempTitle.value.trim());
  }
  isEditingTitle.value = false;
};

const cancelEditing = () => {
  isEditingTitle.value = false;
};

const selecthistory = (name) => {
  flushBuffer();
  sessionStore.selecthistory(name);
};

defineExpose({ selecthistory });
</script>

<template>
  <div class="header">
    <div class="header-title">
      <template v-if="!isEditingTitle">
        {{ sessionStore.curname }}
        <el-icon @click="startEditing"><EditPen /></el-icon>
      </template>
      <template v-else>
        <el-input
          v-model="tempTitle"
          class="title-input"
          size="small"
          @keyup.enter="saveTitle"
          @blur="saveTitle"
        />
        <el-icon @click="cancelEditing"><Close /></el-icon>
      </template>
    </div>

    <el-radio-group
      v-model="selectedRole"
      size="small"
      class="role-selector"
      :disabled="isTyping"
    >
      <el-radio-button
        v-for="role in aiRoles"
        :key="role.id"
        :value="role.id"
      >
        {{ role.name }}
      </el-radio-button>
    </el-radio-group>
    
    <el-select
      v-model="selectedModel"
      size="small"
      class="model-select"
      :disabled="isTyping"
      placeholder="选择模型"
      :teleported="false"
    >
      <el-option
        v-for="option in modelOptions"
        :key="option.value"
        :label="option.label"
        :value="option.value"
      />
    </el-select>
  </div>

  <div class="role-indicator" :class="{ 'is-developer': currentRoleId === 'developer' }">
    <span class="role-indicator__label">当前模式：{{ currentRole.name }}</span>
    <span class="role-indicator__desc">{{ currentRole.description }}</span>
  </div>

  <transition name="warning-fade">
    <el-alert
      v-if="showDeveloperModeWarning"
      title="当前是程序员助手模式"
      type="warning"
      description="这类问题更适合切换到通用助手后继续提问。"
      show-icon
      :closable="true"
      @close="showDeveloperModeWarning = false"
      class="developer-warning"
    />
  </transition>
  
  <DynamicScroller
    class="content"
    :items="messages"
    :min-item-size="120"
    key-field="_key"
    :key="sessionStore.curname"
  >
    <template #default="{ item, index, active }">
      <DynamicScrollerItem
        :item="item"
        :active="active"
        :data-index="index"
        :size-dependencies="[
          item.content,
          shouldShowPendingState(item, index),
          pendingStateLabel(item, index),
        ]"
      >
        <div
          class="message-row"
          :class="item.role === 'user' ? 'is-user' : 'is-assistant'"
        >
          <img
            class="message-avatar"
            :src="avatarForMessage(item)"
            :alt="item.role === 'user' ? '用户头像' : 'AI头像'"
          />
          <div
            class="message"
            :class="[
              item.role === 'user' ? 'user-message' : 'assistant-message',
              { 'is-pending': shouldShowPendingState(item, index) },
            ]"
          >
            <div class="message-header">
              <span class="message-role">
                {{ item.role === 'user' ? '我' : assistantNameForMessage(item) }}
              </span>
              <div class="message-actions">
                <el-tooltip content="复制纯文本" placement="top">
                  <button @click="copyMessage(item.content)" class="action-btn">
                    <el-icon><CopyDocument /></el-icon>
                  </button>
                </el-tooltip>
                <el-tooltip
                  v-if="item.role === 'assistant'"
                  content="复制全文"
                  placement="top"
                >
                  <button
                    @click="copyMessageMarkdown(item.content)"
                    class="action-btn"
                  >
                    <el-icon><DocumentCopy /></el-icon>
                  </button>
                </el-tooltip>
                <el-tooltip
                  v-if="item.role === 'assistant'"
                  content="重新回复"
                  placement="top"
                >
                  <button @click="handleRegenerateMessage(index)" class="action-btn">
                    <el-icon><RefreshRight /></el-icon>
                  </button>
                </el-tooltip>
                <el-tooltip content="删除此消息" placement="top">
                  <button @click="handleDeleteMessage(index)" class="action-btn">
                    <el-icon><Delete /></el-icon>
                  </button>
                </el-tooltip>
              </div>
            </div>

            <div
              v-if="shouldShowPendingState(item, index)"
              class="pending-state"
            >
              <span class="pending-state__label">
                {{ pendingStateLabel(item, index) }}
              </span>
              <span class="pending-state__dots" aria-hidden="true">
                <span></span>
                <span></span>
                <span></span>
              </span>
            </div>

            <div
              v-if="shouldShowPendingSkeleton(item, index)"
              class="pending-skeleton"
              aria-hidden="true"
            >
              <span class="pending-skeleton__line first"></span>
              <span class="pending-skeleton__line second"></span>
            </div>

            <div class="message-body" v-html="renderMarkdown(item.content)"></div>

            <AttachmentPreview
              v-if="item.attachments?.length"
              :attachments="item.attachments"
            />
          </div>
        </div>
      </DynamicScrollerItem>
    </template>
  </DynamicScroller>

  <ChatInput v-model:msg="msg" v-model:isTyping="isTyping" @submit="submit" />

  <div
    v-if="showNewMessageIndicator"
    class="new-message-indicator"
    @click="scrollToBottomOnClick"
  >
    新消息
  </div>
</template>

<style scoped>
.header {
  padding: 20px 24px;
  background: var(--color-panel);
  border-bottom: 1px solid var(--color-border);
  font-size: 16px;
  font-weight: 600;
  color: var(--color-heading);
  display: flex;
  align-items: center;
  gap: 16px;
  position: relative;
}

.header::after {
  content: '';
  position: absolute;
  left: 24px;
  right: 24px;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--color-border), transparent);
  opacity: 0.5;
}

.header-title {
  flex: 1;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-heading);
  letter-spacing: 0.2px;
}

.header-title .el-icon {
  padding: 6px;
  border-radius: 8px;
  background: var(--color-input-background);
  color: var(--color-muted);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.header-title .el-icon:hover {
  background: var(--color-toolbar-hover-bg);
  color: var(--color-text-primary);
  transform: scale(1.05);
}

.title-input {
  width: 220px;
  max-width: 60%;
}

.title-input :deep(.el-input__wrapper) {
  border-radius: 10px;
  background: var(--color-input-background);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-soft);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  padding: 6px 12px;
}

.title-input :deep(.el-input__wrapper:hover) {
  border-color: var(--color-accent);
  box-shadow: var(--shadow-medium);
}

.title-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1), var(--shadow-medium);
}

.title-input :deep(.el-input__inner) {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.role-selector {
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow-soft);
}

.role-selector :deep(.el-radio-button__inner) {
  border: none;
  background: var(--color-input-background);
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 500;
  padding: 8px 16px;
  transition: all 0.2s ease;
}

.role-selector :deep(.el-radio-button__inner:hover) {
  color: var(--color-text-primary);
  background: var(--color-toolbar-hover-bg);
}

.role-selector :deep(.el-radio-button__orig-radio:checked + .el-radio-button__inner),
.role-selector :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: var(--color-accent);
  color: var(--color-accent-contrast);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.2);
}

.model-select {
  width: 160px;
}

.model-select :deep(.el-select__wrapper) {
  border-radius: 12px;
  background: var(--color-input-background);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-soft);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.model-select :deep(.el-select__wrapper:hover) {
  border-color: var(--color-accent);
  box-shadow: var(--shadow-medium);
}

.model-select :deep(.el-select__wrapper.is-focused) {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1), var(--shadow-medium);
}

.model-select :deep(.el-select__placeholder) {
  color: var(--color-muted);
}

.model-select :deep(.el-input__inner) {
  color: var(--color-text-primary);
  font-size: 13px;
  font-weight: 500;
}

.role-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-panel);
  color: var(--color-text-secondary);
  font-size: 13px;
}

.role-indicator::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #10b981;
  flex: 0 0 auto;
}

.role-indicator.is-developer::before {
  background: #2563eb;
}

.role-indicator__label {
  font-weight: 600;
  color: var(--color-text-primary);
}

.role-indicator__desc {
  color: var(--color-muted);
}

.developer-warning {
  margin: 12px 24px 0;
}

.warning-fade-enter-active,
.warning-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.warning-fade-enter-from,
.warning-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.content {
  flex: 1;
  overflow-y: auto;
  background: var(--color-panel-alt);
  padding: 32px 12%;
}

.message-row {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 48px;
}

.message-row.is-user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  background: var(--color-surface);
  padding: 8px;
  box-shadow: var(--shadow-medium);
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.message-row:hover .message-avatar {
  transform: scale(1.05);
  box-shadow: var(--shadow-strong);
}

.message {
  max-width: 70%;
  width: fit-content;
  padding: 18px 22px;
  margin-bottom: 24px;
  border-radius: 20px;
  position: relative;
  box-shadow: var(--shadow-soft);
  animation: messageSlideIn 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  word-break: break-word;
  color: var(--color-text-primary);
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.message:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-medium);
}

.message.user-message {
  background: linear-gradient(135deg, var(--color-bubble-user) 0%, var(--color-accent-strong) 100%);
  color: var(--color-accent-contrast);
  border: none;
  box-shadow: var(--shadow-medium);
}

.message.user-message:hover {
  box-shadow: var(--shadow-strong);
}

.message.assistant-message {
  background: var(--color-elevated-surface);
  color: var(--color-text-primary);
}

.message.assistant-message.is-pending {
  border-color: rgba(37, 99, 235, 0.18);
  box-shadow:
    0 0 0 1px rgba(37, 99, 235, 0.05),
    var(--shadow-medium);
}

.message-row.is-user .message-actions .action-btn {
  color: rgba(249, 250, 251, 0.8);
}

.message-row.is-user .message-actions .action-btn:hover {
  color: var(--color-accent-contrast);
}

.message-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.message-role {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: inherit;
}

.message-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.action-btn {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--color-muted);
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.action-btn:hover {
  background: var(--color-toolbar-hover-bg);
  color: var(--color-text-primary);
}

.message-row.is-user .action-btn:hover {
  background: rgba(255, 255, 255, 0.12);
}

.pending-state {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 8px 12px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.08), rgba(37, 99, 235, 0.03));
  border: 1px solid rgba(37, 99, 235, 0.12);
  color: var(--color-text-secondary);
}

.pending-state__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.pending-state__dots {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.pending-state__dots span {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--color-accent);
  opacity: 0.3;
  animation: thinkingDots 1.2s ease-in-out infinite;
}

.pending-state__dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.pending-state__dots span:nth-child(3) {
  animation-delay: 0.4s;
}

.pending-skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 4px;
}

.pending-skeleton__line {
  display: block;
  height: 10px;
  border-radius: 999px;
  background: linear-gradient(
    90deg,
    rgba(148, 163, 184, 0.14) 0%,
    rgba(148, 163, 184, 0.32) 50%,
    rgba(148, 163, 184, 0.14) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.4s linear infinite;
}

.pending-skeleton__line.first {
  width: min(280px, 100%);
}

.pending-skeleton__line.second {
  width: min(180px, 72%);
}

.message-body :deep(p) {
  margin: 0.5em 0;
}

.message-body :deep(a) {
  color: var(--color-link);
}

.message-body :deep(a:hover) {
  text-decoration: underline;
  color: var(--color-link-hover);
}

.message-body :deep(code:not(.hljs)) {
  background: var(--color-code-surface);
  padding: 0.2em 0.4em;
  border-radius: 4px;
}

.content :deep(pre) {
  position: relative;
  background: var(--color-code-surface);
  border: 1px solid var(--color-code-border);
  border-radius: 10px;
  padding: 16px;
  margin: 16px 0;
  overflow-x: auto;
}

.content :deep(code.hljs) {
  background: transparent;
  padding: 0;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 14px;
  color: var(--color-text-primary);
}

.content :deep(pre)::before {
  content: "代码";
  display: block;
  font-size: 12px;
  color: var(--color-code-label);
  margin-bottom: 8px;
}

.content :deep(.copy-btn) {
  position: absolute;
  top: 10px;
  right: 10px;
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--color-copy-button-bg);
  color: var(--color-accent-contrast);
  border: none;
  cursor: pointer;
  font-size: 12px;
}

.content :deep(.copy-btn:hover) {
  background: var(--color-copy-button-hover);
}

.new-message-indicator {
  position: fixed;
  bottom: 80px;
  right: 24px;
  background: var(--color-new-indicator-bg);
  color: var(--color-accent-contrast);
  padding: 8px 18px;
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
  box-shadow: var(--shadow-strong);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.new-message-indicator:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-strong);
}

@keyframes messageSlideIn {
  from {
    opacity: 0;
    transform: translateY(20px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes thinkingDots {
  0%,
  80%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.vue-recycle-scroller__item-view {
  margin: 0 !important;
}

.content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
  background: var(--color-table-bg);
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--color-table-border);
  font-size: 14px;
}

.content :deep(th),
.content :deep(td) {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid var(--color-table-border);
}

.content :deep(th) {
  background: var(--color-table-header-bg);
  font-weight: 600;
  color: var(--color-heading);
}

.content :deep(tr:last-child td) {
  border-bottom: none;
}

::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: var(--color-scroll-track);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb {
  background: var(--color-scroll-thumb);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--color-scroll-thumb-hover);
}

@media (max-width: 960px) {
  .content {
    padding: 24px 24px;
  }

  .message {
    max-width: 85%;
  }
}

@media (max-width: 640px) {
  .header {
    flex-wrap: wrap;
  }

  .role-indicator {
    align-items: flex-start;
    flex-direction: column;
  }

  .content {
    padding: 20px 16px;
  }

  .message-row {
    gap: 12px;
  }

  .message {
    max-width: 100%;
  }

  .pending-state {
    width: 100%;
    justify-content: space-between;
  }
}

@media (max-width: 480px) {
  .header {
    padding: 14px 18px;
    font-size: 16px;
  }

  .title-input {
    width: 180px;
  }

  .content {
    padding: 18px 12px;
  }

  .developer-warning {
    margin: 10px 12px 0;
  }

  .message-avatar {
    width: 36px;
    height: 36px;
    padding: 4px;
  }

  .message {
    padding: 14px 16px;
  }

  .message-actions {
    gap: 4px;
  }
}
</style>
