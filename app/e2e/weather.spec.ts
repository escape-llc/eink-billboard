import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// The OpenWeatherMap API data source (the Weather pages and overlay use its settings) takes a key from a page of OpenWeatherMap's: its settings carry a link to it (a descriptor's `link`).
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the OpenWeatherMap settings link to where an API key is got, and the key is a password", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Providers" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: "openweathermap-api", exact: true }).click()
	const link = page.getByRole("link", { name: "Get a free API key" })
	await expect(link).toBeVisible()
	await expect(link).toHaveAttribute("href", "https://home.openweathermap.org/users/sign_up")
	await expect(link).toHaveAttribute("target", "_blank")
	await expect(link).toHaveAttribute("rel", /noopener/)
	await expect(page.getByRole("textbox", { name: "API Key", exact: true })).toHaveAttribute("type", "password")
	watch.expectNone()
})

test("an API key is one frame: the Test joined to the input, the link beside them, then the answer under the row", async ({ page }) => {
	const watch = watchProblems(page)
	await page.route("**/api/datasource/openweathermap-api/test", route => route.fulfill({ json: { ok: false, message: "OpenWeatherMap refused this key. A new key can take a couple of hours to start working." } }))
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Providers" }).click()
	await page.getByRole("tabpanel").locator(".p-select").first().click()
	await page.getByRole("option", { name: "openweathermap-api", exact: true }).click()
	const key = page.getByRole("textbox", { name: "API Key", exact: true })
	const test = page.getByRole("button", { name: "Test API Key" })
	const link = page.getByRole("link", { name: "Get a free API key" })
	// nothing to test until a key is typed
	await expect(test).toBeDisabled()
	await key.fill("any-key")
	await expect(test).toBeEnabled()
	await test.click()
	const answer = page.getByTestId("test-result")
	await expect(answer).toContainText("refused this key")
	const [k, t, l, a] = await Promise.all([key.boundingBox(), test.boundingBox(), link.boundingBox(), answer.boundingBox()])
	// joined: the button is on the input's row, touching its right edge
	expect(Math.abs((t!.y + t!.height / 2) - (k!.y + k!.height / 2))).toBeLessThan(4)
	expect(t!.x - (k!.x + k!.width)).toBeLessThan(2)
	// the link is in the same group, on the input's row, after the Test
	expect(l!.y).toBeLessThan(k!.y + k!.height)
	expect(l!.y + l!.height).toBeGreaterThan(k!.y)
	expect(l!.x).toBeGreaterThan(t!.x + t!.width - 2)
	// the answer is under the row
	expect(a!.y).toBeGreaterThan(k!.y + k!.height - 2)
	expect(a!.y).toBeGreaterThan(l!.y + l!.height - 2)
	// the key is required, as the others are
	await key.fill("")
	await key.press("Tab")
	await expect(page.getByText("Required", { exact: true }).first()).toBeVisible()
	watch.expectNone()
})
