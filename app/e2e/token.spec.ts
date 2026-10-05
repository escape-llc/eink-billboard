import { expect, test } from "@playwright/test"
import { PROTECTED, TOKEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// The second server requires `Authorization: Bearer e2e-token` on /api.
test.use({ baseURL: PROTECTED.url })
const STORAGE_KEY = "eink-billboard.api-token"

test("the API refuses requests without the token", async ({ request }) => {
	expect((await request.get("/api/settings/system")).status()).toBe(401)
	expect((await request.get("/api/settings/system", { headers: { Authorization: "Bearer nope" } })).status()).toBe(401)
	expect((await request.get("/api/settings/system", { headers: { Authorization: `Bearer ${TOKEN}` } })).status()).toBe(200)
})

test("the app asks for the token once, and remembers it", async ({ page }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page, [401])
	let prompts = 0
	page.on("dialog", d => { prompts++; void d.accept(TOKEN) })

	await page.goto("/#/settings")
	await expect(page.locator(".p-select").filter({ hasText: "English" }).first()).toBeVisible()
	expect(prompts, "prompts on the first load").toBe(1)
	expect(await page.evaluate(k => localStorage.getItem(k), STORAGE_KEY)).toBe(TOKEN)

	await page.reload()
	await expect(page.locator(".p-select").filter({ hasText: "English" }).first()).toBeVisible()
	expect(prompts, "prompts after a reload").toBe(1)
	watch.expectNone()
})

test("cancelling the prompt leaves the page without data and shows the server's message", async ({ page }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page, [401], [/Missing or invalid API token/])
	page.on("dialog", d => void d.dismiss())
	await page.goto("/#/settings")
	await expect(page.getByText(/Missing or invalid API token/).first()).toBeVisible()
	await expect(page.locator(".p-select").filter({ hasText: "English" })).toHaveCount(0)
	expect(await page.evaluate(k => localStorage.getItem(k), STORAGE_KEY)).toBeNull()
	watch.expectNone()
})
