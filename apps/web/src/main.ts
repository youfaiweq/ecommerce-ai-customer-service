import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { i18n } from '@/i18n'
import { useProductStore } from '@/stores/products'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(i18n)
app.use(router)
app.mount('#app')

// 启动后异步拉后端商品（失败降级到 mock，不阻塞首屏）
const products = useProductStore()
void products.load()
