<script setup>
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, nextTick, ref } from "vue";
import {
  Close,
  ChatDotRound,
  EditPen,
  Delete,
  Moon,
  MoreFilled,
  Plus,
  Search,
  Sunny,
} from "@element-plus/icons-vue";
import { useSessionStore } from "@/stores/session";
import { useThemeStore } from "@/stores/theme";
import BackendSettings from "./BackendSettings.vue";

defineOptions({ name: "ConversationSidebar" });
defineProps({ mobile: Boolean, compact: Boolean, closable: Boolean });
const emit = defineEmits(["callR", "close", "replay-opening", "request-expand"]);
const sessionStore = useSessionStore();
const themeStore = useThemeStore();
const keyword = ref("");
const listRef = ref(null);
const creating = ref(false);
const historyBusy = ref(false);
const isDark = computed(() => themeStore.mode === "dark");
const hasQuery = computed(() => !!keyword.value.trim());
const filteredConversations = computed(() => {
  const query = keyword.value.trim().toLowerCase();
  return sessionStore.visibleConversations.filter(
    (item) => !query || `${item.title} ${item.preview}`.toLowerCase().includes(query),
  );
});
const conversationGroups = computed(() => {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const groups = [
    { label: "今天", items: [] },
    { label: "昨天", items: [] },
    { label: "更早", items: [] },
  ];
  filteredConversations.value.forEach((conversation) => {
    const date = conversation.updated_at ? new Date(conversation.updated_at).toDateString() : "";
    const group = date === today.toDateString() ? 0 : date === yesterday.toDateString() ? 1 : 2;
    groups[group].items.push(conversation);
  });
  return groups.filter((group) => group.items.length);
});
const newChat = async () => {
  if (creating.value) return;
  creating.value = true;
  try {
    const item = await sessionStore.newConversation();
    if (sessionStore.currentId !== item.id) return;
    keyword.value = "";
    emit("close");
    await nextTick();
    if (sessionStore.currentId === item.id) listRef.value?.setScrollTop?.(0);
  } catch (error) {
    sessionStore.reportError(error);
  } finally {
    creating.value = false;
  }
};
const clearHistory = async () => {
  if (!sessionStore.visibleConversations.length || historyBusy.value) return;
  historyBusy.value = true;
  try {
    try {
      await ElMessageBox.confirm("确认清空全部对话记录吗？正在生成的回复会先停止。", "清空历史", {
        confirmButtonText: "清空",
        cancelButtonText: "取消",
        type: "warning",
      });
    } catch {
      return;
    }
    await sessionStore.clear();
    keyword.value = "";
    ElMessage.success("已清空历史对话");
  } catch (error) {
    sessionStore.reportError(error);
  } finally {
    historyBusy.value = false;
  }
};
const deleteHistory = async (item) => {
  if (historyBusy.value) return;
  historyBusy.value = true;
  try {
    try {
      await ElMessageBox.confirm(`确认删除“${item.title}”吗？此操作无法恢复。`, "删除对话", {
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        type: "warning",
      });
    } catch {
      return;
    }
    await sessionStore.deleteConversation(item.id);
    ElMessage.success("对话已删除");
  } catch (error) {
    sessionStore.reportError(error);
  } finally {
    historyBusy.value = false;
  }
};
const renameConversation = async (item) => {
  let value;
  try {
    ({ value } = await ElMessageBox.prompt("请输入新的对话标题", "重命名对话", {
      inputValue: item.title,
      confirmButtonText: "保存",
      cancelButtonText: "取消",
      inputValidator: (text) => !!text?.trim() || "标题不能为空",
    }));
  } catch {
    return;
  }
  try {
    await sessionStore.renameConversation(item.id, value.trim());
    ElMessage.success("标题已更新");
  } catch (error) {
    sessionStore.reportError(error);
  }
};
const conversationCommand = (command, item) => {
  if (command === "rename") renameConversation(item);
  else if (command === "delete") deleteHistory(item);
};
</script>

