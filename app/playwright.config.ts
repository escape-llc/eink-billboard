import { defineConfig, devices } from "@playwright/test"
import { OPEN, PROTECTED, ROOT, TOKEN } from "./e2e/servers"

// Browser tests against the real server and the built web app (npm run e2e builds it first).
// Needs `uv sync` to have been run in the repository root, and the Playwright browser (`npx playwright install chromium`).
const server = (s: { port: number, storage: string }, extra = "") =>
	`uv run python -m scripts.e2e_storage "${s.storage}" && ` +
	`uv run python -m python.eink-billboard --host 127.0.0.1 --port ${s.port} --storage "${s.storage}" --app app/dist ${extra}`

export default defineConfig({
	testDir: "./e2e",
	// the tests change settings on a shared server, so they run one at a time
	workers: 1,
	fullyParallel: false,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
	use: {
		baseURL: OPEN.url,
		trace: "retain-on-failure",
		screenshot: "only-on-failure",
	},
	projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
	webServer: [
		{
			command: server(OPEN),
			cwd: ROOT,
			url: `${OPEN.url}/api/settings/system`,
			reuseExistingServer: false,
			timeout: 120_000,
		},
		{
			command: server(PROTECTED, `--token ${TOKEN}`),
			cwd: ROOT,
			// a 401 means the server is up
			url: `${PROTECTED.url}/api/settings/system`,
			reuseExistingServer: false,
			timeout: 120_000,
		},
	],
})
