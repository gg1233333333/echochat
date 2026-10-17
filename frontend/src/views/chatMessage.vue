<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  CopyDocument,
  Close,
  Delete,
  RefreshRight,
  DocumentCopy,
  ArrowRight,
  MoreFilled,
  Menu,
  Check,
} from "@element-plus/icons-vue";
import { DynamicScroller, DynamicScrollerItem } from "vue-virtual-scroller";
import { renderMarkdown, markdownPlainText } from "@/utils/markdown";
import AttachmentPreview from "@/components/chat/AttachmentPreview.vue";
import ChatInput from "@/components/chat/ChatInput.vue";
import ToolActivity from "@/components/chat/ToolActivity.vue";
import ConversationNavigator from "@/components/chat/ConversationNavigator.vue";
import { useSessionStore } from "@/stores/session";
import { useStreamingDisplay } from "@/composables/useStreamingDisplay";
import { useConversationNavigation } from "@/composables/useConversationNavigation";
import assistantAvatarGeneral from "@/assets/avatars/assistant.svg";

defineOptions({ name: "ChatMessage" });
defineProps({ sidebarOpen: Boolean, brandInHeader: Boolean });
const emit = defineEmits(["toggle-sidebar"]);
const store = useSessionStore();
const scroller = ref(null);
const autoScroll = ref(true);
const navigationPaused = ref(false);
const showNewMessageIndicator = ref(false);
const isEditingTitle = ref(false);
const titleButton = ref(null);
const editingId = ref(null);
const tempTitle = ref("");
const savingTitle = ref(false);
const expandedReasoning = ref({});
const toolLayoutRevision = ref({});
const onToolLayout = (id) => {
  toolLayoutRevision.value[id] = (toolLayoutRevision.value[id] || 0) + 1;
  onMeasuredLayout();
};
const messages = computed(() => store.messages);
const presentation = useStreamingDisplay({
  messages,
  currentId: computed(() => store.currentId),
  activeGeneration: computed(() => store.activeGeneration),
});
const navigation = useConversationNavigation({
  messages,
  currentId: computed(() => store.currentId),
  scroller,
  onNavigate: () => {
    navigationPaused.value = true;
    autoScroll.value = false;
    showNewMessageIndicator.value = true;
  },
});
const isEmpty = computed(() => !messages.value.length);
const selectedModel = computed({ get: () => store.model, set: store.setModel });
const activeHere = computed(() => store.activeGeneration?.conversationId === store.currentId);
const scrollToBottom = async () => {
  if (!autoScroll.value) return;
  await nextTick();
  if (!autoScroll.value) return;
  const element = scroller.value?.$el;
  if (element) element.scrollTop = element.scrollHeight;
};
const onMeasuredLayout = () => {
  navigation.onUpdate();
  if (autoScroll.value) void scrollToBottom();
};
const onScrollerUpdate = (...indices) => {
  navigation.onUpdate(...indices);
  if (autoScroll.value) void scrollToBottom();
};
const resumeScrollTracking = () => {
  navigation.cancelNavigation();
  navigationPaused.value = false;
};
const onScrollKey = (event) => {
  if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(event.key))
    resumeScrollTracking();
};
const onScroll = () => {
  if (navigationPaused.value) return;
  const element = scroller.value?.$el;
  if (!element) return;
  autoScroll.value = element.scrollHeight - element.scrollTop - element.clientHeight < 40;
  showNewMessageIndicator.value = !autoScroll.value;
};
const scrollToBottomOnClick = () => {
  resumeScrollTracking();
  autoScroll.value = true;
  showNewMessageIndicator.value = false;
  scrollToBottom();
};
watch(
  () => store.currentId,
  () => {
    navigationPaused.value = false;
    autoScroll.value = true;
    showNewMessageIndicator.value = false;
    scrollToBottom();
  },
);
watch(
  () => [
    messages.value.length,
    messages.value.at(-1) && presentation.contentFor(messages.value.at(-1)),
    messages.value.at(-1) && presentation.reasoningFor(messages.value.at(-1)),
  ],
  () => {
    if (autoScroll.value) scrollToBottom();
    else if (activeHere.value) showNewMessageIndicator.value = true;
  },
  { flush: "post" },
);
const loadOlder = async () => {
  resumeScrollTracking();
  const element = scroller.value?.$el;
  const previousHeight = element?.scrollHeight || 0;
  autoScroll.value = false;
  try {
    await store.loadMessages(store.currentId, true);
    await nextTick();
    if (element) element.scrollTop += element.scrollHeight - previousHeight;
  } catch (error) {
    store.reportError(error);
  }
};
const submit = () => {
  resumeScrollTracking();
  autoScroll.value = true;
  store.send().catch(store.reportError);
};
const copy = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制");
  } catch {
    ElMessage.error("复制失败，请检查浏览器剪贴板权限");
  }
};
const copyCode = (event) => {
  const button = event.target.closest(".copy-btn");
  if (!button) return;
  const row = button.closest("[data-message-id]");
  const item = messages.value.find((message) => message.id === row?.dataset.messageId);
  if (!item) {
    ElMessage.error("无法获取这段代码，请重新打开回复后再试");
    return;
  }
  const index = [...row.querySelectorAll(".message-body .copy-btn")].indexOf(button);
  const received = document.createElement("div");
  received.innerHTML = renderMarkdown(item.content);
  const code = received.querySelectorAll("pre code")[index];
  if (code) copy(code.textContent);
  else ElMessage.error("无法获取这段代码，请重新打开回复后再试");
};
const deleteMessage = async (item) => {
  try {
    await ElMessageBox.confirm("删除这条消息？此操作无法恢复。", "删除消息", {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
    });
  } catch {
    return;
  }
  store.deleteMessage(item).catch(store.reportError);
};
const regenerate = async (item) => {
  if (store.isGenerating) return;
  const following = messages.value.filter((message) => message.seq > item.seq).length;
  if (following) {
    try {
      await ElMessageBox.confirm(
        `重新回复会替换此回复，并删除其后的 ${following} 条消息。是否继续？`,
        "重新回复",
        {
          confirmButtonText: "重新回复",
          cancelButtonText: "取消",
          type: "warning",
        },
      );
    } catch {
      return;
    }
  }
  resumeScrollTracking();
  autoScroll.value = true;
  store.regenerate(item).catch(store.reportError);
};
const messageCommand = (command, item) => {
  if (command === "markdown") copy(item.content);
  else if (command === "delete") deleteMessage(item);
};
const pending = (item) => item.status === "generating" && !presentation.contentFor(item);
const statusLabel = (item) => {
  if (item.status === "failed") return item.error_message || "生成失败，可重新回复";
  if (item.status === "cancelled") return "已停止，保留部分回复";
  if (item.status === "interrupted") return "生成中断，可重新回复";
  if (item.finish_reason === "length") return "回复达到长度上限，内容可能不完整";
  if (item.finish_reason === "content_filter") return "回复受到内容限制";
  if (item.finish_reason && item.finish_reason !== "stop") return `结束原因：${item.finish_reason}`;
  return "";
};
const startEditing = () => {
  if (!store.currentConversation) return;
  tempTitle.value = store.currentConversation.title;
  editingId.value = store.currentId;
  isEditingTitle.value = true;
  nextTick(() => document.querySelector(".title-input input")?.focus());
};
const focusTitle = async () => {
  await nextTick();
  titleButton.value?.focus({ preventScroll: true });
};
const cancelTitleEditing = () => {
  isEditingTitle.value = false;
  void focusTitle();
};
const saveTitle = async (event) => {
  if (event?.isComposing || event?.keyCode === 229) return;
  if (event?.type === "keydown") event.preventDefault();
  if (savingTitle.value || !isEditingTitle.value) return;
  if (!tempTitle.value.trim()) {
    ElMessage.warning("标题不能为空");
    return;
  }
  savingTitle.value = true;
  try {
    await store.renameConversation(editingId.value, tempTitle.value.trim());
    const restoreFocus = event?.type !== "blur" && document.activeElement?.closest(".title-input");
    isEditingTitle.value = false;
    if (restoreFocus) await focusTitle();
  } catch (error) {
    store.reportError(error);
  } finally {
    savingTitle.value = false;
  }
};
defineExpose({ selecthistory: (id) => store.selectConversation(id).catch(store.reportError) });
</script>

