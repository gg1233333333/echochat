// src/utils/aiRoles.js
// AI 角色配置系统 - 支持通用助手与程序员助手切换

export const AI_ROLES = {
  general: {
    id: "general",
    name: "通用助手",
    description: "适合日常问答、学习、写作和生活类问题",
    systemPrompt: `你是一个友好、专业、乐于助人的 AI 助手。
你可以回答用户提出的各类问题，包括技术问题、学习问题、写作问题和生活问题等。
回答时尽量做到：
- 信息准确、结构清晰
- 语气自然、友好、直接
- 对复杂问题给出分步骤解释
- 在用户信息不足时，先基于现有信息给出最有帮助的回答，再指出关键前提`,
    icons: {
      favicon: "/favicon.svg",
    },
  },

  developer: {
    id: "developer",
    name: "程序员助手",
    description: "专注编程、调试、架构设计和工程实践问题",
    systemPrompt: `你是一个专业的程序员助手。
你专注回答软件开发相关问题，包括但不限于：
- 编程语言与语法
- Bug 排查与修复
- 代码生成、重构与代码审查
- 前端 / 后端 / 数据库 / 运维 / 云服务
- 算法、数据结构与性能优化
- 架构设计、工程化、测试与部署

如果用户提出明显与软件开发无关的问题，请礼貌说明当前处于【程序员助手模式】，
并建议用户切换到【通用助手】模式继续提问。
拒绝时保持简短，不要编造无关答案。`,
    icons: {
      favicon: "/faviconcode.svg",
    },
  },
};

export function getAllRoles() {
  return Object.values(AI_ROLES);
}

export function getRoleById(roleId) {
  return AI_ROLES[roleId] || AI_ROLES.general;
}

export function isDeveloperMode(roleId) {
  return roleId === "developer";
}

const NON_TECHNICAL_KEYWORDS = [
  "天气",
  "笑话",
  "故事",
  "颜色",
  "爱好",
  "喜欢",
  "讨厌",
  "情感",
  "感情",
  "恋爱",
  "婚姻",
  "生活",
  "娱乐",
  "电影",
  "音乐",
  "旅行",
  "美食",
  "健康",
  "医疗",
  "医生",
  "星座",
  "运势",
  "算命",
  "彩票",
  "股票",
  "投资",
  "理财",
  "聊聊天",
];

export function isLikelyNonTechnical(text = "") {
  const normalized = text.trim().toLowerCase();
  if (!normalized) {
    return false;
  }

  return NON_TECHNICAL_KEYWORDS.some((keyword) =>
    normalized.includes(keyword.toLowerCase()),
  );
}
