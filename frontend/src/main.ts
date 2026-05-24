import { createApp } from 'vue'
import { createPinia } from 'pinia'
// Element Plus CSS (components auto-imported via unplugin)
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import './styles/main.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')