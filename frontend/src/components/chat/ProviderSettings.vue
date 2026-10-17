<script setup>
import { ref } from "vue";
import { api } from "@/apis/backend";
import { useSessionStore } from "@/stores/session";

const open = defineModel({ type: Boolean, default: false });
const store = useSessionStore();
const settings = ref({ base_url: "", model: "", protocol: "deepseek" });
const busy = ref(false);
const message = ref("");
const error = ref("");
const load = async () => {
  busy.value = true; error.value = ""; message.value = "";
  try { settings.value = await api("/provider"); }
  catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
};
const save = async () => {
  busy.value = true; error.value = ""; message.value = "";
  try {
    const result = await api("/provider", { method: "PUT", body: settings.value });
    store.configured = result.configured;
    message.value = result.configured ? "配置已保存。连接测试仅检查已保存的地址。" : "配置已保存，请重新配置此服务的 API Key。";
  } catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
};
const test = async () => {
  busy.value = true; error.value = ""; message.value = "";
  try { message.value = (await api("/provider/test", { method: "POST" })).message; }
  catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
};
</script>

<template>
  <el-dialog v-model="open" title="模型接口" width="min(500px, 92vw)" class="echo-settings-dialog" append-to-body :close-on-click-modal="!busy" :show-close="!busy" @open="load">
    <p class="provider-note">支持 OpenAI Chat Completions 流式协议。DeepSeek 模式额外发送其思考参数。配置保存在本机；更换服务地址会清除内存密钥。</p>
    <el-form label-position="top" :disabled="busy || store.isGenerating">
      <el-form-item label="兼容模式"><el-select v-model="settings.protocol" aria-label="兼容模式"><el-option label="DeepSeek" value="deepseek" /><el-option label="OpenAI Chat Completions" value="openai" /></el-select></el-form-item>
      <el-form-item label="服务地址"><el-input v-model="settings.base_url" aria-label="模型服务地址" placeholder="https://api.example.com/v1" autocomplete="off" /></el-form-item>
      <el-form-item label="模型名称"><el-input v-model="settings.model" aria-label="模型名称" autocomplete="off" /></el-form-item>
    </el-form>
    <p class="provider-note">密钥仅发往已保存地址。公网需 HTTPS，允许明确的本机 HTTP 服务；禁止内网地址和重定向。连接测试只 GET /models，不生成回复，不证明该模型或工具已兼容。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" role="status" />
    <template #footer>
      <el-button :disabled="busy || !store.configured" @click="test">测试已保存连接</el-button>
      <el-button type="primary" :disabled="busy || store.isGenerating" @click="save">保存接口</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.provider-note { color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.el-select { width: 100%; }
</style>
