import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import i18n from './locales'
import { pinia } from './stores/pinia'
import './styles/main.css'
import './styles/cards.css'

const app = createApp(App)

app.use(pinia)
app.use(router)
app.use(i18n)

app.mount('#app')