<template>
  <aside class="sidebar" :class="{ 'is-compact': compact }">
    <div class="brand-row">
      <div id="echo-sidebar-brand" class="brand-dock"></div>
      <span v-if="mobile" class="brand-title">EchoChat</span>
      <button
        v-if="mobile || closable"
        class="icon-button"
        aria-label="关闭侧栏"
        title="关闭侧栏"
        @click="emit('close')"
      >
        <el-icon><Close /></el-icon>
      </button>
    </div>
    <el-button
      type="primary"
      class="new-chat-btn"
      aria-label="新建对话"
      :title="compact ? '新建对话' : undefined"
      :loading="creating"
      :disabled="!sessionStore.ready || creating"
      @click="newChat"
      ><el-icon><Plus /></el-icon><span v-if="!compact">新建对话</span></el-button
    >
    <template v-if="compact">
      <button
        class="icon-button rail-button"
        aria-label="搜索对话"
        title="搜索对话"
        @click="emit('request-expand', 'search')"
      >
        <el-icon><Search /></el-icon>
      </button>
      <button
        class="icon-button rail-button"
        aria-label="历史对话"
        title="历史对话"
        @click="emit('request-expand', 'history')"
      >
        <el-icon><ChatDotRound /></el-icon>
      </button>
      <div class="rail-spacer"></div>
    </template>
    <template v-else>
      <el-input
        v-model="keyword"
        placeholder="搜索对话"
        clearable
        :prefix-icon="Search"
        class="search-input"
        aria-label="搜索对话"
      />
      <div class="history-heading">
        <span>对话</span><span>{{ filteredConversations.length }}</span>
      </div>
      <el-scrollbar ref="listRef" class="conversation-list">
        <section
          v-for="group in conversationGroups"
          :key="group.label"
          class="history-group"
          :aria-label="group.label"
        >
          <h2 class="history-group__heading">{{ group.label }}</h2>
          <div
            v-for="conversation in group.items"
            :key="conversation.id"
            class="conversation-item"
            :class="{ active: conversation.id === sessionStore.currentId }"
          >
            <button
              class="conversation-select"
              :aria-label="conversation.title"
              :aria-current="conversation.id === sessionStore.currentId ? 'page' : undefined"
              @click="emit('callR', conversation.id)"
            >
              <span class="conversation-item__title" :title="conversation.title">{{
                conversation.title
              }}</span>
              <span v-if="hasQuery" class="conversation-item__preview">{{
                conversation.preview
              }}</span>
            </button>
            <el-dropdown
              class="conversation-dropdown"
              trigger="click"
              @command="(command) => conversationCommand(command, conversation)"
              @click.stop
            >
              <button
                class="icon-button conversation-more"
                aria-label="对话操作"
                title="对话操作"
                :disabled="historyBusy"
              >
                <el-icon><MoreFilled /></el-icon>
              </button>
              <template #dropdown
                ><el-dropdown-menu>
                  <el-dropdown-item command="rename" :icon="EditPen">重命名对话</el-dropdown-item>
                  <el-dropdown-item command="delete" :icon="Delete" :disabled="historyBusy"
                    >删除对话</el-dropdown-item
                  >
                </el-dropdown-menu></template
              >
            </el-dropdown>
          </div>
        </section>
        <p v-if="!filteredConversations.length" class="empty-state">
          {{ hasQuery ? "没有找到相关对话" : "对话会保存在这里" }}
        </p>
      </el-scrollbar>
    </template>
    <footer class="sidebar-footer">
      <BackendSettings
        :compact="compact"
        :history-busy="historyBusy"
        @clear-history="clearHistory"
        @replay-opening="emit('replay-opening')"
      />
      <button
        class="icon-button"
        :aria-label="isDark ? '日间模式' : '夜间模式'"
        :title="isDark ? '日间模式' : '夜间模式'"
        @click="themeStore.toggleMode()"
      >
        <el-icon><component :is="isDark ? Sunny : Moon" /></el-icon>
      </button>
    </footer>
  </aside>
