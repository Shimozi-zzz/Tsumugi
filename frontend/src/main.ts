import { createApp, type Directive } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './assets/main.css'

const imgFadeDirective: Directive<HTMLImageElement> = {
  mounted(el) {
    el.classList.add('img-fade')
    const reveal = () => {
      el.classList.add('img-loaded')
    }
    el.addEventListener('load', reveal)
    el.addEventListener('error', reveal)
    if (el.complete && el.naturalWidth > 0) {
      el.classList.add('img-loaded')
    }
  },
  updated(el) {
    if (!el.complete) {
      el.classList.remove('img-loaded')
    } else if (el.naturalWidth > 0) {
      el.classList.add('img-loaded')
    }
  },
}

const app = createApp(App)
app.directive('img-fade', imgFadeDirective)
app.use(createPinia())
app.mount('#app')
