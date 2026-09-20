// 旧实现是往 #modal 注入 HTML 字符串（ui.html:182），对话框内容里带
// onclick="xxx()" 内联处理器。桥接期必须保留这个形态——那些处理器指向的
// 全局函数还在 legacy-views.js 里。等视图逐个迁完，再换成 Svelte 组件式弹窗。
export const modalState = $state({ html: '' })

export function openModal(html) {
  modalState.html = html
}

export function closeModal() {
  modalState.html = ''
}
