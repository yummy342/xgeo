// 提示条。旧实现是往 #toast 里 append 一个 div 再 setTimeout 移除；
// 换成响应式数组，渲染交给 <Toast/>。
let seq = 0

export const toasts = $state([])

export function toast(message, kind = '') {
  const id = ++seq
  toasts.push({ id, message, kind })
  setTimeout(() => remove(id), 3800)
  return id
}

toast.error = (m) => toast(m, 'err')

export function remove(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}
