<style src="@/assets/main.css"></style>
<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import ChatMessage from "@/views/chatMessage.vue";
import ConversationSidebar from "@/components/chat/ConversationSidebar.vue";
import { useThemeStore } from "@/stores/theme";
import { useSessionStore } from "@/stores/session";
import { useDynamicFavicon } from "@/composables/useDynamicFavicon";
import { Close, Menu } from "@element-plus/icons-vue";

// 使用动态 favicon，根据角色自动切换
const sessionStore = useSessionStore();
useDynamicFavicon(computed(() => sessionStore.currentRole));

/**
 * 保存右侧对话面板的组件引用，方便在侧边栏切换会话时
 * 调用内部暴露的方法来同步消息列表。
 */
const chatPanelRef = ref(null);
const themeStore = useThemeStore();

const MOBILE_BREAKPOINT = 1024;

const isSidebarOpen = ref(false);
const isMobile = ref(false);

const currentConversationTitle = computed(
  () => sessionStore.curname || "DeepSeek 对话",
);

onBeforeUnmount(() => {
  themeStore.cleanup();
  if (typeof window !== "undefined") {
    window.removeEventListener("resize", updateViewportMode);
  }
});

/**
 * 当侧边栏选中一个历史会话时，将事件继续传递给
 * ChatMessage 组件，从而刷新当前的消息内容。
 */
const handleHistorySelect = (conversation) => {
  chatPanelRef.value?.selecthistory(conversation);
  if (isMobile.value) {
    isSidebarOpen.value = false;
  }
};

const updateViewportMode = () => {
  if (typeof window === "undefined") return;
  isMobile.value = window.innerWidth <= MOBILE_BREAKPOINT;
  if (!isMobile.value) {
    isSidebarOpen.value = false;
  }
};

const toggleSidebar = () => {
  if (!isMobile.value) return;
  isSidebarOpen.value = !isSidebarOpen.value;
};

const closeSidebar = () => {
  if (!isMobile.value) return;
  isSidebarOpen.value = false;
};

onMounted(() => {
  updateViewportMode();
  if (typeof window !== "undefined") {
    window.addEventListener("resize", updateViewportMode, { passive: true });
  }
});
</script>

<template>
  <div class="app-shell" :class="{ 'is-sidebar-open': isSidebarOpen }">
    <header class="mobile-header">
      <button
        class="mobile-header__action"
        type="button"
        @click="toggleSidebar"
        aria-label="切换会话列表"
      >
        <el-icon>
          <component :is="isSidebarOpen ? Close : Menu" />
        </el-icon>
      </button>
      <div class="mobile-header__title" :title="currentConversationTitle">
        {{ currentConversationTitle }}
      </div>
    </header>
    <div class="box">
      <div class="sideleft" :class="{ 'is-mobile-active': isSidebarOpen }">
        <ConversationSidebar @callR="handleHistorySelect" />
      </div>
      <div class="sideright">
        <ChatMessage ref="chatPanelRef" />
      </div>
    </div>
    <div
      v-if="isMobile && isSidebarOpen"
      class="mobile-overlay"
      @click="closeSidebar"
    ></div>
  </div>
</template>

<style scoped>
.app-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
}

.box {
  display: flex;
  height: 100%;
  width: 100%;
  background: var(--color-app-background);
}

.mobile-header {
  display: none;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--color-panel);
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
  z-index: 12;
}

.mobile-header__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: background-color 0.2s ease, color 0.2s ease;
}

.mobile-header__action:hover {
  background: var(--color-toolbar-bg);
  color: var(--color-heading);
}

.mobile-header__title {
  flex: 1;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-heading);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sideleft {
  height: 100%;
  background: var(--color-sidebar-surface);
  width: 400px;
  border-right: 1px solid var(--color-border-strong);
}
.sideright {
  height: 100%;
  width: 100%;
  background: var(--color-panel-alt);
  display: flex;
  flex-direction: column;

  position: relative;
}

.mobile-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(2px);
  z-index: 10;
}

@media (max-width: 1024px) {
  .box {
    flex: 1;
    position: relative;
  }

  .mobile-header {
    display: flex;
  }

  .sideleft {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(360px, 85vw);
    max-width: 100%;
    transform: translateX(-100%);
    transition: transform 0.25s ease, box-shadow 0.25s ease;
    z-index: 11;
    box-shadow: none;
  }

  .sideleft.is-mobile-active {
    transform: translateX(0);
    box-shadow: 12px 0 32px rgba(15, 23, 42, 0.24);
  }

  .sideright {
    width: 100%;
  }
}

@media (max-width: 640px) {
  .mobile-header {
    padding: 10px 14px;
  }

  .mobile-header__action {
    width: 36px;
    height: 36px;
  }

  .mobile-header__title {
    font-size: 15px;
  }
}
</style>
