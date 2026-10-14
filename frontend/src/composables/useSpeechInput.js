import { onBeforeUnmount, ref } from "vue";

export function useSpeechInput(append, onError) {
  const supported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  const starting = ref(false);
  const recording = ref(false);
  const preview = ref("");
  let recognition;
  let requested = false;
  const reset = () => {
    requested = false;
    starting.value = false;
    recording.value = false;
    preview.value = "";
  };
  const stop = () => {
    const active = requested;
    const pending = starting.value;
    reset();
    if (!active) return;
    try {
      if (pending) recognition.abort();
      else recognition.stop();
    } catch {
      onError("无法停止语音识别，请关闭麦克风权限后重试");
    }
  };
  const start = () => {
    if (!supported || requested) return;
    if (!recognition) {
      const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      recognition = new Recognition();
      recognition.lang = "zh-CN";
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.onstart = () => {
        if (!requested) {
          recognition.abort();
          return;
        }
        starting.value = false;
        recording.value = true;
        preview.value = "正在听…";
      };
      recognition.onresult = (event) => {
        if (!recording.value) return;
        let final = "",
          interim = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          if (result.isFinal) final += result[0].transcript;
          else interim += result[0].transcript;
        }
        if (final) append(final);
        preview.value = interim;
      };
      recognition.onend = reset;
      recognition.onerror = (event) => {
        reset();
        if (event.error === "aborted") return;
        if (["not-allowed", "service-not-allowed"].includes(event.error))
          onError("麦克风或语音识别权限未获允许，请检查浏览器权限后重试");
        else if (event.error === "no-speech") onError("没有识别到语音，请重试");
        else onError("语音识别失败，请检查麦克风与网络连接");
      };
    }
    requested = true;
    starting.value = true;
    preview.value = "正在启动语音，请允许麦克风访问…";
    try {
      recognition.start();
    } catch {
      reset();
      onError("无法启动语音识别");
    }
  };
  onBeforeUnmount(() => {
    stop();
    if (recognition)
      recognition.onstart = recognition.onresult = recognition.onend = recognition.onerror = null;
  });
  return {
    supported,
    starting,
    recording,
    preview,
    stop,
    toggle: () => (requested ? stop() : start()),
  };
}
