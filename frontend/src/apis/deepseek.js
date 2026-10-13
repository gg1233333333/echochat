// src/apis/deepseek.js
import { ElMessage } from "element-plus";
import { DEEPSEEK_API_KEY } from "@/config/deepseekKey";
import { getDeepSeekMode } from "@/config/deepseekModes";

let currentAbortController = null;

class SSEParser {
  constructor() {
    this.buffer = '';
  }

  parse(chunk) {
    const lines = [];
    this.buffer += chunk;

    // 按行分割 buffer
    const parts = this.buffer.split('\n');
    
    // 保留最后一行（可能不完整）
    this.buffer = parts.pop() || '';

    // 处理完整的行
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith('data: ')) {
        lines.push(line);
      }
    }

    return lines;
  }

  getRemainingBuffer() {
    return this.buffer;
  }

  clear() {
    this.buffer = '';
  }
}

export async function chatStream(
  messages,
  onChunk,
  onDone,
  mode = "thinking",
) {
  try {
    const apiKey = (DEEPSEEK_API_KEY ?? "").trim();
    if (!apiKey) {
      const errorMsg =
        "未配置 DeepSeek API Key，请在 .env 中设置 VITE_DEEPSEEK_API_KEY。";
      ElMessage.error(errorMsg);
      throw new Error(errorMsg);
    }
    
    currentAbortController = new AbortController();

    const response = await fetch("https://api.deepseek.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
      },
      body: JSON.stringify({
        ...getDeepSeekMode(mode).request,
        messages,
        stream: true,
      }),
      signal: currentAbortController.signal,
    });

    if (!response.ok) {
      const errorText = await response.text();
      let errorMsg = "网络请求失败";
      try {
        const errorData = JSON.parse(errorText);
        errorMsg = errorData.error?.message || errorMsg;
      } catch {
        // 如果解析失败，使用原始错误文本
      }
      ElMessage.error(errorMsg);
      throw new Error(errorMsg);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const sseParser = new SSEParser();

    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        // 检查剩余 buffer 中是否有未处理的 data 行
        const remainingBuffer = sseParser.getRemainingBuffer();
        if (remainingBuffer.trim().startsWith('data: ')) {
          const lines = sseParser.parse('\n');
          processLines(lines, onChunk, onDone);
        }
        onDone?.();
        break;
      }

      const chunk = decoder.decode(value, { stream: true });
      const lines = sseParser.parse(chunk);
      
      const shouldContinue = processLines(lines, onChunk, onDone);
      if (!shouldContinue) {
        break;
      }
    }

    reader.releaseLock();
  } catch (error) {
    if (error.name === 'AbortError') {
      onDone?.();
      return;
    }
    
    if (!error.message?.includes('网络请求失败')) {
      ElMessage.error(error.message || "流式响应处理异常");
    }
    
    throw error;
  } finally {
    currentAbortController = null;
  }
}

function processLines(lines, onChunk, onDone) {
  for (const line of lines) {
    if (line === "data: [DONE]") {
      onDone?.();
      return false;
    }

    try {
      const payload = JSON.parse(line.slice(6));

      const delta = payload.choices?.[0]?.delta?.content;
      if (delta) {
        onChunk?.(delta);
      }
    } catch (parseError) {
      // 跳过 JSON 解析错误，继续处理下一行
      console.warn('JSON parse error:', parseError, 'Line:', line);
    }
  }
  return true;
}

export function abortStream() {
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
  }
}