<template>
  <section class="chat-view" :class="{ 'has-messages': !isEmpty }">
    <header class="header" :class="{ 'is-editing-title': isEditingTitle }">
      <button
        class="title-action sidebar-toggle"
        aria-label="切换会话列表"
        :title="sidebarOpen ? '收起侧栏' : '展开侧栏'"
        :aria-expanded="sidebarOpen"
        @click="emit('toggle-sidebar')"
      >
        <el-icon :size="20"><Menu /></el-icon>
      </button>
      <div v-show="brandInHeader" id="echo-header-brand" class="header-brand-dock"></div>
      <div class="header-title">
        <template v-if="!isEditingTitle">
          <button
            ref="titleButton"
            class="header-title-text title-rename"
            aria-label="重命名对话"
            title="重命名对话"
            :disabled="!store.currentConversation"
            @click="startEditing"
          >
            {{ store.currentConversation?.title || "EchoChat" }}
          </button>
        </template>
        <template v-else>
          <el-input
            v-model="tempTitle"
            class="title-input"
            size="small"
            aria-label="对话标题"
            @keydown.enter="saveTitle"
            @keydown.esc.prevent="cancelTitleEditing"
            @blur="saveTitle"
          />
          <button
            class="title-action"
            aria-label="取消重命名"
            @mousedown.prevent
            @click="cancelTitleEditing"
          >
            <el-icon :size="16"><Close /></el-icon>
          </button>
        </template>
      </div>
      <el-select
        v-model="selectedModel"
        class="model-select"
        popper-class="echo-mode-popper"
        :show-arrow="false"
        :disabled="store.isGenerating || !store.ready"
        aria-label="回答方式"
        placeholder="回答方式"
      >
        <el-option
          v-for="option in store.options?.modes || []"
          :key="option.value"
          :label="option.label"
          :value="option.value"
          class="mode-option"
        >
          <div class="mode-option__copy">
            <span class="mode-option__label">{{ option.label }}</span>
            <small class="mode-option__description">{{
              option.value === "thinking"
                ? "适合复杂问题，先思考再回答"
                : "适合日常问答，更快给出回复"
            }}</small>
          </div>
          <el-icon
            v-if="selectedModel === option.value"
            class="mode-option__check"
            aria-hidden="true"
            ><Check
          /></el-icon>
        </el-option>
      </el-select>
      <div v-show="!isEmpty" id="echo-navigation-dock" class="conversation-navigation-dock"></div>
    </header>
    <el-alert
      v-if="store.error"
      :title="store.error"
      type="error"
      show-icon
      class="connection-error"
      @close="store.error = ''"
    >
      <el-button
        v-if="!store.ready"
        text
        :loading="store.loading"
        @click="store.initialize().catch(store.reportError)"
        >重新连接</el-button
      >
    </el-alert>
    <div v-if="store.isGenerating && !activeHere" class="generation-notice">
      其他对话正在生成回复，点击“停止”可结束该回复。
    </div>
    <div v-if="store.pages[store.currentId]?.has_more" class="history-controls">
      <el-button text :loading="store.pages[store.currentId]?.loading" @click="loadOlder"
        >加载更早消息</el-button
      >
    </div>
    <div class="chat-body" :class="{ 'is-empty': isEmpty }">
      <ConversationNavigator
        v-if="!isEmpty"
        :key="store.currentId"
        :entries="navigation.entries.value"
        :active-id="navigation.activeId.value"
        @select="navigation.navigate"
      />
      <div v-if="isEmpty" class="chat-empty">
        <div class="empty-brand" aria-hidden="true">
          <img :src="assistantAvatarGeneral" alt="" />
        </div>
        <h1>今天，想一起解决什么？</h1>
        <p>写下问题、分享内容，或一起把想法理清楚。</p>
      </div>
      <DynamicScroller
        v-if="!isEmpty"
        ref="scroller"
        class="content"
        :items="messages"
        :min-item-size="90"
        :emit-update="true"
        key-field="id"
        :key="store.currentId"
        @scroll.passive="onScroll"
        @wheel.passive="resumeScrollTracking"
        @touchmove.passive="resumeScrollTracking"
        @pointerdown="resumeScrollTracking"
        @keydown="onScrollKey"
        @resize="onMeasuredLayout"
        @update="onScrollerUpdate"
        @click="copyCode"
      >
        <template #default="{ item, index, active }">
          <DynamicScrollerItem
            :item="item"
            :active="active"
            :emit-resize="true"
            @resize="onMeasuredLayout"
            :data-index="index"
            :size-dependencies="[
              presentation.contentFor(item),
              presentation.reasoningFor(item),
              expandedReasoning[item.id],
              item.status,
              item.error_message,
              item.tool_calls,
              toolLayoutRevision[item.id],
              item.artifacts?.length,
            ]"
          >
            <div
              class="message-row"
              :class="item.role === 'user' ? 'is-user' : 'is-assistant'"
              :data-message-id="item.id"
            >
              <img
                v-if="item.role === 'assistant'"
                class="message-avatar"
                :src="assistantAvatarGeneral"
                alt="AI头像"
              />
              <div
                class="message"
                :class="item.role === 'user' ? 'user-message' : 'assistant-message'"
                :data-revealing="presentation.isRevealing(item) || undefined"
              >
                <div
                  v-if="item.role === 'assistant' && item.reasoning_content"
                  class="reasoning-panel"
                >
                  <button
                    class="reasoning-toggle"
                    type="button"
                    :aria-expanded="!!expandedReasoning[item.id]"
                    :aria-controls="`reasoning-${item.id}`"
                    @click="expandedReasoning[item.id] = !expandedReasoning[item.id]"
                  >
                    <el-icon :class="{ 'is-expanded': expandedReasoning[item.id] }"
                      ><ArrowRight /></el-icon
                    ><span>思考过程</span>
                  </button>
                  <div
                    v-if="expandedReasoning[item.id]"
                    :id="`reasoning-${item.id}`"
                    class="reasoning-content"
                  >
                    {{ presentation.reasoningFor(item) }}
                  </div>
                </div>
                <ToolActivity v-if="item.role === 'assistant'" :calls="item.tool_calls"
                  :artifacts="item.artifacts" :run-id="item.run_id" @resize="onToolLayout(item.id)" />
                <div v-if="pending(item) && !item.tool_calls?.length" class="pending-state">
                  <span>{{ item.reasoning_content ? "等待回答" : "等待回复" }}</span
                  ><span class="pending-state__dots" aria-hidden="true"
                    ><span></span><span></span><span></span
                  ></span>
                </div>
                <div class="message-body" v-html="presentation.htmlFor(item)"></div>
                <p
                  v-if="item.status === 'generating' && item.content"
                  class="streaming-state"
                  role="status"
                >
                  <span class="generation-dot" aria-hidden="true"></span>正在生成
                </p>
                <p
                  v-if="item.role === 'assistant' && statusLabel(item)"
                  class="message-status"
                  :class="{ 'is-error': item.status === 'failed' }"
                  role="status"
                >
                  {{ statusLabel(item) }}
                </p>
                <AttachmentPreview
                  v-if="item.attachments?.length"
                  :attachments="item.attachments"
                />
                <div class="message-actions">
                  <el-tooltip content="复制纯文本" placement="top"
                    ><button
                      class="action-btn"
                      aria-label="复制纯文本"
                      @click="copy(markdownPlainText(item.content))"
                    >
                      <el-icon><CopyDocument /></el-icon></button
                  ></el-tooltip>
                  <el-tooltip v-if="item.role === 'assistant'" content="重新回复" placement="top"
                    ><button
                      class="action-btn"
                      aria-label="重新回复"
                      :disabled="
                        store.isGenerating || !item.related_user_message_id || !item.context_segment
                      "
                      @click="regenerate(item)"
                    >
                      <el-icon><RefreshRight /></el-icon></button
                  ></el-tooltip>
                  <el-dropdown
                    trigger="click"
                    @command="(command) => messageCommand(command, item)"
                  >
                    <button class="action-btn" aria-label="更多消息操作" title="更多消息操作">
                      <el-icon><MoreFilled /></el-icon>
                    </button>
                    <template #dropdown
                      ><el-dropdown-menu>
                        <el-dropdown-item
                          v-if="item.role === 'assistant'"
                          command="markdown"
                          :icon="DocumentCopy"
                          >复制 Markdown</el-dropdown-item
                        >
                        <el-dropdown-item command="delete" :icon="Delete"
                          >删除此消息</el-dropdown-item
                        >
                      </el-dropdown-menu></template
                    >
                  </el-dropdown>
                </div>
              </div>
            </div>
          </DynamicScrollerItem>
        </template>
      </DynamicScroller>
      <div v-show="isEmpty" id="echo-chat-suggestions" class="chat-suggestions"></div>
    </div>
    <div v-show="showNewMessageIndicator" class="latest-marker">
      <button class="new-message-indicator" @click="scrollToBottomOnClick">回到最新</button>
    </div>
    <ChatInput @submit="submit" />
  </section>
