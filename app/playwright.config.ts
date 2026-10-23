import { defineConfig, devices } from "@playwright/test"
import { CLAIM, CLAIM_PHONE, OPEN, PROTECTED, ROOT, TOKEN } from "./e2e/servers"

// the specs the phone project runs: the first steps (setup, settings, the playlist), the lookups, the location picker, and the page widths
const PHONE_SPECS = ["access", "settings", "playlist", "lookups", "address-search", "phone"].map(name => `**/${name}.spec.ts`)

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
	projects: [
		{ name: "chromium", use: { ...devices["Desktop Chrome"] } },
		// a phone (#510 A5): a new user's first contact is the setup dialog on a phone, so the views they see first run here too, not the whole suite
		{ name: "phone", use: { ...devices["Pixel 7"] }, testMatch: PHONE_SPECS },
	],
	webServer: [
		{
			command: server(OPEN),
			cwd: ROOT,
			url: `${OPEN.url}/api/settings/system`,
			reuseExistingServer: false,
			// the schemas are patched by scripts/e2e_storage.py, so the server must not bring them back to the shipped ones
			env: { EINK_KEEP_SCHEMAS: "1" },
			timeout: 120_000,
		},
		{
			command: server(PROTECTED, `--token ${TOKEN}`),
			cwd: ROOT,
			// a 401 means the server is up
			url: `${PROTECTED.url}/api/settings/system`,
			reuseExistingServer: false,
			// the schemas are patched by scripts/e2e_storage.py, so the server must not bring them back to the shipped ones
			env: { EINK_KEEP_SCHEMAS: "1" },
			timeout: 120_000,
		},
		{
			// a new device: every /api route answers 401 `setup` until the setup code is entered
			command: server(CLAIM, "--require-auth"),
			cwd: ROOT,
			url: `${CLAIM.url}/api/access`,
			reuseExistingServer: false,
			env: { EINK_KEEP_SCHEMAS: "1", EINK_SETUP_CODE: CLAIM.code },
			timeout: 120_000,
		},
		{
			// the phone project's own new device: claiming one is done once, so each project claims its own
			command: server(CLAIM_PHONE, "--require-auth"),
			cwd: ROOT,
			url: `${CLAIM_PHONE.url}/api/access`,
			reuseExistingServer: false,
			env: { EINK_KEEP_SCHEMAS: "1", EINK_SETUP_CODE: CLAIM.code },
			timeout: 120_000,
		},
	],
})
