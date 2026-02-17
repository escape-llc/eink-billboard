import 'primeflex/primeflex.css'
import 'primeicons/primeicons.css'
import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia';
import App from './App.vue'
import PrimeVue from 'primevue/config'
import DialogService from 'primevue/dialogservice'
import ToastService from 'primevue/toastservice'
import ConfirmationService from 'primevue/confirmationservice'
import router from './router'
import { useThemes } from './components/ThemeTools'

const { DARK_MODE_SELECTOR, DefaultPreset } = useThemes(undefined);

const pinia = createPinia();
const app = createApp(App)

app.use(PrimeVue, {
	theme: {
		preset: DefaultPreset,
		options: {
			darkModeSelector: DARK_MODE_SELECTOR,
		}
	}
})
app.use(DialogService)
app.use(ToastService)
app.use(ConfirmationService)
app.use(pinia)
app.use(router)

app.mount('#app')