</template>

<style scoped>
.chat-view {
  position: relative;
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}
.header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
  height: var(--chat-header-height);
  padding: 0 var(--chat-gutter);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-panel);
}
.header-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  flex: 1;
  color: var(--color-heading);
}
.header-brand-dock {
  width: 22px;
  flex-shrink: 0;
}
.conversation-navigation-dock {
  display: none;
}
.header-title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 16px;
  font-weight: 550;
}
.title-rename {
  appearance: none;
  min-width: 0;
  max-width: 100%;
  padding: var(--space-1) var(--space-2);
  margin-left: calc(var(--space-2) * -1);
  border: 0;
  border-radius: var(--radius-control);
  color: inherit;
  background: transparent;
  box-shadow: none;
  text-align: left;
  cursor: pointer;
  transition: background var(--motion-fast);
}
.title-rename:hover,
.title-rename:focus-visible {
  background: var(--color-panel-alt);
}
.title-rename:disabled {
  cursor: default;
}
.title-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  padding: 0;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    color var(--motion-fast),
    background var(--motion-fast);
}
.title-action:hover,
.title-action:focus-visible {
  background: var(--color-panel-alt);
  color: var(--color-text-primary);
}
.title-input {
  max-width: 360px;
}
.model-select {
  width: 136px;
  flex-shrink: 0;
}
.model-select :deep(.el-select__wrapper) {
  min-height: 36px;
  border-radius: var(--radius-control);
  background: var(--color-input-background);
  box-shadow: 0 0 0 1px var(--color-border-strong) inset;
}
.model-select :deep(.el-select__wrapper.is-focused) {
  box-shadow:
    0 0 0 1px var(--color-accent) inset,
    0 0 0 3px color-mix(in srgb, var(--color-accent) 12%, transparent);
}
.model-select :deep(.el-select__selected-item) {
  color: var(--color-text-primary);
  font-size: 13px;
}
.model-select :deep(.el-select__caret) {
  color: var(--color-accent);
}
.model-select :deep(.el-select__wrapper.is-disabled) {
  opacity: 0.5;
}
.connection-error {
  flex-shrink: 0;
  margin: var(--space-2) var(--chat-gutter) 0;
  width: auto;
}
.generation-notice {
  padding: var(--space-2) var(--chat-gutter);
  color: var(--color-text-secondary);
  font-size: 13px;
}
.history-controls {
  text-align: center;
}
.chat-body {
  display: flex;
  position: relative;
  flex: 1;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
}
.chat-body.is-empty {
  justify-content: safe center;
  gap: var(--space-6);
  overflow-y: auto;
  padding-block: var(--space-12);
}
.chat-empty {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  width: calc(100% - var(--chat-gutter) * 2);
  max-width: var(--chat-column-width);
  margin: 0 auto;
  text-align: center;
}
.empty-brand {
  display: grid;
  place-items: center;
  position: relative;
  width: 72px;
  height: 72px;
  margin-bottom: var(--space-3);
}
.empty-brand::before {
  content: "";
  position: absolute;
  inset: 10px -5px;
  border: 1px solid color-mix(in srgb, var(--color-accent) 22%, transparent);
  border-radius: 50%;
  transform: rotate(-23deg);
}
.empty-brand::after {
  content: "";
  position: absolute;
  inset: 9px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--color-brand-mint) 12%, transparent);
  filter: blur(14px);
}
.empty-brand img {
  width: 64px;
  height: 64px;
  position: relative;
  z-index: 1;
}
.chat-empty h1 {
  font-size: clamp(32px, 2.5vw, 36px);
  font-weight: 600;
  line-height: 1.4;
  color: var(--color-heading);
}
.chat-empty p {
  color: var(--color-text-secondary);
  font-size: 15px;
  line-height: 1.75;
}
.chat-suggestions {
  width: calc(100% - var(--chat-gutter) * 2);
  max-width: var(--chat-column-width);
  margin: 0 auto;
}
.content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-8) 0 var(--space-2);
}
.message-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  width: calc(100% - var(--chat-gutter) * 2);
  max-width: var(--chat-column-width);
  margin: 0 auto;
  padding-bottom: var(--space-8);
}
.message-row.is-user {
  justify-content: flex-end;
  padding-bottom: var(--space-6);
}
.message-avatar {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  margin-top: 2px;
  padding: 2px;
  border-radius: var(--radius-control);
  background: var(--color-panel-alt);
}
.message {
  min-width: 0;
  color: var(--color-text-primary);
  overflow-wrap: anywhere;
}
.assistant-message {
  flex: 1;
}
.user-message {
  max-width: 70%;
}
.user-message .message-body {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-message);
  background: var(--color-toolbar-bg);
}
.user-message .message-actions {
  justify-content: flex-end;
}
.message-body {
  font-size: 16px;
  line-height: 1.75;
}
.message-body :deep(p) {
  margin: 0 0 var(--space-3);
}
.message-body :deep(p:last-child) {
  margin-bottom: 0;
}
.message-body :deep(h1),
.message-body :deep(h2),
.message-body :deep(h3) {
  margin: var(--space-6) 0 var(--space-3);
  line-height: 1.4;
  font-weight: 600;
}
.message-body :deep(h1) {
  font-size: 24px;
}
.message-body :deep(h2) {
  font-size: 21px;
}
.message-body :deep(h3) {
  font-size: 18px;
}
.message-body :deep(h1:first-child),
.message-body :deep(h2:first-child),
.message-body :deep(h3:first-child) {
  margin-top: 0;
}
.message-body :deep(ul),
.message-body :deep(ol) {
  padding-left: 1.5em;
  margin: var(--space-3) 0;
}
.message-body :deep(li) {
  margin-bottom: var(--space-1);
}
.message-body :deep(strong) {
  font-weight: 600;
}
.message-body :deep(a) {
  color: var(--color-link);
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.message-body :deep(a:hover) {
  color: var(--color-accent-strong);
}
.message-body :deep(blockquote) {
  margin: var(--space-4) 0;
  padding: var(--space-2) var(--space-4);
  border-left: 2px solid var(--color-border-strong);
  border-radius: 0 var(--radius-control) var(--radius-control) 0;
  background: var(--color-panel-alt);
  color: var(--color-text-secondary);
}
.message-body :deep(blockquote p:last-child) {
  margin-bottom: 0;
}
.message-body :deep(code:not(.hljs)) {
  padding: 0.15em 0.35em;
  border-radius: var(--space-1);
  background: var(--color-panel-alt);
  font-size: 0.9em;
}
.content :deep(pre) {
  position: relative;
  max-width: 100%;
  margin: var(--space-4) 0;
  padding: var(--space-4);
  border: 1px solid var(--color-code-border);
  border-radius: var(--radius-list);
  overflow-x: auto;
  background: var(--color-code-surface);
  color: var(--color-code-text);
}
.content :deep(code.hljs) {
  display: block;
  padding: 0;
  background: transparent;
  font-family: Consolas, Menlo, monospace;
  font-size: 14px;
  line-height: 1.65;
  color: var(--color-code-text);
}
.content :deep(.code-language) {
  display: block;
  padding-right: 60px;
  margin-bottom: var(--space-3);
  color: var(--color-code-label);
  font-size: 12px;
  line-height: 20px;
}
.content :deep(.copy-btn) {
  position: absolute;
  top: var(--space-2);
  right: var(--space-2);
  min-height: 28px;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-code-border);
  border-radius: var(--radius-control);
  background: var(--color-code-surface);
  color: var(--color-code-label);
  font-size: 12px;
  cursor: pointer;
}
.content :deep(.copy-btn:hover) {
  color: var(--color-code-text);
  border-color: var(--color-code-label);
}
.content :deep(.hljs-keyword),
.content :deep(.hljs-selector-tag),
.content :deep(.hljs-built_in),
.content :deep(.hljs-title) {
  color: var(--color-code-keyword);
}
.content :deep(.hljs-string),
.content :deep(.hljs-regexp),
.content :deep(.hljs-attribute) {
  color: var(--color-code-string);
}
.content :deep(.hljs-number),
.content :deep(.hljs-literal),
.content :deep(.hljs-symbol),
.content :deep(.hljs-type) {
  color: var(--color-code-number);
}
.content :deep(.hljs-comment),
.content :deep(.hljs-quote) {
  color: var(--color-code-comment);
}
.content :deep(table) {
  display: block;
  max-width: 100%;
  margin: var(--space-4) 0;
  border-collapse: collapse;
  overflow-x: auto;
  font-size: 14px;
}
.content :deep(th),
.content :deep(td) {
  min-width: 10rem;
  overflow-wrap: normal;
  word-break: normal;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-table-border);
  text-align: left;
}
.content :deep(th) {
  background: var(--color-table-header-bg);
  font-weight: 600;
}
.reasoning-panel {
  margin-bottom: var(--space-3);
}
.reasoning-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 32px;
  padding: var(--space-1) var(--space-2);
  margin-left: calc(var(--space-2) * -1);
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.reasoning-toggle:hover {
  background: var(--color-panel-alt);
  color: var(--color-text-primary);
}
.reasoning-toggle .el-icon {
  transition: transform var(--motion-fast);
}
.reasoning-toggle .is-expanded {
  transform: rotate(90deg);
}
.reasoning-content {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-left: 2px solid var(--color-border-strong);
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.message-status,
.streaming-state {
  margin: var(--space-3) 0 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--color-text-secondary);
}
.message-status.is-error {
  color: var(--color-danger);
}
.streaming-state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.generation-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-accent);
  animation: thinkingDots 1.2s ease-in-out infinite;
}
.message-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-1);
  min-height: 32px;
  opacity: 0;
  transition: opacity var(--motion-fast);
}
.message-row:hover .message-actions,
.message-row:focus-within .message-actions {
  opacity: 1;
}
.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 17px;
  cursor: pointer;
  transition:
    color var(--motion-fast),
    background var(--motion-fast);
}
.action-btn:hover,
.action-btn:focus-visible {
  background: var(--color-panel-alt);
  color: var(--color-text-primary);
}
.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.pending-state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 28px;
  color: var(--color-text-secondary);
  font-size: 14px;
}
.pending-state__dots {
  display: flex;
  gap: var(--space-1);
}
.pending-state__dots span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-accent);
  animation: thinkingDots 1.2s ease-in-out infinite;
}
.pending-state__dots span:nth-child(2) {
  animation-delay: 0.2s;
}
.pending-state__dots span:nth-child(3) {
  animation-delay: 0.4s;
}
.latest-marker {
  position: relative;
  height: 0;
  flex-shrink: 0;
  z-index: 1;
}
.new-message-indicator {
  position: absolute;
  right: var(--chat-gutter);
  bottom: var(--space-2);
  min-height: 34px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-input-background);
  color: var(--color-text-primary);
  padding: var(--space-1) var(--space-3);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  box-shadow: var(--shadow-soft);
}
.title-action:focus-visible,
.title-rename:focus-visible,
.action-btn:focus-visible,
.reasoning-toggle:focus-visible,
.new-message-indicator:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
@keyframes thinkingDots {
  0%,
  80%,
  100% {
    opacity: 0.3;
  }
  40% {
    opacity: 1;
  }
}
@media (hover: none) {
  .message-actions {
    opacity: 1;
  }
}
@media (max-width: 767px) {
  .title-action,
  .title-rename,
  .action-btn,
  .reasoning-toggle {
    min-width: 44px;
    min-height: 44px;
  }
  .title-action,
  .action-btn {
    width: 44px;
    height: 44px;
  }
  .title-input :deep(.el-input__wrapper),
  .model-select :deep(.el-select__wrapper) {
    min-height: 44px;
  }
  .content :deep(.copy-btn) {
    min-width: 44px;
    min-height: 44px;
  }
  .content :deep(.code-language) {
    min-height: 36px;
    line-height: 36px;
    margin-bottom: var(--space-2);
  }
  .header {
    gap: var(--space-1);
  }
  .model-select {
    width: 106px;
  }
  .conversation-navigation-dock {
    display: flex;
    flex-shrink: 0;
    width: 44px;
    height: 44px;
  }
  .header.is-editing-title .model-select,
  .header.is-editing-title .conversation-navigation-dock {
    display: none;
  }
  .header-title-text {
    font-size: 15px;
  }
  .chat-body.is-empty {
    gap: var(--space-4);
    padding-block: var(--space-8);
  }
  .chat-empty {
    margin-top: 0;
  }
  .chat-empty h1 {
    max-width: 260px;
    font-size: 28px;
  }
  .chat-empty p {
    max-width: 285px;
    font-size: 14px;
  }
  .empty-brand {
    margin-bottom: var(--space-2);
  }
  .content {
    padding-top: var(--space-6);
  }
  .message-row {
    gap: var(--space-2);
    padding-bottom: var(--space-6);
  }
  .message-avatar {
    width: 24px;
    height: 24px;
  }
  .user-message {
    max-width: 85%;
  }
  .user-message .message-body {
    padding: var(--space-2) var(--space-3);
  }
  .message-actions {
    opacity: 1;
  }
}
@media (max-height: 650px) {
  .chat-body.is-empty {
    padding-block: var(--space-6);
  }
  .chat-empty {
    margin-top: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .pending-state__dots span,
  .generation-dot {
    animation: none;
  }
}
</style>

<style>
.echo-mode-popper.el-popper.is-light {
  width: 280px;
  max-width: calc(100vw - 32px);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-list);
  background: var(--color-elevated-surface);
  box-shadow: var(--shadow-medium);
  overflow: hidden;
}
.echo-mode-popper .el-select-dropdown__list {
  padding: var(--space-2);
}
.echo-mode-popper .el-select-dropdown__item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: auto;
  min-height: 68px;
  padding: var(--space-3);
  border-radius: var(--radius-control);
  color: var(--color-text-primary);
  line-height: 1.5;
  white-space: normal;
  transition:
    background var(--motion-fast),
    box-shadow var(--motion-fast);
}
.echo-mode-popper .el-select-dropdown__item + .el-select-dropdown__item {
  margin-top: var(--space-1);
}
.echo-mode-popper .mode-option__copy {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-1);
}
.echo-mode-popper .mode-option__label {
  font-size: 14px;
  font-weight: 550;
}
.echo-mode-popper .mode-option__description {
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 400;
}
.echo-mode-popper .mode-option__check {
  flex-shrink: 0;
  color: var(--color-toolbar-text);
  font-size: 17px;
}
.echo-mode-popper .el-select-dropdown__item.is-selected {
  color: var(--color-text-primary);
  background: var(--color-toolbar-bg);
}
.echo-mode-popper .el-select-dropdown__item.is-hovering {
  background: var(--color-panel-alt);
  box-shadow: 0 0 0 1px var(--color-border-strong) inset;
}
.echo-mode-popper .el-select-dropdown__item.is-selected.is-hovering {
  background: var(--color-toolbar-hover-bg);
}
</style>
