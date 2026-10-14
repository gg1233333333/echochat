<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { gsap } from "gsap";
import BackgroundReveal from "./BackgroundReveal.vue";

const props = defineProps({ reducedMotion: Boolean, exiting: Boolean });
const emit = defineEmits(["enter"]);
const stage = ref(null);
const startButton = ref(null);
const backgroundReveal = ref(null);
const ready = ref(false);
const coreHovered = ref(false);
let context;
let startupTimeline;
let pointerFrame;
let latestPointer;
let prepared = false;
let particleMotion = [];

const cancelPointerFrame = () => {
  if (pointerFrame) cancelAnimationFrame(pointerFrame);
  pointerFrame = null;
  latestPointer = null;
};

const particles = Array.from({ length: 23 }, (_, index) => ({
  x: 7 + ((index * 37) % 86),
  y: 10 + ((index * 29) % 78),
  size: index % 4 === 0 ? 3 : 2,
  opacity: 0.2 + (index % 5) * 0.1,
}));

const prepareExit = () => {
  prepared = true;
  ready.value = true;
  if (!props.reducedMotion) startupTimeline?.progress(1);
  startupTimeline?.kill();
  context?.getTweens().forEach((tween) => tween.kill());
  cancelPointerFrame();
  backgroundReveal.value?.fadeOut();
  if (stage.value) gsap.set(stage.value, { "--eyes-x": "0px", "--eyes-y": "0px" });
};
const enter = () => {
  if (!ready.value || props.exiting) return;
  emit("enter");
};
const updatePointer = (event) => {
  if (event.pointerType === "touch") {
    backgroundReveal.value?.stop();
    return;
  }
  if (props.reducedMotion || props.exiting || prepared) return;
  latestPointer = { x: event.clientX, y: event.clientY };
  if (pointerFrame) return;
  pointerFrame = requestAnimationFrame(() => {
    pointerFrame = null;
    if (props.reducedMotion || props.exiting || prepared) return;
    const bounds = stage.value?.getBoundingClientRect();
    if (!bounds || !latestPointer) return;
    backgroundReveal.value?.move(latestPointer.x - bounds.left, latestPointer.y - bounds.top);
    const x = Math.max(-1, Math.min(1, ((latestPointer.x - bounds.left) / bounds.width - 0.5) * 2));
    const y = Math.max(-1, Math.min(1, ((latestPointer.y - bounds.top) / bounds.height - 0.5) * 2));
    const logo = stage.value.querySelector("[data-echo-logo]");
    const matrix = logo?.getScreenCTM();
    if (!matrix) return;
    const point = new DOMPoint(latestPointer.x, latestPointer.y).matrixTransform(matrix.inverse());
    const eyeX = (point.x - 60) / 140;
    const eyeY = (point.y - 66.5) / 140;
    const limit = Math.max(1, Math.hypot(eyeX, eyeY));
    const particleBounds = stage.value.querySelector(".welcome-particles").getBoundingClientRect();
    particleMotion.forEach((motion, index) => {
      const dx =
        particleBounds.left + (particleBounds.width * particles[index].x) / 100 - latestPointer.x;
      const dy =
        particleBounds.top + (particleBounds.height * particles[index].y) / 100 - latestPointer.y;
      const distance = Math.hypot(dx, dy);
      const push = Math.max(0, 1 - distance / 200) ** 2 * 28;
      const directionX = distance > 0.001 ? dx / distance : Math.cos(index * 2.4);
      const directionY = distance > 0.001 ? dy / distance : Math.sin(index * 2.4);
      motion.x(directionX * push);
      motion.y(directionY * push);
    });
    context?.add(() => {
      gsap.to(stage.value, {
        "--aurora-x": `${x * 12}px`,
        "--aurora-y": `${y * 8}px`,
        "--cards-x": `${x * 24}px`,
        "--cards-y": `${y * 18}px`,
        "--particles-x": `${x * 9}px`,
        "--particles-y": `${y * 6}px`,
        "--core-rotation-x": `${-y * 6}deg`,
        "--core-rotation-y": `${x * 8}deg`,
        "--glint-x": `${50 + x * 24}%`,
        "--glint-y": `${30 + y * 20}%`,
        "--pointer-x": `${(x + 1) * 50}%`,
        "--pointer-y": `${(y + 1) * 50}%`,
        "--pointer-opacity": 1,
        duration: 0.4,
        ease: "power2.out",
        overwrite: "auto",
      });
      gsap.to(stage.value, {
        "--eyes-x": `${((eyeX / limit) * 6).toFixed(3)}px`,
        "--eyes-y": `${((eyeY / limit) * 4).toFixed(3)}px`,
        duration: 0.18,
        ease: "power2.out",
        overwrite: "auto",
      });
    });
  });
};
const resetPointer = () => {
  cancelPointerFrame();
  if (props.reducedMotion || props.exiting || prepared) return;
  backgroundReveal.value?.reset();
  particleMotion.forEach((motion) => {
    motion.x(0);
    motion.y(0);
  });
  context?.add(() => {
    gsap.to(stage.value, {
      "--aurora-x": "0px",
      "--aurora-y": "0px",
      "--cards-x": "0px",
      "--cards-y": "0px",
      "--particles-x": "0px",
      "--particles-y": "0px",
      "--pointer-opacity": 0,
      "--core-rotation-x": "0deg",
      "--core-rotation-y": "0deg",
      "--glint-x": "50%",
      "--glint-y": "30%",
      duration: 0.7,
      ease: "power2.out",
      overwrite: "auto",
    });
    gsap.to(stage.value, {
      "--eyes-x": "0px",
      "--eyes-y": "0px",
      duration: 0.22,
      ease: "power2.out",
      overwrite: "auto",
    });
  });
};
const leaveWindow = (event) => {
  if (event.relatedTarget === null) resetPointer();
};
const moveButton = (event) => {
  if (props.reducedMotion || props.exiting || prepared || event.pointerType === "touch") return;
  const bounds = startButton.value.getBoundingClientRect();
  context?.add(() => {
    gsap.to(startButton.value, {
      x: (event.clientX - bounds.left - bounds.width / 2) * 0.055,
      y: (event.clientY - bounds.top - bounds.height / 2) * 0.055,
      duration: 0.35,
      ease: "power2.out",
      overwrite: "auto",
    });
  });
};
const resetButton = () => {
  if (prepared) return;
  context?.add(() => gsap.to(startButton.value, { x: 0, y: 0, duration: 0.4, overwrite: "auto" }));
};
const startAnimation = () => {
  cancelPointerFrame();
  context?.revert();
  particleMotion = [];
  prepared = false;
  if (props.reducedMotion) {
    ready.value = true;
    context = gsap.context(() => {
      gsap.set(".welcome-cursor, .welcome-ripple, .welcome-sweep", { autoAlpha: 0 });
      gsap.from(".welcome-core, .welcome-subtitle, .welcome-actions", {
        autoAlpha: 0,
        duration: 0.22,
      });
    }, stage.value);
    return;
  }
  ready.value = false;
  context = gsap.context(() => {
    particleMotion = Array.from(stage.value.querySelectorAll(".welcome-particle-slot"), (slot) => ({
      x: gsap.quickTo(slot, "x", { duration: 0.65, ease: "power3.out" }),
      y: gsap.quickTo(slot, "y", { duration: 0.65, ease: "power3.out" }),
    }));
    startupTimeline = gsap.timeline();
    startupTimeline
      .set(".welcome-core, .welcome-rings, .welcome-subtitle, .welcome-actions", { autoAlpha: 0 })
      .set(".inspiration-card", { autoAlpha: 0 })
      .set(".welcome-particle", { opacity: 0.05 })
      .fromTo(
        ".welcome-cursor",
        { scaleY: 0.8, opacity: 0.35 },
        { scaleY: 1, opacity: 1, duration: 0.24, repeat: 1, yoyo: true },
        0,
      )
      .to(".welcome-cursor", { scaleY: 0.12, scaleX: 1.8, borderRadius: 50, duration: 0.22 }, 0.48)
      .to(".welcome-cursor", { autoAlpha: 0, duration: 0.2 }, 0.78)
      .fromTo(
        ".welcome-ripple",
        { scale: 0.06, opacity: 0.75 },
        { scale: 1.2, opacity: 0, duration: 1.35, ease: "power2.out" },
        0.67,
      )
      .fromTo(
        ".welcome-core",
        { scale: 0.4, autoAlpha: 0 },
        { scale: 1, autoAlpha: 1, duration: 0.95, ease: "power3.out" },
        0.65,
      )
      .set(".welcome-core", { clearProps: "transform" }, 1.6)
      .fromTo(
        ".welcome-rings",
        { scale: 0.8, rotate: -15, autoAlpha: 0 },
        { scale: 1, rotate: 0, autoAlpha: 1, duration: 1.1, ease: "power2.out" },
        0.78,
      )
      .fromTo(
        ".welcome-sweep",
        { xPercent: -170, opacity: 0 },
        { xPercent: 170, opacity: 0.45, duration: 0.9, ease: "power2.inOut" },
        0.81,
      )
      .to(".welcome-sweep", { opacity: 0, duration: 0.2 }, 1.6)
      .to(
        ".welcome-particle",
        { opacity: (index) => particles[index]?.opacity ?? 0.3, duration: 1.2, stagger: 0.035 },
        0.75,
      )
      .to(".inspiration-card", { autoAlpha: 1, duration: 0.8, stagger: 0.13 }, 1.05)
      .set(".inspiration-card", { clearProps: "opacity,visibility" }, 2.12)
      .fromTo(
        ".welcome-subtitle",
        { y: 12, autoAlpha: 0 },
        { y: 0, autoAlpha: 1, duration: 0.6 },
        1.32,
      )
      .fromTo(
        ".welcome-actions",
        { y: 12, autoAlpha: 0 },
        { y: 0, autoAlpha: 1, duration: 0.6 },
        1.44,
      )
      .call(
        () => {
          ready.value = true;
        },
        [],
        1.44,
      );
    gsap.to(".welcome-aurora-left", {
      y: 30,
      x: 12,
      scale: 1.07,
      duration: 14,
      repeat: -1,
      yoyo: true,
      ease: "sine.inOut",
    });
    gsap.to(".welcome-aurora-right", {
      y: -25,
      x: -15,
      scale: 0.96,
      duration: 17,
      repeat: -1,
      yoyo: true,
      ease: "sine.inOut",
    });
    gsap.to(".welcome-ring-one", { rotate: 360, duration: 62, repeat: -1, ease: "none" });
    gsap.to(".welcome-ring-two", { rotate: -360, duration: 83, repeat: -1, ease: "none" });
    gsap.to(".welcome-particle", {
      y: (index) => (index % 2 ? -12 : 14),
      x: (index) => (index % 3 ? 5 : -9),
      duration: 9,
      stagger: 0.21,
      repeat: -1,
      yoyo: true,
      ease: "sine.inOut",
    });
  }, stage.value);
};
onMounted(async () => {
  window.addEventListener("pointermove", updatePointer, { passive: true });
  window.addEventListener("pointerout", leaveWindow);
  window.addEventListener("blur", resetPointer);
  await nextTick();
  if (stage.value && !props.exiting) startAnimation();
});
watch(
  () => props.exiting,
  (value) => {
    if (value) prepareExit();
  },
);
watch(
  () => props.reducedMotion,
  () => {
    if (stage.value && !props.exiting) startAnimation();
  },
);
onBeforeUnmount(() => {
  window.removeEventListener("pointermove", updatePointer);
  window.removeEventListener("pointerout", leaveWindow);
  window.removeEventListener("blur", resetPointer);
  prepareExit();
  context?.revert();
});
defineExpose({ prepareExit, stage, getStartupTimeline: () => startupTimeline });
</script>

