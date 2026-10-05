/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

import pkg from "./package.json" with { type: "json" }
const version = pkg.version || 0
const packageName = pkg.name || "medialab-wasm"

// https://vite.dev/config/
export default defineConfig({
  plugins: [
		vue()
	],
	define: {
		__APP_VERSION__: JSON.stringify(version),
		__APP_PACKAGE__: JSON.stringify(packageName)
	},
	test: {
		// the code under test uses window, localStorage, and fetch
		environment: "jsdom",
		include: ["src/**/*.test.ts"],
		// the Playwright tests in e2e/ run with `npm run e2e`
		exclude: ["e2e/**", "node_modules/**"]
	}
})
