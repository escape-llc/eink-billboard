import 'primeflex/primeflex.css'
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
import { installMaterialIcons } from './components/MaterialIcons'
import { installStaleBuildReload } from './components/StaleBuild'
import { installResources } from './api/resources'

installMaterialIcons()
// a tab opened before an update reloads itself when a page of its old build is gone
installStaleBuildReload(router)

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
installResources(app)
app.use(router)

app.mount('#app')