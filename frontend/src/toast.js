// 轻量 Toast：模块级命令式 API，ToastHost 订阅渲染。
// 视觉复用主题 token（--panel/--panel-border/--shadow-md/--radius-md，见 ADR 0021）。
// 克制：简短、自动消失、不过度堆叠。

const listeners = new Set();
let idSeq = 0;
let current = [];

function emit(next) {
  current = next;
  listeners.forEach((fn) => fn(next));
}

export function toast(message, type = "info", duration) {
  const id = ++idSeq;
  const item = { id, message, type };
  const ttl = duration ?? (type === "error" ? 4200 : 2600);
  emit([...current, item]);
  setTimeout(() => {
    emit(current.filter((t) => t.id !== id));
  }, ttl);
  return id;
}

toast.success = (message, duration) => toast(message, "success", duration);
toast.error = (message, duration) => toast(message, "error", duration);
toast.info = (message, duration) => toast(message, "info", duration);

/** 清空当前 toast（测试隔离用）。 */
export function clearToasts() {
  emit([]);
}

/** 当前 toast 列表（测试用快照）。 */
export function getToasts() {
  return [...current];
}

export function subscribeToast(fn) {
  listeners.add(fn);
  fn(current);
  return () => listeners.delete(fn);
}
