<script setup>
import { onBeforeUnmount, ref, useId, watch } from "vue";
import { gsap } from "gsap";

const props = defineProps({ reducedMotion: Boolean, exiting: Boolean });
const live = ref(null);
const trails = ref([]);
const id = useId();
const maskId = `echo-reveal-mask-${id}`;
const featherId = `echo-reveal-feather-${id}`;
const inkId = `echo-reveal-ink-${id}`;
const mistId = `echo-reveal-mist-${id}`;
let active = false;
let trailIndex = 0;
let lastTrail = null;

const waves = Array.from({ length: 33 }, (_, index) => {
  const y = index * 34 - 64;
  const bend = Math.sin(index * 0.16) * 43;
  return `M -100 ${y} C 130 ${y + 90 + bend}, 210 ${y - 115}, 390 ${y - 44} S 665 ${y + 145}, 860 ${y + 48} S 1180 ${y - 122 + bend}, 1540 ${y + 32}`;
});
const contours = Array.from({ length: 14 }, (_, index) => {
  const rx = 42 + index * 17;
  const ry = 26 + index * 11;
  return `M ${286 - rx} 624 C ${286 - rx * 1.09} ${624 - ry}, ${286 + rx * 0.38} ${624 - ry * 1.48}, ${286 + rx} ${624 - ry * 0.34} S ${286 + rx * 0.87} ${624 + ry * 1.2}, 286 ${624 + ry} S ${286 - rx * 1.04} ${624 + ry * 0.42}, ${286 - rx} 624 Z`;
});
const stars = Array.from({ length: 38 }, (_, index) => ({
  x: 38 + ((index * 173) % 1380),
  y: 35 + ((index * 127) % 890),
  radius: index % 5 === 0 ? 2.2 : 1.2,
}));

const circles = () => [live.value, ...trails.value].filter(Boolean);
const position = (circle, x, y) => {
  circle.setAttribute("cx", x.toFixed(2));
  circle.setAttribute("cy", y.toFixed(2));
};
const move = (x, y) => {
  if (props.reducedMotion || props.exiting || !live.value) return;
  position(live.value, x, y);
  if (!active) {
    active = true;
    gsap.to(live.value, { opacity: 1, duration: 0.14, ease: "power2.out", overwrite: true });
  }
  const now = performance.now();
  if (lastTrail && (now - lastTrail.time < 55 || Math.hypot(x - lastTrail.x, y - lastTrail.y) < 30))
    return;
  const circle = trails.value[trailIndex];
  if (!circle) return;
  gsap.killTweensOf(circle);
  position(circle, x, y);
  gsap.fromTo(
    circle,
    { opacity: 0.72 },
    { opacity: 0, duration: 1.3, ease: "power2.out", overwrite: true },
  );
  trailIndex = (trailIndex + 1) % 6;
  lastTrail = { x, y, time: now };
};
const reset = () => {
  active = false;
  lastTrail = null;
  gsap.to(circles(), { opacity: 0, duration: 0.55, ease: "power2.out", overwrite: true });
};
const stop = () => {
  active = false;
  lastTrail = null;
  trailIndex = 0;
  const targets = circles();
  gsap.killTweensOf(targets);
  targets.forEach((circle) => {
    circle.style.opacity = "0";
    circle.setAttribute("cx", "0");
    circle.setAttribute("cy", "0");
  });
};
const fadeOut = () => {
  active = false;
  lastTrail = null;
  gsap.killTweensOf(circles());
  gsap.to(circles(), { opacity: 0, duration: 0.36, ease: "sine.out" });
};

watch(
  () => props.reducedMotion,
  (inactive) => {
    if (inactive) stop();
  },
);
watch(
  () => props.exiting,
  (inactive) => {
    if (inactive) fadeOut();
  },
);
onBeforeUnmount(stop);
defineExpose({ move, reset, stop, fadeOut });
</script>

<template>
  <svg
    class="welcome-reveal"
    aria-hidden="true"
    focusable="false"
    xmlns="http://www.w3.org/2000/svg"
  >
    <defs>
      <radialGradient :id="featherId">
        <stop offset="0" stop-color="white" />
        <stop offset="0.38" stop-color="white" stop-opacity="0.96" />
        <stop offset="0.7" stop-color="white" stop-opacity="0.48" />
        <stop offset="1" stop-color="white" stop-opacity="0" />
      </radialGradient>
      <linearGradient :id="inkId" x1="0" y1="1" x2="1" y2="0">
        <stop offset="0" stop-color="#59ddc2" />
        <stop offset="0.48" stop-color="#75caff" />
        <stop offset="1" stop-color="#4899ec" />
      </linearGradient>
      <radialGradient :id="mistId" cx="48%" cy="48%" r="75%">
        <stop offset="0" stop-color="#123d60" stop-opacity="0.62" />
        <stop offset="1" stop-color="#0a2b49" stop-opacity="0.36" />
      </radialGradient>
      <mask
        :id="maskId"
        maskUnits="userSpaceOnUse"
        x="0"
        y="0"
        width="100%"
        height="100%"
        mask-type="alpha"
      >
        <circle
          ref="live"
          data-reveal-live
          cx="0"
          cy="0"
          r="200"
          :fill="`url(#${featherId})`"
          style="opacity: 0"
        />
        <circle
          v-for="index in 6"
          :key="index"
          ref="trails"
          data-reveal-trail
          cx="0"
          cy="0"
          r="135"
          :fill="`url(#${featherId})`"
          style="opacity: 0"
        />
      </mask>
    </defs>
    <g class="welcome-reveal-pattern" :mask="`url(#${maskId})`">
      <svg viewBox="0 0 1440 960" width="100%" height="100%" preserveAspectRatio="xMidYMid slice">
        <rect width="1440" height="960" :fill="`url(#${mistId})`" />
        <g
          :stroke="`url(#${inkId})`"
          fill="none"
          stroke-linecap="round"
          stroke-width="1.35"
          opacity="0.66"
        >
          <path
            v-for="(wave, index) in waves"
            :key="`wave-${index}`"
            :d="wave"
            :opacity="index % 4 === 0 ? 0.95 : 0.54"
          />
          <g opacity="0.75" transform="rotate(-18 286 624)">
            <path v-for="(contour, index) in contours" :key="`contour-${index}`" :d="contour" />
          </g>
          <path
            d="M 922 206 Q 1047 107 1196 185 T 1420 263 M 952 229 Q 1058 149 1192 209 T 1417 286 M 982 250 Q 1071 188 1187 232 T 1412 309 M 1012 269 Q 1083 220 1182 254 T 1406 332"
            opacity="0.8"
          />
        </g>
        <g fill="#a0e7ef">
          <circle
            v-for="(star, index) in stars"
            :key="`star-${index}`"
            :cx="star.x"
            :cy="star.y"
            :r="star.radius"
            :opacity="index % 5 === 0 ? 0.8 : 0.44"
          />
        </g>
      </svg>
    </g>
  </svg>
</template>

<style scoped>
.welcome-reveal {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  overflow: hidden;
  pointer-events: none;
}
</style>
