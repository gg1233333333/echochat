<style src="@/assets/main.css"></style>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import ChatMessage from "@/views/chatMessage.vue";
import ConversationSidebar from "@/components/chat/ConversationSidebar.vue";
import { useThemeStore } from "@/stores/theme";
import { useSessionStore } from "@/stores/session";
import { useDynamicFavicon } from "@/composables/useDynamicFavicon";
import { useOpening } from "@/composables/useOpening";
import WelcomeStage from "@/components/opening/WelcomeStage.vue";
import EchoBrand from "@/components/opening/EchoBrand.vue";
import InspirationCards from "@/components/opening/InspirationCards.vue";

const sessionStore = useSessionStore();
const themeStore = useThemeStore();
useDynamicFavicon(computed(() => sessionStore.options?.roles[0]?.icons?.favicon));
const chatPanelRef = ref(null);
const viewportWidth = ref(window.innerWidth);
const isMobile = computed(() => viewportWidth.value < 768);
const isSidebarOpen = ref(false);
const desktopCollapsed = ref(false);
const isRail = computed(
  () => !isMobile.value && (viewportWidth.value < 1200 || desktopCollapsed.value),
);
const overlayOpen = computed(() => isSidebarOpen.value && (isMobile.value || isRail.value));
const workspace = ref(null);
const sidebar = ref(null);
const stage = ref(null);
const brand = ref(null);
const brandInHeader = isMobile;
const hasMessages = computed(() => sessionStore.messages.length > 0);
const opening = useOpening({
  workspace,
  stage,
  brand,
  hasMessages,
  getBrandDock: () => (brandInHeader.value ? "#echo-header-brand" : "#echo-sidebar-brand"),
  getBrandCompact: () => isMobile.value || (isRail.value && !overlayOpen.value),
  canReplay: () => !sessionStore.isGenerating,
});
const { phase, mounted, active, full, docked, reducedMotion, brandTarget, cardTarget } = opening;
const chooseSuggestion = (prompt) => {
  if (active.value || !sessionStore.ready) return;
  const draft = sessionStore.currentDraft.text;
  sessionStore.setDraftText(draft ? `${draft.trimEnd()}\n\n${prompt}` : prompt);
  workspace.value?.querySelector("textarea.inputbox")?.focus({ preventScroll: true });
};
const sidebarVisible = computed(() => (isMobile.value || isRail.value ? overlayOpen.value : true));
let sidebarTrigger;
let sidebarTriggerLabel;
let sidebarFocusTarget;
const rememberSidebarTrigger = () => {
  sidebarTrigger = document.activeElement;
  sidebarTriggerLabel = sidebarTrigger?.getAttribute("aria-label");
};
const toggleSidebar = () => {
  rememberSidebarTrigger();
  sidebarFocusTarget = null;
  if (isMobile.value || viewportWidth.value < 1200) isSidebarOpen.value = !isSidebarOpen.value;
  else desktopCollapsed.value = !desktopCollapsed.value;
};
const expandSidebar = (source) => {
  rememberSidebarTrigger();
  sidebarFocusTarget = source === "search" ? ".search-input input" : null;
  isSidebarOpen.value = true;
};
const closeSidebar = () => {
  const shouldRestore = overlayOpen.value;
  isSidebarOpen.value = false;
  if (shouldRestore)
    void nextTick(() => {
      const trigger =
        sidebarTrigger?.isConnected && sidebarTrigger.getClientRects().length
          ? sidebarTrigger
          : sidebarTriggerLabel &&
            workspace.value?.querySelector(
              `button[aria-label="${CSS.escape(sidebarTriggerLabel)}"]`,
            );
      (trigger || workspace.value?.querySelector('button[aria-label="切换会话列表"]'))?.focus({
        preventScroll: true,
      });
    });
};
const updateViewportMode = () => {
  closeSidebar();
  viewportWidth.value = window.innerWidth;
};
watch(overlayOpen, async (open) => {
  if (!open) return;
  await nextTick();
  sidebar.value
    ?.querySelector(sidebarFocusTarget || "button:not(:disabled)")
    ?.focus({ preventScroll: true });
});
const sidebarKeyboard = (event) => {
  if (!overlayOpen.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeSidebar();
    return;
  }
  if (event.key !== "Tab") return;
  const items = [
    ...sidebar.value.querySelectorAll('button:not(:disabled),input:not(:disabled),[tabindex="0"]'),
  ].filter((element) => element.getClientRects().length);
  const first = items[0];
  const last = items.at(-1);
  if (
    (event.shiftKey && document.activeElement === first) ||
    (!event.shiftKey && document.activeElement === last)
  ) {
    event.preventDefault();
    (event.shiftKey ? last : first)?.focus();
  }
};
const replayOpening = () => {
  closeSidebar();
  void opening.replay();
};
const handleHistorySelect = (id) => {
  chatPanelRef.value?.selecthistory(id);
  closeSidebar();
};
onMounted(() => {
  sessionStore.initialize().catch(sessionStore.reportError);
  window.addEventListener("resize", updateViewportMode, { passive: true });
  window.addEventListener("pagehide", sessionStore.disconnect);
});
onBeforeUnmount(() => {
  themeStore.cleanup();
  sessionStore.disconnect();
  window.removeEventListener("resize", updateViewportMode);
  window.removeEventListener("pagehide", sessionStore.disconnect);
});
</script>

