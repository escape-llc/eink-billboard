import { createRouter, createWebHashHistory } from 'vue-router'
import WelcomeView from '../views/WelcomeView.vue'
import { apiJson } from '../components/ApiClient'

const router = createRouter({
	history: createWebHashHistory(),
	routes: [
		{
			path: '/',
			name: 'home',
			component: WelcomeView,
			// a device with no playlist has nothing on its panel: the first thing to do is make one, so the landing page goes there (only the landing page: any other address is the user's choice)
			beforeEnter: async () => {
				try {
					const found = await apiJson<{ playlists?: unknown[] }>('/api/schedule/playlist/list')
					if (Array.isArray(found.playlists) && found.playlists.length === 0) return { name: 'playlist' }
				} catch {
					// not signed in, or the server did not answer: stay on the welcome page, which does not need it
				}
				return true
			}
		},
		{
			path: '/settings',
			name: 'settings',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/Settings.vue')
		},
		{
			path: '/schedule',
			name: 'schedule',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/Scheduler.vue')
		},
		{
			path: '/system',
			name: 'system',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/System.vue')
		},
		{
			path: '/playlist',
			name: 'playlist',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/PlaylistEditor.vue')
		},
	]
})
export default router