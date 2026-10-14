<script setup>
import { nextTick, ref, useId, watch } from "vue";
import { Check, Guide } from "@element-plus/icons-vue";

const props = defineProps({
  entries: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
});
const emit = defineEmits(["select"]);
const mobileOpen = ref(false);
const mobileTrigger = ref(null);
const mobileList = ref(null);
const rail = ref(null);
const listId = useId();
let restoreFocus = false;
const closeMobile = () => {
  restoreFocus = true;
  mobileOpen.value = false;
};
const afterMobileClose = async () => {
  if (!restoreFocus) return;
  restoreFocus = false;
  await nextTick();
  if (!mobileOpen.value) mobileTrigger.value?.focus({ preventScroll: true });
};
const select = (id) => {
  emit("select", id);
  if (mobileOpen.value) void closeMobile();
};
watch(
  mobileOpen,
  async (open) => {
    if (!open) return;
    restoreFocus = false;
    await nextTick();
    if (!mobileOpen.value) return;
    const current =
      props.activeId &&
      mobileList.value?.querySelector(`[data-navigation-id="${CSS.escape(props.activeId)}"]`);
    (current || mobileList.value?.querySelector("button"))?.focus({ preventScroll: true });
  },
  { flush: "post" },
);
watch(
  () => [props.activeId, props.entries.length],
  async () => {
    await nextTick();
    const container = rail.value;
    if (!container?.clientHeight || !props.activeId) return;
    const current = container.querySelector(`[data-navigation-id="${CSS.escape(props.activeId)}"]`);
    if (!current) return;
    const bounds = container.getBoundingClientRect();
    const tick = current.getBoundingClientRect();
    if (tick.top < bounds.top) container.scrollTop += tick.top - bounds.top;
    else if (tick.bottom > bounds.bottom) container.scrollTop += tick.bottom - bounds.bottom;
  },
  { flush: "post" },
);
</script>

<template>
  <nav v-if="entries.length" class="conversation-navigator" aria-label="对话定位">
    <div ref="rail" class="conversation-navigator__rail" aria-label="已加载轮次">
      <el-tooltip
        v-for="(entry, index) in entries"
        :key="entry.id"
        placement="right"
        effect="light"
        :trigger="['hover', 'focus']"
        :show-after="120"
        popper-class="conversation-navigation-tooltip"
      >
        <button
          class="conversation-navigator__tick"
          :class="{ 'is-active': activeId === entry.id }"
          type="button"
          :data-navigation-id="entry.id"
          :aria-label="`定位到：${entry.label}`"
          :aria-current="activeId === entry.id ? 'location' : undefined"
          @click="select(entry.id)"
        >
          <span aria-hidden="true"></span>
        </button>
        <template #content>
          <div class="conversation-navigation-preview">
            <small>第 {{ index + 1 }} 轮 · 已加载记录</small>
            <p>{{ entry.label }}</p>
            <span v-if="entry.preview">{{ entry.preview }}</span>
          </div>
        </template>
      </el-tooltip>
    </div>
    <div class="conversation-navigator__mobile">
      <el-popover
        v-model:visible="mobileOpen"
        trigger="click"
        placement="bottom-end"
        :width="300"
        :show-arrow="false"
        :persistent="false"
        popper-class="conversation-navigation-popper"
        @after-leave="afterMobileClose"
      >
        <template #reference>
          <span class="conversation-navigator__reference"
            ><button
              ref="mobileTrigger"
              class="conversation-navigator__trigger"
              type="button"
              aria-label="定位对话"
              :aria-expanded="mobileOpen"
              :aria-controls="listId"
              title="定位对话"
              @keydown.esc.prevent.stop="closeMobile"
            >
              <el-icon><Guide /></el-icon></button
          ></span>
        </template>
        <p class="conversation-navigation-heading">已加载 {{ entries.length }} 轮对话</p>
        <div
          ref="mobileList"
          :id="listId"
          class="conversation-navigation-list"
          @keydown.esc.prevent.stop="closeMobile"
        >
          <button
            v-for="(entry, index) in entries"
            :key="entry.id"
            class="conversation-navigation-item"
            :class="{ 'is-active': activeId === entry.id }"
            type="button"
            :data-navigation-id="entry.id"
            :aria-current="activeId === entry.id ? 'location' : undefined"
            @click="select(entry.id)"
          >
            <span class="conversation-navigation-number">{{ index + 1 }}</span>
            <span class="conversation-navigation-copy"
              ><span>{{ entry.label }}</span
              ><small v-if="entry.preview">{{ entry.preview }}</small></span
            >
            <el-icon
              v-if="activeId === entry.id"
              class="conversation-navigation-check"
              aria-hidden="true"
              ><Check
            /></el-icon>
          </button>
        </div>
      </el-popover>
    </div>
  </nav>
