<script setup>
import { ref } from "vue";
import { api } from "@/apis/backend";

const props = defineProps({ runId: { type: String, required: true } });
const open = ref(false);
const run = ref(null);
const events = ref([]);
const error = ref("");
const busy = ref(false);
let revision = 0;
const states = { queued: "已排队", running: "运行中", completed: "已完成", cancelled: "已取消", failed: "失败", interrupted: "已中断" };
const kinds = { run_queued: "任务已接受", run_running: "运行开始", model_started: "模型请求开始", model_finished: "模型请求结束", tool_started: "工具开始", tool_finished: "工具结束", run_completed: "运行完成", run_cancelled: "运行取消", run_failed: "运行失败", run_interrupted: "重启后标记中断", legacy_imported: "历史运行迁入" };
const load = async () => {
  const current = ++revision;
  const id = props.runId;
  busy.value = true; error.value = ""; run.value = null; events.value = [];
  try {
    const [detail, timeline] = await Promise.all([api(`/runs/${id}`), api(`/runs/${id}/events?limit=200`)]);
    if (current === revision && id === props.runId) { run.value = detail; events.value = timeline.items; }
  } catch (cause) { if (current === revision) error.value = cause.message; }
  finally { if (current === revision) busy.value = false; }
};
const cancel = async () => {
  busy.value = true; error.value = "";
  try { await api(`/runs/${props.runId}/cancel`, { method: "POST" }); await load(); }
  catch (cause) { error.value = cause.message; }
  finally { busy.value = false; }
};
</script>

<template>
  <button type="button" class="run-link" @click="open = true">运行记录</button>
  <el-dialog v-model="open" title="运行记录" width="min(540px, 92vw)" class="echo-settings-dialog" append-to-body @open="load">
    <p class="run-id">{{ runId }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="run">
      <p role="status">{{ states[run.state] || run.state }}</p>
      <p v-if="run.error_message" class="run-error">{{ run.error_message }}</p>
      <p class="run-note">已保存 {{ run.checkpoint.model_calls ?? "未知" }} 次模型请求、{{ run.checkpoint.tool_calls ?? "未知" }} 次工具尝试。记录不会自动续跑。</p>
      <ol class="run-events">
        <li v-for="event in events" :key="event.seq">
          <span>{{ event.seq }} · {{ kinds[event.kind] || event.kind }}</span>
          <small v-if="event.payload.name">{{ event.payload.name }} · {{ event.payload.status || "" }}</small>
        </li>
      </ol>
    </template>
    <template #footer><el-button v-if="run && ['queued', 'running'].includes(run.state)" :disabled="busy" @click="cancel">停止运行</el-button><el-button :loading="busy" @click="load">刷新运行记录</el-button></template>
  </el-dialog>
</template>

<style scoped>
.run-link { border: 0; background: transparent; color: var(--color-text-secondary); font: inherit; font-size: 12px; padding: 4px 0; cursor: pointer; }
.run-link:hover { color: var(--color-accent); }
.run-id { overflow-wrap: anywhere; font-family: monospace; font-size: 12px; }
.run-note, .run-events small { color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.run-error { color: var(--color-danger, #c2414b); }
.run-events { max-height: 40vh; overflow: auto; padding-left: 24px; }
.run-events li { padding: 5px 0; }
.run-events small { display: block; overflow-wrap: anywhere; }
</style>
