import test from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";
import { useThemeStore } from "../src/stores/theme.js";

test("system theme continues updating until the user explicitly chooses a mode", () => {
  let stored = null, listener;
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: () => stored, setItem: (_key, value) => { stored = value; },
  } });
  Object.defineProperty(globalThis, "window", { configurable: true, value: {
    matchMedia: () => ({ matches: true, addEventListener: (_event, handler) => { listener = handler; }, removeEventListener: () => {} }),
  } });
  setActivePinia(createPinia());
  const store = useThemeStore();
  store.initialize();
  assert.equal(store.mode, "dark");
  assert.equal(stored, null);
  listener({ matches: false });
  assert.equal(store.mode, "light");
  store.toggleMode();
  assert.equal(JSON.parse(stored).mode, "dark");
  listener({ matches: false });
  assert.equal(store.mode, "dark");
  store.cleanup();
});
