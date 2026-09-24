import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import router from './router'
import { restaurerSessionKiosque } from './api/session'

// Écran Andon (TV d'atelier) : reprend la session après un redémarrage du navigateur.
restaurerSessionKiosque()

createApp(App).use(router).mount('#app')
