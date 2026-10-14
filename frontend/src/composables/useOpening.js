import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { gsap } from "gsap";
import { Flip } from "gsap/Flip";

gsap.registerPlugin(Flip);
const VISITED_KEY = "echochat.opening.v1";
const clearMotion =
  "transform,opacity,visibility,position,top,left,width,height,color,filter,zIndex,transition";
const headerTools = ".header > :not(#echo-header-brand)";

export function useOpening({
  workspace,
  stage,
  brand,
  hasMessages,
  getBrandDock,
  getBrandCompact,
  canReplay,
}) {
  let visited = false;
  try {
    visited = localStorage.getItem(VISITED_KEY) === "seen";
  } catch {
    /* Storage may be unavailable. */
  }
  const phase = ref(visited ? "resume" : "welcome");
  const mounted = ref(false);
  const docked = ref(visited);
  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const reducedMotion = ref(motionQuery.matches);
  const active = computed(() => phase.value !== "chat");
  const full = computed(() => phase.value === "welcome" || phase.value === "entering");
  const brandTarget = computed(() => (docked.value ? getBrandDock() : "#echo-intro-brand"));
  const cardTarget = computed(() =>
    !docked.value ? "#echo-intro-suggestions" : hasMessages.value ? null : "#echo-chat-suggestions",
  );
  let timeline;
  let flip;
  let revision = 0;

  const brandElements = () =>
    [
      document.querySelector("[data-echo-logo]"),
      document.querySelector("[data-echo-title]"),
    ].filter(Boolean);
  const cards = () => Array.from(document.querySelectorAll("[data-inspiration]"));
  const entranceParts = () =>
    workspace.value?.querySelectorAll(
      `.new-chat-btn,.search-input,.history-heading,.conversation-list,.rail-button,.sidebar-footer,${headerTools},.content,.container,.chat-empty > .empty-brand,.chat-empty > h1,.chat-empty > p`,
    ) || [];
  const stop = () => {
    flip?.revert();
    timeline?.kill();
    timeline = null;
    flip = null;
    stage.value?.prepareExit();
    brand.value?.stopAnimation();
  };
  const clear = () => {
    gsap.set([...brandElements(), ...cards(), ...entranceParts()], { clearProps: clearMotion });
    if (workspace.value)
      gsap.set(workspace.value.querySelectorAll(".sideright,.sideleft"), {
        clearProps:
          "--canvas-reveal,--canvas-offset,--canvas-scale,--sidebar-opacity,backgroundColor",
      });
    if (workspace.value) gsap.set(workspace.value, { clearProps: "opacity,visibility" });
  };
  const finish = async () => {
    if (phase.value === "chat") return;
    const current = ++revision;
    stop();
    docked.value = true;
    try {
      localStorage.setItem(VISITED_KEY, "seen");
    } catch {
      /* Entry does not depend on persistence. */
    }
    await nextTick();
    if (current !== revision) return;
    phase.value = "chat";
    await nextTick();
    if (current !== revision) return;
    // The welcome scene also owns styles on the shared cards until it unmounts.
    clear();
    workspace.value?.querySelector("textarea.inputbox")?.focus({ preventScroll: true });
  };

  const enter = async () => {
    if (phase.value !== "welcome") return;
    if (reducedMotion.value) {
      await finish();
      return;
    }
    const current = ++revision;
    stop();
    phase.value = "entering";
    const scene = stage.value?.stage;
    const originalCards = cards();
    gsap.set(originalCards, { transition: "none" });
    const logo = document.querySelector("[data-echo-logo]");
    const logoBounds = logo.getBoundingClientRect();
    const startX = logoBounds.x + logoBounds.width / 2;
    const startY = logoBounds.bottom + 12;
    const compact = getBrandCompact();
    timeline = gsap.timeline({ paused: true });
    timeline.to(
      scene?.querySelectorAll(".welcome-rings"),
      { scale: 0.88, duration: 0.18, ease: "power2.inOut" },
      0,
    );
    originalCards.forEach((card) => {
      const bounds = card.getBoundingClientRect();
      timeline.to(
        card,
        {
          x: (startX - bounds.x - bounds.width / 2) * 0.12,
          y: (startY - bounds.y) * 0.08,
          scale: 0.95,
          opacity: 0,
          duration: 0.18,
          ease: "power2.inOut",
        },
        0,
      );
    });
    if (compact) timeline.to("[data-echo-title]", { autoAlpha: 0, duration: 0.12 }, 0);
    timeline.play();
    await new Promise((resolve) => setTimeout(resolve, 180));
    if (current !== revision) return;
    timeline.pause();
    const targets = compact ? [logo] : brandElements();
    const state = Flip.getState(targets, {
      props: "color,backgroundColor,borderColor,borderRadius",
    });
    gsap.set(originalCards, { clearProps: "transform" });
    docked.value = true;
    await nextTick();
    if (current !== revision) return;
    gsap.set(workspace.value, { autoAlpha: 1 });
    gsap.set(entranceParts(), { autoAlpha: 0 });
    flip = Flip.from(state, {
      duration: 1.04,
      absolute: true,
      scale: true,
      ease: "sine.inOut",
      paused: true,
      zIndex: 40,
    });
    timeline.add(flip, 0.18);
    // A paused child is not advanced by its parent timeline.
    flip.paused(false);
    timeline.fromTo(
      workspace.value.querySelector(".sideright"),
      { "--canvas-reveal": "110%", "--canvas-offset": "16px", "--canvas-scale": 0.985 },
      {
        "--canvas-reveal": "-10%",
        "--canvas-offset": "0px",
        "--canvas-scale": 1,
        duration: 0.88,
        ease: "sine.inOut",
      },
      0.24,
    );
    timeline.to(
      workspace.value.querySelector(".sideleft"),
      { "--sidebar-opacity": 1, duration: 0.72, ease: "sine.inOut" },
      0.28,
    );
    timeline.to(
      scene?.querySelectorAll(".welcome-core,.welcome-rings"),
      { autoAlpha: 0, duration: 0.62, ease: "sine.out" },
      0.24,
    );
    timeline.to(
      scene?.querySelectorAll(".welcome-actions,.welcome-subtitle"),
      { autoAlpha: 0, duration: 0.28 },
      0.16,
    );
    timeline.to(
      scene?.querySelectorAll(
        ".welcome-particles,.welcome-aurora,.welcome-pointer-glow,.welcome-backdrop,.welcome-reveal",
      ),
      { autoAlpha: 0, duration: 1.0, ease: "sine.inOut" },
      0.25,
    );
    timeline.to(scene, { autoAlpha: 0, duration: 0.46, ease: "sine.out" }, 0.85);
    timeline.fromTo(
      workspace.value.querySelectorAll(
        ".new-chat-btn,.search-input,.history-heading,.conversation-list,.rail-button,.sidebar-footer",
      ),
      { x: -8 },
      { x: 0, autoAlpha: 1, duration: 0.3, stagger: 0.025, ease: "sine.out" },
      0.68,
    );
    timeline.to(
      workspace.value.querySelectorAll(headerTools),
      { autoAlpha: 1, duration: 0.3 },
      0.95,
    );
    timeline.to(workspace.value.querySelector(".container"), { autoAlpha: 1, duration: 0.3 }, 1.0);
    timeline.to(
      workspace.value.querySelectorAll(
        ".content,.chat-empty > .empty-brand,.chat-empty > h1,.chat-empty > p",
      ),
      { autoAlpha: 1, duration: 0.28 },
      1.05,
    );
    if (!hasMessages.value) timeline.to(cards(), { opacity: 1, duration: 0.3 }, 1.03);
    timeline.call(
      () => {
        if (current === revision) void finish();
      },
      [],
      1.38,
    );
    timeline.play(0.18);
  };

  const replay = async () => {
    if (phase.value !== "chat" || !canReplay()) return;
    ++revision;
    stop();
    clear();
    docked.value = false;
    phase.value = "welcome";
    await nextTick();
    document.querySelector(".welcome-stage")?.focus({ preventScroll: true });
  };
  const resize = () => {
    if (phase.value === "entering" || phase.value === "resume") void finish();
  };
  const changeMotion = (event) => {
    reducedMotion.value = event.matches;
    if (event.matches && (phase.value === "entering" || phase.value === "resume")) void finish();
  };
  onMounted(async () => {
    mounted.value = true;
    motionQuery.addEventListener("change", changeMotion);
    window.addEventListener("resize", resize);
    await nextTick();
    if (phase.value === "resume") {
      if (reducedMotion.value) {
        void finish();
        return;
      }
      gsap.set(workspace.value, { autoAlpha: 1 });
      timeline = gsap.timeline({
        onComplete: () => {
          void finish();
        },
      });
      timeline.from(brandElements(), { autoAlpha: 0, y: 3, duration: 0.18 });
      timeline.from(entranceParts(), { autoAlpha: 0, duration: 0.18 }, 0.05);
    }
  });
  onBeforeUnmount(() => {
    ++revision;
    stop();
    motionQuery.removeEventListener("change", changeMotion);
    window.removeEventListener("resize", resize);
  });
  return {
    phase,
    mounted,
    active,
    full,
    docked,
    reducedMotion,
    brandTarget,
    cardTarget,
    enter,
    replay,
  };
}
