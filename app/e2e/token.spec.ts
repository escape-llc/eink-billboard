import { expect, test, type Page } from "@playwright/test"
import { PROTECTED, TOKEN } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// The second server requires `Authorization: Bearer e2e-token` on /api. The web app signs in once with the token;
// the server remembers it and the browser holds only an HttpOnly cookie.
test.use({ baseURL: PROTECTED.url })
const BEARER = { Authorization: `Bearer ${TOKEN}` }
const showingSettings = (page: Page) => page.locator(".p-select").filter({ hasText: "English" }).first()

/** Nothing but the theme may be kept in the browser: no token, no session, nothing else. */
async function expectOnlyTheThemeStored(page: Page) {
	const stored = await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage), cookie: document.cookie }))
	expect(stored.local.filter(k => !k.startsWith("theme-")), "localStorage keys besides the theme").toEqual([])
	expect(stored.session, "sessionStorage keys").toEqual([])
	// the session cookie is HttpOnly: a script cannot see it
	expect(stored.cookie).not.toContain("eink_session")
}

test("the API refuses requests without the token", async ({ request }) => {
	expect((await request.get("/api/settings/system")).status()).toBe(401)
	expect((await request.get("/api/settings/system", { headers: { Authorization: "Bearer nope" } })).status()).toBe(401)
	expect((await request.get("/api/settings/system", { headers: BEARER })).status()).toBe(200)
})

test("signing in starts a server session that works without the token", async ({ request }) => {
	const refused = await request.post("/api/session", { headers: { Authorization: "Bearer nope" } })
	expect(refused.status()).toBe(401)
	expect(refused.headers()["set-cookie"]).toBeUndefined()

	const signedIn = await request.post("/api/session", { headers: BEARER })
	expect(signedIn.status()).toBe(200)
	const cookie = signedIn.headers()["set-cookie"].toLowerCase()
	expect(cookie).toContain("httponly")
	expect(cookie).toContain("samesite=strict")
	// the cookie holds an unguessable ID, never the token
	expect(cookie).not.toContain(TOKEN)
	// the request context keeps the cookie, so no Bearer token is needed any more
	expect((await request.get("/api/settings/system")).status()).toBe(200)

	expect((await request.delete("/api/session")).status()).toBe(200)
	expect((await request.get("/api/settings/system")).status()).toBe(401)
})

test("the app asks for the token once, and the server remembers the sign-in", async ({ page, context }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page, [401])
	let prompts = 0
	page.on("dialog", d => { prompts++; void d.accept(TOKEN) })

	await page.goto("/#/settings")
	await expect(showingSettings(page)).toBeVisible()
	expect(prompts, "prompts on the first load, though several requests failed at once").toBe(1)
	await expectOnlyTheThemeStored(page)

	// the browser has the session cookie, flagged so scripts cannot read it
	const cookie = (await context.cookies()).find(c => c.name === "eink_session")
	expect(cookie?.httpOnly).toBe(true)
	expect(cookie?.sameSite).toBe("Strict")
	expect(cookie?.value).not.toContain(TOKEN)

	await page.reload()
	await expect(showingSettings(page)).toBeVisible()
	expect(prompts, "prompts after a reload").toBe(1)
	await expectOnlyTheThemeStored(page)
	watch.expectNone()
})

test("cancelling the prompt leaves the page without data and shows the server's message", async ({ page }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page, [401], [/Missing or invalid API token/])
	let prompts = 0
	page.on("dialog", d => { prompts++; void d.dismiss() })
	await page.goto("/#/settings")
	await expect(page.getByText(/Missing or invalid API token/).first()).toBeVisible()
	await expect(page.locator(".p-select").filter({ hasText: "English" })).toHaveCount(0)
	expect(prompts, "prompts, though several requests failed at once").toBe(1)
	await expectOnlyTheThemeStored(page)
	watch.expectNone()
})

test("a wrong token is refused and nothing is kept", async ({ page, context }) => {
	await stubMapTiles(page)
	const watch = watchProblems(page, [401], [/Missing or invalid API token/])
	let prompts = 0
	page.on("dialog", d => { prompts++; void d.accept("wrong-token") })
	await page.goto("/#/settings")
	await expect(page.getByText(/Missing or invalid API token/).first()).toBeVisible()
	expect((await context.cookies()).some(c => c.name === "eink_session")).toBe(false)
	expect(prompts, "prompts, though the page loads in several waves of requests").toBe(1)
	await expectOnlyTheThemeStored(page)
	watch.expectNone()
})
