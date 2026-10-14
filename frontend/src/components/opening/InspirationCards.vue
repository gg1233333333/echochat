<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { inspirations } from "@/config/inspirations";

const props = defineProps({ opening: Boolean, disabled: Boolean });
const emit = defineEmits(["choose"]);
const hovered = ref(null);
const hasEntry = ref(false);
const pointerStyle = computed(() => ({ "--hovered": hovered.value == null ? 0 : 1 }));
onMounted(() => {
  hasEntry.value =
    !props.opening && document.querySelector(".echo-app")?.dataset.openingPhase === "chat";
});
watch(
  () => props.opening,
  (opening) => {
    if (opening) hasEntry.value = false;
  },
);
</script>

<template>
  <div
    class="inspiration-cards"
    :class="{ 'is-opening': opening, 'has-hover': hovered !== null, 'has-entry': hasEntry }"
    :style="pointerStyle"
  >
    <button
      v-for="(item, index) in inspirations"
      :key="item.id"
      :data-inspiration="item.id"
      class="inspiration-card"
      :class="{ 'is-hovered': hovered === item.id }"
      :style="{ '--card-index': index }"
      :disabled="disabled && !opening"
      :aria-disabled="opening || disabled"
      :tabindex="opening ? -1 : 0"
      @pointerenter="hovered = item.id"
      @pointerleave="hovered = null"
      @click="!opening && !disabled && emit('choose', item.prompt)"
    >
      <span class="inspiration-icon" aria-hidden="true">
        <svg v-if="item.id === 'writing'" viewBox="0 0 24 24" fill="none">
          <path
            d="m15 4 5 5M4 20l5-1 11-11a2 2 0 0 0-5-5L4 14l-1 6h1Z"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linejoin="round"
          />
          <path d="M13 21h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        </svg>
        <svg v-else-if="item.id === 'coding'" viewBox="0 0 24 24" fill="none">
          <path
            d="m7 6-6 6 6 6m10-12 6 6-6 6M14 4l-4 16"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="none">
          <path
            d="M5 5h14M5 10h10M5 15h14M5 20h7"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
          />
          <path
            d="m18 18 2 2 3-4"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </span>
      <span class="inspiration-label">{{ opening ? item.openingLabel : item.label }}</span>
      <svg class="inspiration-arrow" aria-hidden="true" viewBox="0 0 20 20" fill="none">
        <path
          d="M4 10h12m-5-5 5 5-5 5"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>
  </div>
</template>

<style scoped>
.inspiration-cards {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-2);
  width: 100%;
}
.inspiration-card {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 42px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-list);
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-secondary);
  background: transparent;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--motion-fast),
    border-color var(--motion-fast),
    transform var(--motion-normal),
    opacity var(--motion-fast);
}
.inspiration-card:hover {
  color: var(--color-accent);
  border-color: color-mix(in srgb, var(--color-accent) 42%, transparent);
  background: var(--color-toolbar-bg);
}
.inspiration-card:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 4px;
}
.inspiration-icon {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  color: var(--color-accent);
}
.inspiration-icon svg {
  width: 100%;
  height: 100%;
}
.inspiration-arrow {
  display: none;
}
.has-entry:not(.is-opening) .inspiration-card {
  animation: suggestion-enter 0.26s both ease-out;
  animation-delay: calc(var(--card-index) * 35ms);
}
@keyframes suggestion-enter {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.is-opening {
  position: relative;
  display: block;
  width: 100%;
  height: 100%;
  perspective: 900px;
}
.is-opening .inspiration-card {
  position: absolute;
  min-height: 62px;
  padding: 16px 20px;
  border-radius: 16px;
  border-color: rgb(172 206 248 / 14%);
  background: linear-gradient(125deg, rgb(118 170 226 / 10%), rgb(18 39 71 / 30%));
  backdrop-filter: blur(14px);
  box-shadow:
    0 12px 38px rgb(1 10 26 / 15%),
    inset 0 1px rgb(207 231 255 / 5%);
  color: #bdd0e8;
  font-size: 14px;
  cursor: default;
  overflow: hidden;
  transform: translate3d(var(--cards-x, 0px), var(--cards-y, 0px), 0) rotate(var(--card-rotation));
  transition:
    transform 0.28s cubic-bezier(0.2, 0.7, 0.2, 1),
    opacity 0.5s,
    border-color 0.5s,
    background 0.5s;
}
.is-opening .inspiration-card::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(115deg, transparent 25%, rgb(166 217 255 / 13%) 50%, transparent 72%);
  transform: translateX(-130%);
  transition: transform 0.8s ease;
  pointer-events: none;
}
.is-opening .inspiration-card:nth-child(1) {
  left: calc(50% - 425px);
  top: calc(50% - 67px);
  --card-rotation: -7deg;
}
.is-opening .inspiration-card:nth-child(2) {
  left: calc(50% + 198px);
  top: calc(50% - 133px);
  --card-rotation: 6deg;
}
.is-opening .inspiration-card:nth-child(3) {
  left: calc(50% + 177px);
  top: calc(50% + 94px);
  --card-rotation: -5deg;
}
.is-opening .inspiration-icon {
  color: #8ecbf4;
}
.is-opening .inspiration-arrow {
  display: none;
}
.is-opening .inspiration-card.is-hovered {
  transform: translate3d(var(--cards-x, 0px), calc(var(--cards-y, 0px) - 8px), 12px) rotate(0deg);
  border-color: rgb(166 217 255 / 38%);
  background: linear-gradient(125deg, rgb(118 170 226 / 19%), rgb(18 39 71 / 38%));
}
.is-opening .is-hovered::before {
  transform: translateX(130%);
}
.is-opening.has-hover .inspiration-card:not(.is-hovered) {
  opacity: 0.6;
}
@media (max-width: 1050px) and (min-width: 601px) {
  .is-opening .inspiration-card:nth-child(1) {
    left: 6%;
    top: 48%;
  }
  .is-opening .inspiration-card:nth-child(2) {
    left: auto;
    right: 5%;
    top: 33%;
  }
  .is-opening .inspiration-card:nth-child(3) {
    left: auto;
    right: 6%;
    top: 65%;
  }
  .is-opening .inspiration-card {
    padding: 13px 16px;
    font-size: 12px;
    min-height: 55px;
  }
}
@media (max-width: 600px) {
  .is-opening {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    gap: 10px;
    padding-top: 61dvh;
  }
  .is-opening .inspiration-card:nth-child(n) {
    position: relative;
    top: auto;
    left: auto;
    right: auto;
    min-height: 43px;
    padding: 10px 15px;
    border-radius: 12px;
    font-size: 12px;
    --card-rotation: 0deg;
  }
  .is-opening .inspiration-icon {
    width: 17px;
    height: 17px;
  }
  .inspiration-cards:not(.is-opening) {
    align-items: stretch;
    flex-direction: column;
    gap: var(--space-2);
  }
  .inspiration-cards:not(.is-opening) .inspiration-card {
    justify-content: flex-start;
    min-height: 42px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .inspiration-card,
  .is-opening .inspiration-card {
    transform: none !important;
    transition: none;
    animation: none !important;
  }
  .is-opening .inspiration-card::before {
    display: none;
  }
}
</style>