<template>
  <div
    class="echo-app"
    :class="{
      'is-opening-active': active,
      'is-entering': phase === 'entering',
      'has-welcome': full,
    }"
    :data-opening-phase="phase"
  >
    <div
      ref="workspace"
      class="app-shell"
      :class="{ 'is-rail': isRail, 'has-sidebar-overlay': overlayOpen }"
      :inert="active"
      :aria-hidden="active"
    >
      <div
        ref="sidebar"
        class="sideleft"
        :class="{ 'is-mobile-active': overlayOpen }"
        :inert="isMobile && !overlayOpen"
        @keydown="sidebarKeyboard"
      >
        <ConversationSidebar
          :mobile="isMobile"
          :closable="overlayOpen"
          :compact="isRail && !overlayOpen"
          @request-expand="expandSidebar"
          @callR="handleHistorySelect"
          @close="closeSidebar"
          @replay-opening="replayOpening"
        />
      </div>
      <main class="sideright" :inert="overlayOpen" :aria-hidden="overlayOpen">
        <ChatMessage
          ref="chatPanelRef"
          :sidebar-open="sidebarVisible"
          :brand-in-header="brandInHeader"
          @toggle-sidebar="toggleSidebar"
        />
      </main>
      <button
        v-if="overlayOpen"
        class="mobile-overlay"
        aria-label="关闭会话列表"
        @click="closeSidebar"
      ></button>
    </div>
    <WelcomeStage
      v-if="full"
      ref="stage"
      :reduced-motion="reducedMotion"
      :exiting="phase === 'entering'"
      @enter="opening.enter"
    />
    <Teleport v-if="mounted" :to="brandTarget">
      <EchoBrand
        ref="brand"
        :opening="!docked"
        :compact="docked && brandInHeader"
        :reduced-motion="reducedMotion"
      />
    </Teleport>
    <Teleport v-if="mounted && cardTarget" :to="cardTarget" defer>
      <InspirationCards
        :opening="!docked"
        :disabled="!sessionStore.ready || active"
        @choose="chooseSuggestion"
      />
    </Teleport>
  </div>
</template>

<style scoped>
.echo-app {
  height: 100dvh;
  background: var(--color-shell);
}
.is-opening-active .app-shell {
  opacity: 0;
  pointer-events: none;
}
.is-entering .app-shell {
  position: relative;
  z-index: 4002;
  background: transparent;
}
.is-entering .sideleft {
  background: transparent;
}
.is-entering .sideleft::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: var(--color-sidebar-surface);
  opacity: var(--sidebar-opacity, 0);
  pointer-events: none;
}
.is-entering :deep(.sidebar) {
  position: relative;
  background: transparent;
}
.is-entering .sideright {
  background: transparent;
}
.is-entering :deep(.header) {
  background: transparent;
  border-color: transparent;
}
.is-entering :deep(.echo-mark) {
  transition: filter 0.85s ease;
}
.is-entering :deep(.echo-mark path),
.is-entering :deep(.echo-mark circle),
.is-entering :deep(.echo-eyes) {
  transition:
    fill 0.85s ease,
    stroke 0.85s ease;
}
.is-entering .sideright::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: var(--color-panel);
  mask-image: linear-gradient(
    to right,
    transparent calc(var(--canvas-reveal, 110%) - 10%),
    #000 calc(var(--canvas-reveal, 110%) + 10%)
  );
  transform: translateX(var(--canvas-offset, 16px)) scale(var(--canvas-scale, 0.985));
  transform-origin: right center;
  pointer-events: none;
}
.app-shell {
  --chat-column-width: 840px;
  --chat-gutter: 32px;
  --chat-header-height: 60px;
  display: flex;
  height: 100dvh;
  padding: 12px;
  gap: 12px;
  overflow: hidden;
  background: var(--color-shell);
}
.sideleft {
  position: relative;
  width: 248px;
  flex: 0 0 248px;
  min-height: 0;
  background: var(--color-sidebar-surface);
  border-radius: var(--radius-canvas);
}
.sideright {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  position: relative;
  overflow: hidden;
  border-radius: var(--radius-canvas);
  background: var(--color-panel);
}
.is-rail .sideleft {
  width: 72px;
  flex-basis: 72px;
}
.is-rail.has-sidebar-overlay .sideleft {
  position: absolute;
  inset: 12px auto 12px 12px;
  z-index: 31;
  width: 248px;
  box-shadow: var(--shadow-strong);
}
.is-rail.has-sidebar-overlay .sideright {
  margin-left: 84px;
}
.mobile-overlay {
  position: fixed;
  inset: 0;
  z-index: 30;
  border: 0;
  background: rgb(0 8 22 / 58%);
  cursor: pointer;
}
@media (max-width: 767px) {
  .app-shell {
    --chat-gutter: 16px;
    --chat-header-height: 56px;
    padding: 0;
    gap: 0;
  }
  .sideright {
    border-radius: 0;
  }
  .sideleft {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 31;
    width: min(280px, 88vw);
    border-radius: 0 var(--radius-canvas) var(--radius-canvas) 0;
    transform: translateX(-100%);
    transition: transform var(--motion-normal) ease;
  }
  .sideleft.is-mobile-active {
    transform: translateX(0);
    box-shadow: var(--shadow-strong);
  }
}
</style>
