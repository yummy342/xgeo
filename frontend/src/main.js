import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'
import { installBridge } from './lib/legacy.js'

// 必须在 mount 之前装桥：LegacyView 的 $effect 在组件挂载时就执行，
// 那一刻会调用旧视图函数、读到全局 D/SLUG/ST。放到 onMount 里就晚了
// ——「D is not defined」。
installBridge()

export default mount(App, { target: document.getElementById('app') })
