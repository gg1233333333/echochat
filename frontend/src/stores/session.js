import { computed, markRaw, ref } from "vue";
import { defineStore } from "pinia";
import { api, stream } from "../apis/backend.js";

const PREFERENCE_KEY = "echochat.preferences";
const readPreferences = () => {
  try { return JSON.parse(localStorage.getItem(PREFERENCE_KEY)) || {}; }
  catch { return {}; }
};

export const useSessionStore = defineStore("chat", () => {
  const preferences = readPreferences();
  const conversations = ref({});
  const messagesByConversation = ref({});
  const pages = ref({});
  const drafts = ref({});
  const currentId = ref(preferences.currentId || null);
  const model = ref(preferences.model || "");
  const agentEnabled = ref(preferences.agentEnabled ?? true);
  const options = ref(null);
  const configured = ref(false);
  const keySettingsOpen = ref(false);
  const ready = ref(false);
  const loading = ref(false);
  const error = ref("");
  const activeGeneration = ref(null);
  let generation;
  let initialization;
  let navigationRevision = 0;
  const messageLoads = new Map();
  const currentConversation = computed(() => conversations.value[currentId.value]);
  const currentRole = computed(() => currentConversation.value?.current_role_id);
  const currentRoleMeta = computed(() => options.value?.roles.find((role) => role.id === currentRole.value));
  const messages = computed(() => messagesByConversation.value[currentId.value] || []);
  const visibleConversations = computed(() => Object.values(conversations.value)
    .filter((item) => item.message_count > 0)
    .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at)));
  const isGenerating = computed(() => !!activeGeneration.value);
  const currentDraft = computed(() => {
    if (!currentId.value) return { text: "", files: [] };
    if (!drafts.value[currentId.value]) drafts.value[currentId.value] = { text: "", files: [] };
    return drafts.value[currentId.value];
  });
  const remember = () => localStorage.setItem(PREFERENCE_KEY, JSON.stringify({ currentId: currentId.value, model: model.value, agentEnabled: agentEnabled.value }));
  const toggleAgent = () => { agentEnabled.value = !agentEnabled.value; remember(); };
  const reportError = (value) => { error.value = value?.message || String(value); };
  const setModel = (value) => {
    if (!options.value?.modes.some((item) => item.value === value)) return;
    model.value = value; remember();
  };
  const upsertConversation = (item) => {
    if (item) conversations.value[item.id] = item;
  };
  const upsertMessage = (item) => {
    if (!item || !conversations.value[item.conversation_id]) return;
    messagesByConversation.value[item.conversation_id] ||= [];
    const list = messagesByConversation.value[item.conversation_id];
    const index = list.findIndex((message) => message.id === item.id);
    if (index < 0) list.push(item);
    else list[index] = item;
    list.sort((a, b) => a.seq - b.seq);
  };
  const loadMessages = (id, older = false) => {
    if (messageLoads.has(id)) return messageLoads.get(id);
    pages.value[id] ||= { loading: false, has_more: false };
    const page = pages.value[id];
    page.loading = true;
    const pending = (async () => {
      try {
        const streamingId = generation?.conversationId === id ? generation.messageId : null;
        const before = older ? messagesByConversation.value[id]?.[0]?.seq : null;
        const result = await api(`/conversations/${id}/messages?limit=100${before ? `&before_seq=${before}` : ""}`);
        if (!conversations.value[id]) return;
        const activeId = generation?.conversationId === id ? generation.messageId : streamingId;
        const active = activeId && messagesByConversation.value[id]?.find((item) => item.id === activeId);
        const combined = new Map((older ? messagesByConversation.value[id] || [] : []).map((item) => [item.id, item]));
        result.items.forEach((item) => combined.set(item.id, item));
        // A database snapshot during a stream can lag behind its live deltas.
        if (active) combined.set(active.id, active);
        messagesByConversation.value[id] = [...combined.values()].sort((a, b) => a.seq - b.seq);
        page.has_more = result.has_more;
      } finally { page.loading = false; messageLoads.delete(id); }
    })();
    messageLoads.set(id, pending);
    return pending;
  };
  const selectConversation = async (id) => {
    navigationRevision += 1;
    currentId.value = id; remember();
    if (!messagesByConversation.value[id] || pages.value[id]?.loading) await loadMessages(id);
  };
  const newConversation = async () => {
    const revision = ++navigationRevision;
    const item = await api("/conversations", { method: "POST", body: {} });
    upsertConversation(item);
    messagesByConversation.value[item.id] ||= [];
    if (revision === navigationRevision) await selectConversation(item.id);
    return item;
  };
  const refreshConversations = async () => {
    const result = await api("/conversations?include_empty=true");
    conversations.value = Object.fromEntries(result.items.map((item) => [item.id, item]));
  };
  const initialize = async () => {
    if (initialization) return initialization;
    loading.value = true; error.value = "";
    initialization = (async () => {
      const [config, credential] = await Promise.all([api("/options"), api("/credentials/deepseek")]);
      options.value = config; configured.value = credential.configured;
      if (!config.modes.some((item) => item.value === model.value)) model.value = config.modes[0]?.value || "";
      await refreshConversations();
      if (!conversations.value[currentId.value]) currentId.value = visibleConversations.value[0]?.id || null;
      if (currentId.value) await loadMessages(currentId.value);
      else await newConversation();
      remember(); ready.value = true;
    })();
    try { await initialization; }
    catch (cause) { reportError(cause); throw cause; }
    finally { loading.value = false; initialization = null; }
  };
  const configureKey = async (key) => {
    configured.value = (await api("/credentials/deepseek", { method: "PUT", body: { api_key: key } })).configured;
  };
  const clearKey = async () => {
    configured.value = (await api("/credentials/deepseek", { method: "DELETE" })).configured;
  };
  const renameConversation = async (id, title) => upsertConversation(await api(`/conversations/${id}`, { method: "PATCH", body: { title } }));
  const setRole = async (role_id) => upsertConversation(await api(`/conversations/${currentId.value}`, { method: "PATCH", body: { role_id } }));
  const setDraftText = (text) => { if (currentId.value) currentDraft.value.text = text; };
  const addFiles = (files) => { currentDraft.value.files.push(...files.map((file) => markRaw(file))); };
  const removeFile = (index) => { currentDraft.value.files.splice(index, 1); };

  const cancelGeneration = async () => {
    const run = generation;
    if (!run) return;
    run.cancelRequested = true;
    activeGeneration.value.cancelling = true;
    if (run.cancellation) return run.cancellation;
    run.cancellation = (async () => {
      // A stop during validation must also wait for the eventual accepted request.
      await run.started;
      if (!run.messageId) return;
      const result = await api(`/generations/${run.requestId}/cancel`, { method: "POST" });
      if (result.message) upsertMessage(result.message);
      else upsertMessage(await api(`/messages/${run.messageId}`));
      run.terminal = true;
      run.controller.abort();
    })();
    try { await run.cancellation; }
    catch (cause) {
      run.cancelRequested = false; run.cancellation = null;
      if (generation === run) activeGeneration.value.cancelling = false;
      reportError(cause); throw cause;
    }
  };

  const generate = async ({ target, draft }) => {
    if (generation) throw new Error("请等待当前回复完成或先停止生成");
    if (!configured.value) throw new Error("请先在 API Key 设置中配置密钥");
    const conversationId = target?.conversation_id || currentId.value;
    if (pages.value[conversationId]?.loading) throw new Error("请等待对话历史加载完成后再生成回复");
    const run = {
      conversationId, requestId: crypto.randomUUID(), messageId: null,
      controller: markRaw(new AbortController()), terminal: false, cancelRequested: false,
    };
    run.started = new Promise((resolve) => { run.resolveStarted = resolve; });
    generation = run;
    activeGeneration.value = { conversationId, requestId: run.requestId, messageId: null, cancelling: false };
    error.value = "";
    let body;
    if (target) body = { request_id: run.requestId, mode: model.value, agent_enabled: agentEnabled.value };
    else {
      body = new FormData();
      body.set("text", draft.text.trim()); body.set("mode", model.value); body.set("request_id", run.requestId);
      body.set("agent_enabled", String(agentEnabled.value));
      draft.files.forEach((file) => body.append("files", file));
    }
    try {
      await stream(target ? `/messages/${target.id}/regenerate` : `/conversations/${conversationId}/messages`, body, run.controller.signal, (kind, event) => {
        if (generation !== run || run.terminal || event.request_id !== run.requestId || event.conversation_id !== conversationId) return;
        if (kind === "started") {
          run.messageId = event.assistant_message.id;
          activeGeneration.value.messageId = run.messageId;
          run.resolveStarted();
          if (target) messagesByConversation.value[conversationId] = (messagesByConversation.value[conversationId] || []).filter((item) => item.seq < target.seq);
          upsertConversation(event.conversation); upsertMessage(event.user_message); upsertMessage(event.assistant_message);
          const current = drafts.value[conversationId];
          if (draft && current) {
            if (current.text === draft.text) current.text = "";
            current.files = current.files.filter((file) => !draft.files.includes(file));
          }
          if (run.cancelRequested) void cancelGeneration().catch(reportError);
        } else if (kind === "delta" && !run.cancelRequested && !run.terminal) {
          const item = messagesByConversation.value[conversationId]?.find((message) => message.id === event.message_id && message.id === run.messageId);
          if (item) {
            item.content += event.content || "";
            item.reasoning_content = (item.reasoning_content || "") + (event.reasoning_content || "");
          }
        } else if (kind === "tools" && !run.cancelRequested) {
          const item = messagesByConversation.value[conversationId]?.find((message) => message.id === event.message_id && message.id === run.messageId);
          if (item) item.tool_calls = event.tool_calls;
        } else if (kind === "done" || kind === "error") {
          run.terminal = true; upsertConversation(event.conversation); upsertMessage(event.message);
          if (kind === "error") reportError(event.message_text || event.message?.error_message || "回复生成失败");
        }
      });
      if (!run.terminal) throw new Error("响应连接中断，请检查保存的回复状态后再操作");
    } catch (cause) {
      if (!(cause.name === "AbortError" && run.terminal)) {
        // Never replay an uncertain request: its user message may already be committed.
        try {
          if (run.messageId) {
            const saved = await api(`/messages/${run.messageId}`);
            upsertMessage(saved);
            if (saved.status === "generating") await cancelGeneration();
          }
          else {
            await refreshConversations(); await loadMessages(conversationId);
            const saved = messagesByConversation.value[conversationId]?.find((item) => item.request_id === run.requestId && item.role === "assistant");
            if (saved) {
              run.messageId = saved.id;
              run.resolveStarted();
              if (draft && drafts.value[conversationId]?.text === draft.text) drafts.value[conversationId].text = "";
              if (draft && drafts.value[conversationId]) drafts.value[conversationId].files = drafts.value[conversationId].files.filter((file) => !draft.files.includes(file));
              if (saved.status === "generating") await cancelGeneration();
            }
          }
        } catch (reconcileError) {
          reportError(`${cause.message}；状态同步失败：${reconcileError.message}`); throw cause;
        }
        reportError(cause); throw cause;
      }
    } finally {
      run.resolveStarted();
      if (run.cancellation) await run.cancellation.catch(() => {});
      if (generation === run) { generation = null; activeGeneration.value = null; }
    }
  };
  const send = async () => {
    const draft = { text: currentDraft.value.text, files: [...currentDraft.value.files] };
    if (!draft.text.trim() && !draft.files.length) return;
    await generate({ draft });
  };
  const regenerate = (target) => generate({ target });
  const deleteMessage = async (item) => {
    if (activeGeneration.value?.conversationId === item.conversation_id) await cancelGeneration();
    await api(`/messages/${item.id}`, { method: "DELETE" });
    messagesByConversation.value[item.conversation_id] = (messagesByConversation.value[item.conversation_id] || []).filter((message) => message.id !== item.id);
    await loadMessages(item.conversation_id); await refreshConversations();
  };
  const deleteConversation = async (id) => {
    if (activeGeneration.value?.conversationId === id) await cancelGeneration();
    await api(`/conversations/${id}`, { method: "DELETE" });
    delete conversations.value[id]; delete messagesByConversation.value[id]; delete drafts.value[id]; delete pages.value[id];
    if (currentId.value === id) {
      const next = visibleConversations.value[0]?.id;
      if (next) await selectConversation(next);
      else await newConversation();
    }
  };
  const clear = async () => {
    await cancelGeneration(); await api("/conversations", { method: "DELETE" });
    conversations.value = {}; messagesByConversation.value = {}; pages.value = {}; drafts.value = {};
    await newConversation();
  };
  const importHistory = async (snapshot) => {
    const result = await api("/import/local-history", { method: "POST", body: { snapshot } });
    await refreshConversations(); return result;
  };
  const disconnect = () => generation?.controller.abort();
  return {
    conversations, currentId, currentConversation, currentRole, currentRoleMeta, messages, visibleConversations,
    options, configured, keySettingsOpen, ready, loading, error, model, pages, currentDraft, isGenerating, activeGeneration,
    initialize, reportError, setModel, agentEnabled, toggleAgent, selectConversation, newConversation, renameConversation, setRole,
    configureKey, clearKey, setDraftText, addFiles, removeFile, send, regenerate, cancelGeneration,
    deleteMessage, deleteConversation, clear, importHistory, loadMessages, disconnect,
  };
});
