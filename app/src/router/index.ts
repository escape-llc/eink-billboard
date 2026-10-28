import { createRouter, createWebHashHistory } from 'vue-router'
import WelcomeView from '../views/WelcomeView.vue'
import { api } from '../api/client'
import { authPrompt, claimCodeOf } from '../components/AuthPrompt'

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
					const found = await api.get('/api/schedule/playlist/list')
					if (found.playlists.length === 0) return { name: 'playlist' }
				} catch {
					// not signed in, or the server did not answer: stay on the welcome page, which does not need it
				}
				return true
			}
		},
		{
			// the QR code on a new device's panel (#491): `#/claim/12345678`. The code goes to the setup dialog, which the home page opens when the device asks for it
			// (it needs the password the person chooses, so nothing is claimed here), and the address is the home page's, so the code is not left in the history.
			// A device that is claimed already, or a code that is not eight digits, just lands on home.
			path: '/claim/:code?',
			name: 'claim',
			redirect: to => {
				authPrompt.claim = claimCodeOf(to.params.code)
				// the home page waits for the sign-in this opens, and the address would show the code until then: it is taken out of the address bar now
				window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}#/`)
				return { name: 'home' }
			}
		},
		{
			path: '/settings',
			name: 'settings',
			component: () => import('../views/Settings.vue')
		},
		{
			path: '/schedule',
			name: 'schedule',
			component: () => import('../views/Scheduler.vue')
		},
		{
			path: '/system',
			name: 'system',
			component: () => import('../views/System.vue')
		},
		{
			path: '/gallery',
			name: 'gallery',
			component: () => import('../views/Gallery.vue')
		},
		{
			path: '/playlist',
			name: 'playlist',
			component: () => import('../views/PlaylistEditor.vue')
		},
		// no address is a dead end: anything else is the home page
		{
			path: '/:pathMatch(.*)*',
			name: 'not-found',
			redirect: { name: 'home' }
		},
	]
})
export default router