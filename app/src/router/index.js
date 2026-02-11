import { createRouter, createWebHashHistory } from 'vue-router'
import WelcomeView from '../views/WelcomeView.vue'

const router = createRouter({
	history: createWebHashHistory(),
	routes: [
		{
			path: '/',
			name: 'home',
			component: WelcomeView
		},
		{
			path: '/settings',
			name: 'settings',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/Settings.vue')
		},
		{
			path: '/plugin',
			name: 'plugin',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/PluginSettings.vue')
		},
		{
			path: '/schedule',
			name: 'schedule',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/Scheduler.vue')
		},
		{
			path: '/playlist',
			name: 'playlist',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/PlaylistEditor.vue')
		},
		/*
		{
			path: '/setup',
			name: 'setup',
			// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
			component: () => import('../views/SetupView.vue')
		},
		*/
	]
})
export default router