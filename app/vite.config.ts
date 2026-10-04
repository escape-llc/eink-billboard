import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

import pkg from "./package.json"
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
	}
})