</template>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-3) var(--space-3);
  color: var(--color-sidebar-text);
  background: var(--color-sidebar-surface);
  border-radius: inherit;
}
.brand-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 32px;
  margin-bottom: var(--space-2);
  padding: 0 var(--space-2);
}
.brand-dock {
  flex: 1;
  min-width: 0;
}
.brand-dock :deep(.echo-brand) {
  color: var(--color-sidebar-text);
}
.brand-title {
  flex: 1;
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.4px;
}
.new-chat-btn {
  min-height: 44px;
  margin: 0;
  border-color: transparent;
  border-radius: var(--radius-control);
  background: var(--color-accent);
  color: white;
  box-shadow: none;
  font-size: 14px;
  transition:
    background var(--motion-fast),
    transform var(--motion-fast);
}
.new-chat-btn :deep(span) {
  gap: var(--space-2);
}
.new-chat-btn:not(:disabled):hover {
  background: color-mix(in srgb, var(--color-accent) 90%, white);
  transform: translateY(-1px);
}
.new-chat-btn:not(:disabled):active {
  transform: scale(0.98);
}
.new-chat-btn:disabled {
  color: var(--color-sidebar-muted);
  background: var(--color-sidebar-hover);
}
.search-input :deep(.el-input__wrapper) {
  min-height: 36px;
  border-radius: var(--radius-control);
  background: var(--color-shell);
  box-shadow: 0 0 0 1px var(--color-sidebar-border) inset;
  transition: box-shadow var(--motion-fast);
}
.search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--color-accent) inset;
}
.search-input :deep(.el-input__inner) {
  color: var(--color-sidebar-text);
  font-size: 13px;
}
.search-input :deep(.el-input__inner::placeholder),
.search-input :deep(.el-input__icon) {
  color: var(--color-sidebar-muted);
}
.history-heading {
  display: flex;
  justify-content: space-between;
  padding: 0 var(--space-2);
  color: var(--color-sidebar-muted);
  font-size: 12px;
}
.conversation-list {
  flex: 1;
  min-height: 0;
}
.history-group + .history-group {
  margin-top: var(--space-4);
}
.history-group__heading {
  margin: 0 0 var(--space-1);
  padding: var(--space-1) var(--space-2);
  color: var(--color-sidebar-muted);
  font-size: 12px;
  font-weight: 500;
}
.conversation-item {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: var(--space-1);
  padding-right: var(--space-1);
  border-radius: var(--radius-list);
  transition: background var(--motion-fast);
}
.conversation-item:hover {
  background: var(--color-sidebar-hover);
}
.conversation-item.active {
  background: var(--color-sidebar-hover);
}
.conversation-item.active::before {
  content: "";
  position: absolute;
  top: 12px;
  bottom: 12px;
  left: 0;
  width: 2px;
  border-radius: 2px;
  background: var(--color-brand-mint);
}
.conversation-select {
  display: block;
  min-width: 0;
  min-height: 40px;
  flex: 1;
  padding: var(--space-2);
  border: 0;
  border-radius: var(--radius-list);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.conversation-item__title {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 500;
}
.conversation-item__preview {
  display: block;
  margin-top: var(--space-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-sidebar-muted);
  font-size: 12px;
  line-height: 20px;
}
.conversation-dropdown {
  flex: 0 0 auto;
}
.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-sidebar-muted);
  font-size: 16px;
  cursor: pointer;
  transition:
    background var(--motion-fast),
    color var(--motion-fast),
    opacity var(--motion-fast);
}
.icon-button:hover,
.icon-button:focus-visible {
  background: var(--color-sidebar-hover);
  color: var(--color-sidebar-text);
}
.icon-button:focus-visible,
.conversation-select:focus-visible,
.new-chat-btn:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
.icon-button:disabled {
  opacity: 0.5;
  cursor: wait;
}
.conversation-more {
  width: 28px;
  height: 28px;
  opacity: 0;
}
.conversation-item:hover .conversation-more,
.conversation-item:focus-within .conversation-more {
  opacity: 1;
}
.empty-state {
  padding: var(--space-6) var(--space-2);
  text-align: center;
  color: var(--color-sidebar-muted);
  font-size: 13px;
}
.sidebar-footer {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-sidebar-border);
}
.rail-spacer {
  flex: 1;
}
.is-compact {
  align-items: center;
  padding-inline: 14px;
}
.is-compact .brand-row {
  width: 44px;
  justify-content: center;
  padding: 0;
}
.is-compact .brand-dock {
  display: flex;
  justify-content: center;
}
.is-compact :deep(.echo-title) {
  display: none;
}
.is-compact .new-chat-btn,
.rail-button {
  width: 44px;
  height: 44px;
  padding: 0;
}
.rail-button {
  font-size: 20px;
}
.is-compact .sidebar-footer {
  width: 44px;
  flex-direction: column;
  gap: var(--space-2);
}
.is-compact .sidebar-footer > .icon-button {
  width: 40px;
  height: 40px;
}
@media (hover: none) {
  .conversation-more {
    opacity: 1;
  }
}
@media (max-width: 767px) {
  .icon-button,
  .conversation-more {
    width: 44px;
    height: 44px;
  }
  .conversation-select {
    min-height: 44px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .sidebar *,
  .sidebar :deep(.el-input__wrapper) {
    transition: none;
  }
  .new-chat-btn:not(:disabled):hover,
  .new-chat-btn:not(:disabled):active {
    transform: none;
  }
}
</style>