</template>

<style scoped>
.conversation-navigator {
  position: absolute;
  left: 0;
  top: var(--space-3);
  bottom: var(--space-3);
  z-index: 2;
  width: 32px;
  pointer-events: none;
}
.conversation-navigator__rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  max-height: 100%;
  overflow-y: auto;
  overscroll-behavior: contain;
  pointer-events: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--color-border-strong) transparent;
}
.conversation-navigator__tick {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 24px;
  flex-shrink: 0;
  padding: 0;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  cursor: pointer;
}
.conversation-navigator__tick span {
  display: block;
  width: 8px;
  height: 2px;
  border-radius: 2px;
  background: var(--color-muted);
  transition:
    width var(--motion-fast),
    background var(--motion-fast);
}
.conversation-navigator__tick.is-active span {
  width: 16px;
  background: var(--color-accent);
}
.conversation-navigator__tick:hover span {
  width: 13px;
  background: var(--color-text-secondary);
}
.conversation-navigator__tick.is-active:hover span {
  width: 16px;
  background: var(--color-accent);
}
.conversation-navigator__tick:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: -2px;
  background: var(--color-toolbar-bg);
}
.conversation-navigator__mobile {
  display: none;
}
.conversation-navigator__reference {
  display: inline-flex;
}
@media (max-width: 767px) {
  .conversation-navigator {
    position: relative;
    inset: auto;
    flex-shrink: 0;
    width: 100%;
    height: 52px;
    padding: var(--space-1) var(--chat-gutter);
  }
  .conversation-navigator__rail {
    display: none;
  }
  .conversation-navigator__mobile {
    display: flex;
    justify-content: flex-end;
    height: 44px;
    pointer-events: auto;
  }
  .conversation-navigator__trigger {
    display: inline-flex;
    justify-content: center;
    align-items: center;
    width: 44px;
    height: 44px;
    padding: 0;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-control);
    color: var(--color-text-secondary);
    background: var(--color-input-background);
    font-size: 19px;
    cursor: pointer;
  }
  .conversation-navigator__trigger:hover,
  .conversation-navigator__trigger:focus-visible {
    color: var(--color-accent);
    border-color: var(--color-accent);
  }
  .conversation-navigator__trigger:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }
}
</style>

<style>
.conversation-navigation-tooltip.el-popper.is-light,
.conversation-navigation-popper.el-popper.is-light {
  max-width: calc(100vw - 32px);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-list);
  background: var(--color-elevated-surface);
  color: var(--color-text-primary);
  box-shadow: var(--shadow-medium);
}
.conversation-navigation-preview {
  width: 260px;
  max-width: calc(100vw - 60px);
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.conversation-navigation-preview small {
  display: block;
  color: var(--color-muted);
  font-size: 12px;
}
.conversation-navigation-preview p {
  margin: var(--space-2) 0;
  color: var(--color-text-primary);
  font-size: 14px;
  font-weight: 550;
}
.conversation-navigation-preview span {
  display: block;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.conversation-navigation-heading {
  padding: 0 var(--space-2) var(--space-3);
  color: var(--color-text-secondary);
  font-size: 13px;
}
.conversation-navigation-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  max-height: min(55dvh, 360px);
  overflow-y: auto;
  overscroll-behavior: contain;
}
.conversation-navigation-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  width: 100%;
  min-height: 44px;
  padding: var(--space-3) var(--space-2);
  border: 0;
  border-radius: var(--radius-control);
  color: var(--color-text-primary);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--motion-fast);
}
.conversation-navigation-item:hover,
.conversation-navigation-item:focus-visible {
  background: var(--color-panel-alt);
}
.conversation-navigation-item.is-active {
  background: var(--color-toolbar-bg);
}
.conversation-navigation-item:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: -2px;
}
.conversation-navigation-number {
  flex-shrink: 0;
  min-width: 16px;
  color: var(--color-muted);
  font-size: 12px;
  line-height: 22px;
}
.conversation-navigation-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-1);
  overflow-wrap: anywhere;
}
.conversation-navigation-copy > span {
  font-size: 14px;
  line-height: 22px;
}
.conversation-navigation-copy small {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.conversation-navigation-check {
  color: var(--color-toolbar-text);
  margin-top: 3px;
  flex-shrink: 0;
}
</style>
