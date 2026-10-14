import { ref, computed } from "vue";
import { defineStore } from "pinia";
import { AI_ROLES, getRoleById } from "../utils/aiRoles.js";
import { DEEPSEEK_MODES, getDeepSeekMode } from "../config/deepseekModes.js";

// 默认会话名称，用于初始化以及兜底
const DEFAULT_SESSION_NAME = "新对话";
// 默认角色 ID
const DEFAULT_ROLE = "general";

const MODEL_OPTIONS = DEEPSEEK_MODES;

const formatFileSize = (size) => {
  if (size < 1024) return `${size}B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`;
  return `${(size / (1024 * 1024)).toFixed(1)}MB`;
};

// 将附件对象描述为更易读的字符串，方便拼接到模型上下文
const describeAttachment = (attachment) => {
  if (!attachment) return "";
  const { name, size, type, body, note } = attachment;
  const header = [`文件名: ${name}`, `大小: ${formatFileSize(size)}`];
  if (type) {
    header.push(`类型: ${type}`);
  }

  const bodyText = body
    ? `内容预览:\n${(body || "").slice(0, 4000)}`
    : note || "未提供内容";

  return `${header.join(" | ")}\n${bodyText}`;
};

export const useSessionStore = defineStore(
  "session",
  () => {
    const session = ref({ [DEFAULT_SESSION_NAME]: [] });
    const curname = ref(DEFAULT_SESSION_NAME);
    const time = ref({});
    const visibility = ref({ [DEFAULT_SESSION_NAME]: false });
    const pendingConversation = ref(DEFAULT_SESSION_NAME);
    const model = ref(MODEL_OPTIONS[0].value);
    const sessionRoles = ref({ [DEFAULT_SESSION_NAME]: DEFAULT_ROLE });
    const roleContextStart = ref({ [DEFAULT_SESSION_NAME]: 0 });

    if ((session.value[DEFAULT_SESSION_NAME]?.length ?? 0) > 0) {
      visibility.value[DEFAULT_SESSION_NAME] = true;
      pendingConversation.value = null;
    }

    /**
     * 确保某个会话的相关数据结构已初始化，避免访问 undefined。
     */
    const ensureConversation = (
      name = curname.value,
      { makeVisibleIfNew = true } = {},
    ) => {
      const exists = !!session.value[name];

      if (!exists) {
        session.value[name] = [];
      }
      if (time.value[name] === undefined) {
        time.value[name] = exists ? Date.now() : 0;
      }
      if (sessionRoles.value[name] === undefined) {
        sessionRoles.value[name] = DEFAULT_ROLE;
      }
      if (roleContextStart.value[name] === undefined) {
        roleContextStart.value[name] = 0;
      }

      if (visibility.value[name] === undefined) {
        visibility.value[name] = session.value[name].length > 0;
      }

      if (!exists && !makeVisibleIfNew) {
        visibility.value[name] = false;
        pendingConversation.value = name;
      } else if (!exists) {
        visibility.value[name] = true;
      }
    };

    const generateConversationName = () => {
      const base = DEFAULT_SESSION_NAME;
      if (!session.value[base]) {
        return base;
      }

      let index = 1;
      let candidate = `${base} ${index}`;
      while (session.value[candidate]) {
        index += 1;
        candidate = `${base} ${index}`;
      }
      return candidate;
    };

    /**
     * 向当前会话追加一条消息，同时记录最近活跃时间。
     */
    const sessionpush = (msg) => {
      const key = curname.value;
      ensureConversation(key);
      const normalized = {
        role: msg.role,
        content: msg.content ?? "",
        attachments: Array.isArray(msg.attachments) ? msg.attachments : [],
        roleId: msg.roleId ?? sessionRoles.value[key],
      };
      session.value[key].push(normalized);
      time.value[key] = Date.now();
      visibility.value[key] = true;
      if (pendingConversation.value === key) {
        pendingConversation.value = null;
      }
      return session.value[key][session.value[key].length - 1];
    };

    const setModel = (value) => {
      model.value = getDeepSeekMode(value).value;
    };

    // 设置当前 AI 角色（仅对当前会话生效）
    const setRole = (roleId) => {
      if (AI_ROLES[roleId]) {
        ensureConversation();
        const key = curname.value;
        const previousRole = sessionRoles.value[key];

        if (previousRole === roleId) {
          return;
        }

        sessionRoles.value[key] = roleId;

        if ((session.value[key]?.length ?? 0) > 0) {
          roleContextStart.value[key] = session.value[key].length;
        }
      }
    };

    // 获取当前角色配置
    const getCurrentRole = () => {
      ensureConversation();
      return getRoleById(sessionRoles.value[curname.value]);
    };

    // 计算属性形式的当前角色（用于 v-model 绑定）
    const currentRole = computed({
      get: () => {
        ensureConversation();
        const roleId = sessionRoles.value[curname.value];
        return AI_ROLES[roleId] ? roleId : DEFAULT_ROLE;
      },
      set: (roleId) => {
        setRole(roleId);
      },
    });

    /**
     * 返回所有可见会话的名称列表。
     */
    const getAllSessions = () =>
      Object.keys(session.value).filter((name) => {
        if (visibility.value[name] === undefined) {
          visibility.value[name] = session.value[name].length > 0;
        }
        return visibility.value[name] !== false;
      });

    /**
     * 创建一个空白会话，标记为待输入状态。
     */
    const createBlankConversation = (name) => {
      session.value[name] = [];
      time.value[name] = 0;
      sessionRoles.value[name] = DEFAULT_ROLE;
      roleContextStart.value[name] = 0;
      visibility.value[name] = false;
      pendingConversation.value = name;
    };

    /**
     * 清空所有历史记录并创建新的占位会话。
     */
    const clear = () => {
      session.value = {};
      time.value = {};
      sessionRoles.value = {};
      roleContextStart.value = {};
      visibility.value = {};
      const name = generateConversationName();
      createBlankConversation(name);
      curname.value = name;
    };

    /**
     * 更新当前会话标题，若目标标题已存在则切换到该会话。
     */
    const updateTitle = (newTitle) => {
      const trimmed = newTitle?.trim();
      if (!trimmed) {
        return;
      }

      const current = curname.value;
      if (trimmed === current) {
        return;
      }

      if (session.value[trimmed]) {
        curname.value = trimmed;
        visibility.value[trimmed] = true;
        pendingConversation.value = null;
        return;
      }

      ensureConversation(current);

      session.value[trimmed] = session.value[current];
      sessionRoles.value[trimmed] = sessionRoles.value[current];
      roleContextStart.value[trimmed] = roleContextStart.value[current];
      if (time.value[current]) {
        time.value[trimmed] = time.value[current];
      }

      visibility.value[trimmed] = true;

      delete session.value[current];
      delete sessionRoles.value[current];
      delete roleContextStart.value[current];
      delete time.value[current];
      delete visibility.value[current];

      curname.value = trimmed;
      pendingConversation.value = null;
    };

    const removeMessageAt = (index) => {
      ensureConversation();
      const key = curname.value;
      const messages = session.value[key];
      if (!messages || index < 0 || index >= messages.length) {
        return;
      }

      messages.splice(index, 1);

      const currentContextStart = roleContextStart.value[key] ?? 0;
      if (index < currentContextStart) {
        roleContextStart.value[key] = Math.max(0, currentContextStart - 1);
      } else {
        roleContextStart.value[key] = Math.min(
          currentContextStart,
          messages.length,
        );
      }

      if (!messages.length) {
        time.value[key] = 0;
        roleContextStart.value[key] = 0;
      }
    };

    const trimMessagesFrom = (startIndex) => {
      ensureConversation();
      const key = curname.value;
      const messages = session.value[key];
      if (!messages || startIndex < 0) {
        return;
      }

      if (startIndex < messages.length) {
        session.value[key] = messages.slice(0, startIndex);
        roleContextStart.value[key] = Math.min(
          roleContextStart.value[key] ?? 0,
          session.value[key].length,
        );
      }
    };

    const deletehistory = (name) => {
      const wasCurrent = name === curname.value;
      delete session.value[name];
      delete time.value[name];
      delete sessionRoles.value[name];
      delete roleContextStart.value[name];
      delete visibility.value[name];

      if (pendingConversation.value === name) {
        pendingConversation.value = null;
      }

      const remaining = Object.keys(session.value);

      if (wasCurrent) {
        const fallback = remaining
          .map((key) => ({ key, updatedAt: time.value[key] ?? 0 }))
          .sort((a, b) => b.updatedAt - a.updatedAt)[0]?.key;

        if (fallback) {
          ensureConversation(fallback);
          curname.value = fallback;
          return;
        }

        const fallbackName = generateConversationName();
        createBlankConversation(fallbackName);
        curname.value = fallbackName;
      }
    };

    /**
     * 切换当前会话，必要时自动初始化数据。
     */
    const selecthistory = (name) => {
      if (name && curname.value !== name) {
        ensureConversation(name);
        curname.value = name;
      }
    };

    /**
     * 获取当前会话的消息列表，附带虚拟滚动所需的 key。
     */
    const getcurmsgs = () => {
      ensureConversation();
      const currentMessages = session.value[curname.value];

      return currentMessages.map((item, idx) => ({
        ...item,
        attachments: Array.isArray(item.attachments) ? item.attachments : [],
        _key: `${item.role}-${idx}`,
      }));
    };

    /**
     * 创建新的对话。当存在未使用的占位对话时直接切换过去。
     */
    const newchat = () => {
      if (
        pendingConversation.value &&
        session.value[pendingConversation.value] &&
        (session.value[pendingConversation.value]?.length ?? 0) === 0
      ) {
        curname.value = pendingConversation.value;
        ensureConversation(curname.value, { makeVisibleIfNew: false });
        return { created: false, name: curname.value };
      }

      const name = generateConversationName();
      createBlankConversation(name);
      curname.value = name;
      return { created: true, name };
    };

    /**
     * 将流式响应追加到最后一条消息中。
     */
    const adddelta = (delta) => {
      ensureConversation();
      const key = curname.value;
      const messages = session.value[key];
      const lastMessage = messages[messages.length - 1];

      if (lastMessage) {
        lastMessage.content += delta;
      }
    };

    /**
     * 将消息和附件概述拼接成模型可读的输入。
     */
    const getMessagesForModel = () => {
      ensureConversation();
      const key = curname.value;
      const contextStart = Math.min(
        roleContextStart.value[key] ?? 0,
        session.value[key].length,
      );

      return session.value[key].slice(contextStart).map((item) => {
        const attachmentsText =
          item.attachments && item.attachments.length
            ? `\n\n附件:\n${item.attachments
                .map((attachment) => describeAttachment(attachment))
                .join("\n\n")}`
            : "";

        const content = `${item.content ?? ""}${attachmentsText}`.trim();

        return {
          role: item.role,
          content: content || "(空消息)",
        };
      });
    };

    return {
      session,
      curname,
      sessionpush,
      getcurmsgs,
      adddelta,
      getAllSessions,
      newchat,
      clear,
      deletehistory,
      selecthistory,
      time,
      updateTitle,
      getMessagesForModel,
      visibility,
      pendingConversation,
      removeMessageAt,
      trimMessagesFrom,
      model,
      modelOptions: MODEL_OPTIONS,
      setModel,
      currentRole,
      setRole,
      getCurrentRole,
      sessionRoles,
      roleContextStart,
    };
  },
  {
    persist: {
      afterHydrate: ({ store }) => store.setModel(store.model),
    },
  },
);
