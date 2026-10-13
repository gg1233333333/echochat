// Token 渲染队列
// 使用 requestAnimationFrame 实现批量更新，减少 DOM 操作次数

class StreamQueue {
  constructor() {
    this.contentQueue = [];
    this.isFlushing = false;
    this.onChunkCallback = null;
  }

  // 设置回调函数
  setCallbacks(onChunk) {
    this.onChunkCallback = onChunk;
  }

  // 将内容 token 加入队列
  enqueueContent(delta) {
    if (delta) {
      this.contentQueue.push(delta);
      this.flush();
    }
  }

  // 批量刷新队列到回调
  flush() {
    // 如果正在刷新或队列为空，直接返回
    if (this.isFlushing || this.contentQueue.length === 0) {
      return;
    }

    this.isFlushing = true;

    // 使用 requestAnimationFrame 在下一帧执行批量更新
    requestAnimationFrame(() => {
      // 批量合并内容 token
      if (this.contentQueue.length > 0 && this.onChunkCallback) {
        const mergedContent = this.contentQueue.join('');
        this.contentQueue = [];
        this.onChunkCallback(mergedContent);
      }

      this.isFlushing = false;

      // 检查是否有新的 token 在刷新期间加入
      if (this.contentQueue.length > 0) {
        this.flush();
      }
    });
  }

  // 清空队列
  clear() {
    this.contentQueue = [];
    this.isFlushing = false;
  }

  // 销毁队列，避免内存泄漏
  destroy() {
    this.clear();
    this.onChunkCallback = null;
  }
}

// 单例模式导出
export const streamQueue = new StreamQueue();

// 工厂函数，用于创建新的队列实例（如果需要多个独立队列）
export function createStreamQueue() {
  return new StreamQueue();
}
