import { computed, ref } from "vue";
import { defineStore } from "pinia";

const THEME_STORAGE_KEY = "theme";

export const useThemeStore = defineStore("theme", () => {
  const mode = ref("light");
  let mediaQuery;

  const applyTheme = (value = mode.value) => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    root.dataset.theme = value;
    root.classList.toggle("dark", value === "dark");
  };

  const setMode = (value) => {
    const normalized = value === "dark" ? "dark" : "light";
    if (mode.value === normalized) {
      applyTheme(normalized);
      return;
    }
    mode.value = normalized;
    applyTheme(normalized);
  };

  const toggleMode = () => {
    setMode(mode.value === "dark" ? "light" : "dark");
  };

  const handleSystemChange = (event) => {
    if (typeof localStorage !== "undefined") {
      const stored = localStorage.getItem(THEME_STORAGE_KEY);
      if (stored) {
        // 用户已选择主题时不自动跟随系统
        return;
      }
    }
    setMode(event.matches ? "dark" : "light");
  };

  const initialize = () => {
    if (typeof window === "undefined") {
      return;
    }

    let storedMode;
    if (typeof localStorage !== "undefined") {
      try {
        storedMode = JSON.parse(localStorage.getItem(THEME_STORAGE_KEY))?.mode;
      } catch {
        storedMode = null;
      }
    }

    if (storedMode === "light" || storedMode === "dark") {
      mode.value = storedMode;
    } else {
      const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)")?.matches;
      mode.value = prefersDark ? "dark" : "light";
    }

    applyTheme();

    if (window.matchMedia) {
      mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      if (mediaQuery?.addEventListener) {
        mediaQuery.addEventListener("change", handleSystemChange);
      } else if (mediaQuery?.addListener) {
        mediaQuery.addListener(handleSystemChange);
      }
    }
  };

  const cleanup = () => {
    if (mediaQuery?.removeEventListener) {
      mediaQuery.removeEventListener("change", handleSystemChange);
    } else if (mediaQuery?.removeListener) {
      mediaQuery.removeListener(handleSystemChange);
    }
  };

  const isDark = computed(() => mode.value === "dark");

  return {
    mode,
    isDark,
    initialize,
    cleanup,
    toggleMode,
    setMode,
    applyTheme,
  };
}, {
  persist: true,
});
