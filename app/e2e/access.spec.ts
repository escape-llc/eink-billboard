import { expect, test, type Page } from "@playwright/test"
import { CLAIM } from "./servers"
import { stubMapTiles, watchProblems } from "./support"

// A new device nobody has claimed (the third server, `--require-auth`): it asks for the setup code once, the person chooses the password,
// and from then on it asks for that password. The tests run in order on one server.
test.describe.configure({ mode: "serial" })
test.use({ baseURL: CLAIM.url })
test.beforeEach(async ({ page }) => stubMapTiles(page))

const PASSWORD = "first password 1"
const CHANGED = "second password 2"
const dialog = (page: Page) => page.getByTestId("auth-dialog")
const showingSettings = (page: Page) => page.locator(".p-select").filter({ hasText: "English" }).first()

test("a new device answers 401 with setup, and says nothing else", async ({ request }) => {
	const refused = await request.get("/api/settings/system")
	expect(refused.status()).toBe(401)
	expect(await refused.json()).toMatchObject({ success: false, setup: true, message: "This device is not set up yet." })
	expect(await (await request.get("/api/access")).json()).toEqual({ required: true, setupRequired: true, passwordSet: false, localOnly: true })
	// the code is not in any answer
	expect(JSON.stringify(await (await request.get("/api/access")).json())).not.toContain(CLAIM.code.replace(" ", ""))
})

test("the setup dialog needs the code and two equal passwords, then signs in", async ({ page, context }) => {
	const watch = watchProblems(page, [401, 403], [/Failed|403|401/])
	await page.goto("/#/settings")
	await expect(dialog(page)).toBeVisible()
	await expect(page.getByRole("dialog", { name: "Set up this device" })).toBeVisible()

	// nothing is sent for an empty or mismatched form
	await dialog(page).getByRole("button", { name: "Set password" }).click()
	await expect(dialog(page).getByRole("alert")).toHaveText(/setup code/)
	await dialog(page).getByLabel("Setup code").fill(CLAIM.code)
	await dialog(page).getByLabel("New password", { exact: true }).fill(PASSWORD)
	await dialog(page).getByLabel("Repeat the password").fill("something else 3")
	await dialog(page).getByRole("button", { name: "Set password" }).click()
	await expect(dialog(page).getByRole("alert")).toHaveText(/not the same/)

	// a wrong code is refused by the server, in its words
	await dialog(page).getByLabel("Setup code").fill("0000 0000")
	await dialog(page).getByLabel("Repeat the password").fill(PASSWORD)
	await dialog(page).getByRole("button", { name: "Set password" }).click()
	await expect(dialog(page).getByRole("alert")).toHaveText(/not the setup code/)

	await dialog(page).getByLabel("Setup code").fill(CLAIM.code)
	await dialog(page).getByRole("button", { name: "Set password" }).click()
	await expect(showingSettings(page)).toBeVisible()
	await expect(dialog(page)).toBeHidden()
	expect((await context.cookies()).find(c => c.name === "eink_session")?.httpOnly).toBe(true)
	// nothing typed is kept in the browser
	const stored = await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage), html: document.body.innerHTML }))
	expect(stored.local.filter(k => !k.startsWith("theme-"))).toEqual([])
	expect(stored.session).toEqual([])
	expect(stored.html).not.toContain(PASSWORD)
	watch.expectNone()
})

test("a claimed device is claimed once, and asks for the password after that", async ({ page, request }) => {
	const watch = watchProblems(page, [401, 403], [/Failed|403|401/])
	expect((await request.post("/api/access/setup", { data: { code: CLAIM.code, password: "another password" } })).status()).toBe(409)
	expect(await (await request.get("/api/access")).json()).toMatchObject({ setupRequired: false, passwordSet: true })
	expect((await request.get("/api/settings/system")).status()).toBe(401)

	await page.goto("/#/settings")
	await expect(page.getByRole("dialog", { name: "Sign in" })).toBeVisible()
	await dialog(page).getByLabel("Password", { exact: true }).fill("not the password")
	await dialog(page).getByRole("button", { name: "Sign in" }).click()
	await expect(dialog(page).getByRole("alert")).toHaveText("Wrong password.")
	await dialog(page).getByLabel("Password", { exact: true }).fill(PASSWORD)
	await dialog(page).getByRole("button", { name: "Sign in" }).click()
	await expect(showingSettings(page)).toBeVisible()
	// a reload keeps the sign-in (the cookie), without asking
	await page.reload()
	await expect(showingSettings(page)).toBeVisible()
	await expect(dialog(page)).toBeHidden()
	watch.expectNone()
})

test("the password is changed from the System page, and the old one stops working", async ({ page, request }) => {
	const watch = watchProblems(page, [401, 403], [/Failed|403|401/])
	await page.goto("/#/system")
	await dialog(page).getByLabel("Password", { exact: true }).fill(PASSWORD)
	await dialog(page).getByRole("button", { name: "Sign in" }).click()
	// the whole page is loaded again once signed in: open the password dialog on that one
	await expect(page.locator(".p-toast-message-success")).toContainText("The page was reloaded")
	await page.getByTestId("open-password").click()
	const form = page.getByTestId("password-form")
	await expect(form).toBeVisible()
	await expect(form.getByRole("heading", { name: "Change the device password" })).toBeVisible()

	await form.getByLabel("Current password").fill("not the password")
	await form.getByLabel("New password", { exact: true }).fill(CHANGED)
	await form.getByLabel("Repeat the new password").fill(CHANGED)
	await form.getByRole("button", { name: "Change password" }).click()
	await expect(form.getByRole("alert")).toHaveText(/current password/)

	await form.getByLabel("Current password").fill(PASSWORD)
	await form.getByRole("button", { name: "Change password" }).click()
	await expect(form.getByRole("status")).toHaveText("The password was changed.")

	expect((await request.post("/api/session", { data: { password: PASSWORD } })).status()).toBe(401)
	expect((await request.post("/api/session", { data: { password: CHANGED } })).status()).toBe(200)
	watch.expectNone()
})