<template>
  <section
    ref="stage"
    class="welcome-stage"
    :class="{ 'is-exiting': exiting, 'is-reduced': reducedMotion, 'is-core-hovered': coreHovered }"
    aria-label="欢迎来到 EchoChat"
    role="dialog"
    aria-modal="true"
    tabindex="-1"
  >
    <div class="welcome-backdrop" aria-hidden="true"></div>
    <div class="welcome-aurora" aria-hidden="true">
      <div class="welcome-aurora-left"></div>
      <div class="welcome-aurora-right"></div>
    </div>
    <BackgroundReveal ref="backgroundReveal" :reduced-motion="reducedMotion" :exiting="exiting" />
    <div class="welcome-pointer-glow" aria-hidden="true"></div>
    <div class="welcome-particles" aria-hidden="true">
      <span
        v-for="(particle, index) in particles"
        :key="index"
        class="welcome-particle-slot"
        :style="{
          left: `${particle.x}%`,
          top: `${particle.y}%`,
          width: `${particle.size}px`,
          height: `${particle.size}px`,
        }"
        ><span class="welcome-particle" :style="{ opacity: particle.opacity }"></span
      ></span>
    </div>
    <div id="echo-intro-suggestions"></div>
    <div class="welcome-composition">
      <div
        class="welcome-core-space"
        aria-hidden="true"
        @pointerenter="coreHovered = true"
        @pointerleave="coreHovered = false"
      >
        <div class="welcome-cursor"></div>
        <div class="welcome-ripple"></div>
        <div class="welcome-core">
          <div class="welcome-core-glint"></div>
          <div class="welcome-core-horizon"></div>
          <div class="welcome-sweep"></div>
        </div>
        <div class="welcome-rings">
          <svg class="welcome-ring-one" viewBox="0 0 320 320" fill="none">
            <circle cx="160" cy="160" r="146" stroke="url(#echo-ring-one)" stroke-width="1" />
            <defs>
              <linearGradient
                id="echo-ring-one"
                x1="12"
                y1="12"
                x2="310"
                y2="300"
                gradientUnits="userSpaceOnUse"
              >
                <stop stop-color="#76B6FF" stop-opacity="0.8" />
                <stop offset="0.35" stop-color="#76B6FF" stop-opacity="0.06" />
                <stop offset="0.7" stop-color="#89F0D0" stop-opacity="0.45" />
                <stop offset="1" stop-color="#76B6FF" stop-opacity="0.05" />
              </linearGradient>
            </defs>
          </svg>
          <svg class="welcome-ring-two" viewBox="0 0 320 320" fill="none">
            <circle cx="160" cy="160" r="142" stroke="url(#echo-ring-two)" stroke-width="1" />
            <circle cx="296" cy="121" r="2.6" fill="#B0EBDD" />
            <defs>
              <linearGradient
                id="echo-ring-two"
                x1="12"
                y1="310"
                x2="310"
                y2="12"
                gradientUnits="userSpaceOnUse"
              >
                <stop stop-color="#7BD5DB" stop-opacity="0.05" />
                <stop offset="0.5" stop-color="#A6D7FF" stop-opacity="0.6" />
                <stop offset="1" stop-color="#76B6FF" stop-opacity="0.07" />
              </linearGradient>
            </defs>
          </svg>
        </div>
      </div>
      <div id="echo-intro-brand"></div>
      <p class="welcome-subtitle">让想法，从这里开始。</p>
      <div class="welcome-actions">
        <button
          ref="startButton"
          class="welcome-start"
          :disabled="!ready || exiting"
          @pointermove="moveButton"
          @pointerleave="resetButton"
          @click="enter"
        >
          <span>开始对话</span>
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
            <path
              d="M4 10h12m-5-5 5 5-5 5"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.welcome-stage {
  --aurora-x: 0px;
  --aurora-y: 0px;
  --cards-x: 0px;
  --cards-y: 0px;
  --particles-x: 0px;
  --particles-y: 0px;
  --pointer-x: 50%;
  --pointer-y: 45%;
  --pointer-opacity: 0;
  --core-rotation-x: 0deg;
  --core-rotation-y: 0deg;
  --glint-x: 50%;
  --glint-y: 30%;
  --eyes-x: 0px;
  --eyes-y: 0px;
  position: fixed;
  inset: 0;
  z-index: 4000;
  overflow: hidden;
  color: #e9f1ff;
  background: transparent;
  isolation: isolate;
  perspective: 1000px;
}
.welcome-backdrop {
  position: absolute;
  inset: 0;
  z-index: -1;
  background: #071428;
}
.welcome-backdrop::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse at 50% 40%, rgb(26 63 103 / 24%), transparent 58%),
    linear-gradient(180deg, transparent 65%, rgb(4 12 24 / 45%));
}
.welcome-backdrop::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  opacity: 0.035;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 160 160' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.92' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Cpath fill='%23fff' filter='url(%23n)' opacity='.6' d='M0 0h160v160H0z'/%3E%3C/svg%3E");
}
.welcome-aurora {
  position: absolute;
  inset: -10%;
  pointer-events: none;
  transform: translate(var(--aurora-x), var(--aurora-y));
}
.welcome-aurora-left,
.welcome-aurora-right {
  position: absolute;
  width: 60%;
  height: 70%;
  border-radius: 50%;
  filter: blur(70px);
}
.welcome-aurora-left {
  left: -27%;
  top: 18%;
  background: radial-gradient(ellipse, rgb(33 98 168 / 27%), transparent 65%);
  transform: rotate(-20deg);
}
.welcome-aurora-right {
  right: -28%;
  top: -6%;
  background: radial-gradient(ellipse, rgb(40 99 168 / 23%), transparent 67%);
  transform: rotate(30deg);
}
.welcome-pointer-glow {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: var(--pointer-opacity);
  background: radial-gradient(
    circle 280px at var(--pointer-x) var(--pointer-y),
    rgb(83 159 238 / 12%),
    transparent 75%
  );
}
.welcome-particles {
  position: absolute;
  inset: 0;
  pointer-events: none;
  transform: translate(var(--particles-x), var(--particles-y));
  transition: scale 1.8s ease;
  transform-origin: 50% 40%;
}
.is-core-hovered .welcome-particles {
  scale: 0.975;
}
.welcome-particle-slot {
  position: absolute;
}
.welcome-particle {
  position: absolute;
  inset: 0;
  display: block;
  border-radius: 50%;
  background: #98c9f8;
  box-shadow: 0 0 9px rgb(113 181 251 / 40%);
}
.welcome-start:focus-visible {
  outline: 2px solid #9fcdf8;
  outline-offset: 5px;
}
.welcome-composition {
  position: absolute;
  z-index: 2;
  left: 50%;
  top: 50%;
  width: 360px;
  height: 425px;
  transform: translate(-50%, -54%);
  pointer-events: none;
}
.welcome-core-space {
  position: absolute;
  width: 268px;
  height: 268px;
  left: 46px;
  top: 0;
  pointer-events: auto;
}
.welcome-core {
  position: absolute;
  inset: 20px;
  border: 1px solid rgb(161 210 255 / 23%);
  border-radius: 50%;
  background:
    radial-gradient(
      ellipse at var(--glint-x) var(--glint-y),
      rgb(160 215 255 / 12%),
      transparent 50%
    ),
    linear-gradient(135deg, rgb(49 91 137 / 23%), rgb(15 40 72 / 15%));
  box-shadow:
    inset 0 2px 10px rgb(181 222 255 / 6%),
    inset 0 -10px 20px rgb(82 166 231 / 8%),
    0 0 65px rgb(53 123 202 / 12%);
  backdrop-filter: blur(5px);
  overflow: hidden;
  transform: rotateX(var(--core-rotation-x)) rotateY(var(--core-rotation-y));
  transition:
    box-shadow 0.9s,
    border-color 0.9s;
}
.welcome-core-glint {
  position: absolute;
  width: 140px;
  height: 70px;
  left: 8px;
  top: -23px;
  border-radius: 50%;
  background: rgb(143 210 255 / 8%);
  filter: blur(7px);
  transform: rotate(-25deg);
}
.welcome-core-horizon {
  position: absolute;
  bottom: 12%;
  left: 12%;
  right: 12%;
  height: 12%;
  border-radius: 50%;
  background: rgb(95 218 192 / 6%);
  filter: blur(12px);
}
.welcome-sweep {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 40%;
  width: 15%;
  opacity: 0;
  transform: rotate(-25deg);
  background: linear-gradient(90deg, transparent, rgb(175 224 255 / 25%), transparent);
  filter: blur(4px);
}
.welcome-rings {
  position: absolute;
  inset: -17px;
  pointer-events: none;
  transition: scale 1s cubic-bezier(0.2, 0.7, 0.2, 1);
}
.welcome-rings svg {
  position: absolute;
  width: 100%;
  height: 100%;
}
.welcome-ring-one {
  transform: rotateX(59deg) rotateZ(-26deg);
}
.welcome-ring-two {
  transform: rotateY(53deg) rotateZ(24deg);
}
.is-core-hovered .welcome-rings {
  scale: 1.065;
}
.is-core-hovered .welcome-core {
  border-color: rgb(174 220 255 / 38%);
  box-shadow:
    inset 0 2px 10px rgb(181 222 255 / 12%),
    inset 0 -10px 20px rgb(82 166 231 / 12%),
    0 0 70px rgb(53 123 202 / 20%);
}
.welcome-cursor {
  position: absolute;
  left: calc(50% - 1.5px);
  top: calc(50% - 16px);
  width: 3px;
  height: 32px;
  border-radius: 1px;
  background: #8cceff;
  box-shadow: 0 0 13px rgb(93 184 253 / 55%);
}
.welcome-ripple {
  position: absolute;
  inset: -25px;
  border: 1px solid rgb(115 195 255 / 40%);
  border-radius: 50%;
  opacity: 0;
  pointer-events: none;
}
#echo-intro-brand {
  position: absolute;
  top: 69px;
  left: 0;
  right: 0;
  pointer-events: none;
}
.welcome-subtitle {
  position: absolute;
  top: 295px;
  width: 100%;
  text-align: center;
  color: #9ab0ca;
  font-size: 16px;
  letter-spacing: 0.12em;
}
.welcome-actions {
  position: absolute;
  top: 344px;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  pointer-events: auto;
}
.welcome-start {
  position: relative;
  display: flex;
  align-items: center;
  gap: 29px;
  min-height: 51px;
  border: 1px solid rgb(128 184 255 / 34%);
  border-radius: 999px;
  padding: 12px 23px 12px 27px;
  background: #2868d7;
  box-shadow:
    0 0 20px rgb(47 120 222 / 15%),
    inset 0 1px rgb(226 241 255 / 12%);
  color: #f8fbff;
  font: inherit;
  font-size: 14px;
  cursor: pointer;
  transition:
    background 0.2s,
    box-shadow 0.3s,
    scale 0.2s;
}
.welcome-start::after {
  content: "";
  position: absolute;
  inset: -1px;
  border: 1px solid rgb(169 210 255 / 35%);
  border-radius: inherit;
  opacity: 0;
  pointer-events: none;
}
.welcome-start:hover {
  background: #3075e3;
  box-shadow: 0 0 30px rgb(47 120 222 / 25%);
}
.welcome-start:active {
  scale: 0.96;
}
.welcome-start:active::after {
  animation: button-ripple 0.65s ease-out;
}
.welcome-start svg {
  width: 18px;
  height: 18px;
}
.welcome-start:disabled {
  cursor: default;
}
#echo-intro-suggestions {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: auto;
}
.is-exiting .welcome-actions {
  pointer-events: none;
}
@keyframes button-ripple {
  0% {
    opacity: 0.6;
    scale: 1;
  }
  100% {
    opacity: 0;
    scale: 1.2;
  }
}
@media (max-width: 600px) {
  .welcome-composition {
    top: 36%;
    width: 320px;
    height: 350px;
    transform: translate(-50%, -53%);
  }
  .welcome-core-space {
    width: 230px;
    height: 230px;
    left: 45px;
  }
  .welcome-core {
    inset: 18px;
  }
  #echo-intro-brand {
    top: 60px;
  }
  .welcome-subtitle {
    top: 259px;
    font-size: 14px;
  }
  .welcome-actions {
    top: 302px;
  }
  .welcome-start {
    min-height: 48px;
    font-size: 13px;
  }
}
@media (max-height: 650px) and (min-width: 601px) {
  .welcome-composition {
    transform: translate(-50%, -50%) scale(0.82);
  }
}
@media (max-height: 740px) and (max-width: 600px) {
  .welcome-composition {
    top: 34%;
    transform: translate(-50%, -53%) scale(0.83);
  }
  .welcome-start {
    min-height: 54px;
    font-size: 15px;
  }
}
.is-reduced .welcome-core,
.is-reduced .welcome-aurora,
.is-reduced .welcome-rings {
  transform: none;
}
.is-reduced .welcome-rings,
.is-reduced .welcome-particles {
  scale: 1;
}
.is-reduced .welcome-particles {
  transition: none;
}
.is-reduced .welcome-start,
.is-reduced .welcome-core,
.is-reduced .welcome-rings {
  transition: none;
}
.is-reduced .welcome-start:active::after {
  animation: none;
}
@media (prefers-reduced-motion: reduce) {
  .welcome-stage * {
    transition: none !important;
    animation: none !important;
  }
}
</style>
