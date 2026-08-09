import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import i18n from './locales'
import { pinia } from './stores/pinia'
import './styles/main.css'
import './styles/cards.css'
import './styles/public-pages.css'

const app = createApp(App)

app.use(pinia)
app.use(router)
app.use(i18n)

// Replay remains lazy because it is reached after the showcase. Start its
// chunk while the app mounts so a direct public replay link does not wait for
// RouterView to discover the dynamic import after boot.
const publicPath = window.location.pathname
if (publicPath.startsWith('/replay/')) {
  void import('./views/WorkflowReplay.vue')
}

app.mount('#app')
