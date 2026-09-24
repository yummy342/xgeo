import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'

// 迁移收尾后这里已经没有桥了：19 个视图 + 全部弹窗都是组件，
// 领域函数在 lib/domain.js，任务动作在 lib/jobs.svelte.js，
// 导航在 lib/nav.js。legacy-views.js 已删除。
export default mount(App, { target: document.getElementById('app') })
