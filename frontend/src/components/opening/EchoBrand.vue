<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { gsap } from "gsap";

const props = defineProps({
  opening: Boolean,
  compact: Boolean,
  reducedMotion: Boolean,
});
const brand = ref(null);
let animation;
const letters = [..."EchoChat"];

const stopAnimation = () => {
  animation?.revert();
  animation = null;
};
const animateBrand = () => {
  stopAnimation();
  if (!props.opening || props.reducedMotion || !brand.value) return;
  animation = gsap.context(() => {
    const timeline = gsap.timeline();
    timeline
      .from(".echo-mark-body", { opacity: 0, y: 9, scale: 0.9, duration: 0.7, ease: "power2.out" }, 0.65)
      .from(".echo-eye-blink", { opacity: 0, duration: 0.22 }, 0.88)
      .to(".echo-eye-blink", { scaleY: 0.12, transformOrigin: "50% 50%", duration: 0.1, repeat: 1, yoyo: true }, 1.08)
      .set(".echo-eye-blink", { clearProps: "transform" }, 1.28)
      .from(".echo-title-letter", {
        yPercent: 110,
        filter: "blur(5px)",
        duration: 0.7,
        stagger: 0.045,
        ease: "power3.out",
      }, 1.02);
  }, brand.value);
};
onMounted(animateBrand);
watch(() => [props.opening, props.reducedMotion], animateBrand);
onBeforeUnmount(stopAnimation);
defineExpose({ stopAnimation });
</script>

<template>
  <div ref="brand" class="echo-brand" :class="{ 'is-opening': opening, 'is-compact': compact }">
    <svg data-echo-logo class="echo-mark" viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <g class="echo-mark-body">
        <path d="M36 37 27 22M84 37l9-15" class="echo-antenna" stroke-width="5" stroke-linecap="round" />
        <circle cx="25" cy="19" r="5" class="echo-antenna-tip" />
        <circle cx="95" cy="19" r="5" class="echo-antenna-tip" />
        <path d="M24 71c0-24 16-40 36-40s36 16 36 40v22c0 7-5 12-12 12H36c-7 0-12-5-12-12V71Z" class="echo-shell" />
        <path d="M33 72c0-18 11-31 27-31s27 13 27 31v19c0 3-2 5-5 5H38c-3 0-5-2-5-5V72Z" class="echo-face" />
        <path d="m47 17 10-2 6-8 7 9 9-1" class="echo-spark" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
        <g class="echo-eyes">
          <g class="echo-eye-blink">
            <rect x="43" y="60" width="8" height="13" rx="4" />
            <rect x="69" y="60" width="8" height="13" rx="4" />
          </g>
        </g>
        <path d="M50 84h20" class="echo-smile" stroke-width="5" stroke-linecap="round" />
        <path d="M39 47c5-5 13-8 21-8" stroke="white" stroke-opacity="0.65" stroke-width="3" stroke-linecap="round" />
      </g>
    </svg>
    <span data-echo-title class="echo-title" aria-label="EchoChat">
      <span v-for="(letter, index) in letters" :key="index" class="echo-title-mask" aria-hidden="true">
        <span class="echo-title-letter">{{ letter }}</span>
      </span>
    </span>
  </div>
</template>

<style scoped>
.echo-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  width: fit-content;
  color: var(--color-heading);
}
.echo-mark {
  display: block;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  overflow: visible;
}
.echo-shell { fill: #34465b; }
.echo-face { fill: #78eac0; }
.echo-antenna, .echo-spark, .echo-smile { stroke: #34465b; }
.echo-antenna-tip, .echo-eyes { fill: #34465b; }
.echo-eyes { transform: translate(var(--eyes-x, 0px), var(--eyes-y, 0px)); }
.echo-title {
  display: inline-flex;
  align-items: baseline;
  white-space: nowrap;
  font-size: 20px;
  font-weight: 650;
  line-height: 1.1;
  letter-spacing: 0;
}
.echo-title-mask {
  display: inline-block;
  overflow: hidden;
  padding: 0 0.045em 0.08em;
  margin-inline: -0.025em;
  font-weight: inherit;
}
.echo-title-letter { display: inline-block; font-weight: inherit; }
.is-opening {
  flex-direction: column;
  gap: 33px;
  margin-inline: auto;
  color: #eef5ff;
}
.is-opening .echo-mark {
  width: 124px;
  height: 124px;
  filter: drop-shadow(0 0 20px rgb(89 188 236 / 24%));
}
.is-opening .echo-shell { fill: #a1d3e8; }
.is-opening .echo-face { fill: #8ff0cb; }
.is-opening .echo-antenna, .is-opening .echo-spark { stroke: #bedff1; }
.is-opening .echo-antenna-tip { fill: #9beddd; }
.is-opening .echo-title {
  font-size: clamp(44px, 4.7vw, 54px);
  letter-spacing: 0;
  font-weight: 650;
}
.echo-brand.is-compact .echo-mark { width: 22px; height: 22px; }
.echo-brand.is-compact .echo-title { display: none; }
@media (max-width: 600px) {
  .is-opening { gap: 28px; }
  .is-opening .echo-mark { width: 110px; height: 110px; }
  .is-opening .echo-title { font-size: 42px; }
}
@media (prefers-reduced-motion: reduce) {
  .echo-mark { filter: none; }
}
</style>
