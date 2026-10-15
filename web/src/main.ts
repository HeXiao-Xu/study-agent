/**
 * 前端入口：装配顺序固定 —— Pinia → Router → Element Plus（全局注册）。
 * Element Plus 按任务卡 S0-6 全局注册（体积换简单，需要时再改按需引入）。
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
