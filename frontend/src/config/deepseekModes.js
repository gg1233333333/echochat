export const DEEPSEEK_MODES = Object.freeze([
  {
    label: "推理增强（复杂问题）",
    value: "thinking",
  },
  {
    label: "智能对话（快速响应）",
    value: "non-thinking",
  },
]);

export function getDeepSeekMode(value) {
  const migratedValue =
    value === "deepseek-reasoner"
      ? "thinking"
      : value === "deepseek-chat"
        ? "non-thinking"
        : value;
  const mode = DEEPSEEK_MODES.find((item) => item.value === migratedValue);
  if (!mode) {
    throw new Error(`不支持的 DeepSeek 模式: ${value}`);
  }
  return mode;
}
