import { expect, type APIRequestContext, type Page } from "@playwright/test"

// a 1x1 transparent PNG: the location picker's map tiles come from the internet, which the tests must not need
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64")

export async function stubMapTiles(page: Page) {
	await page.route("https://tile.openstreetmap.org/**", route => route.fulfill({ status: 200, contentType: "image/png", body: PIXEL }))
}

/** One place in Nominatim's answer, as its `/search?format=json` gives it. */
export const NOMINATIM_PLACE = { lat: "51.5007", lon: "-0.1246", display_name: "Big Ben, Westminster, London, United Kingdom", boundingbox: ["51.50", "51.51", "-0.13", "-0.12"] }

/** The location picker's address search answered from a fixture: returns the queries it was asked, in order. */
export async function stubAddressSearch(page: Page, answer: object[] = [NOMINATIM_PLACE]) {
	const queries: string[] = []
	await page.route("https://nominatim.openstreetmap.org/**", route => {
		queries.push(new URL(route.request().url()).searchParams.get("q") ?? "")
		return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(answer) })
	})
	return queries
}

/**
 * Collect everything that goes wrong while a page runs: uncaught errors, console errors,
 * failed requests, and HTTP error responses. Call `.expectNone()` at the end of the test.
 * `allowStatus` lists expected HTTP statuses (for example 401 when a token is being asked for), `allowConsole` console
 * errors a test expects (the app logs the errors it handles, such as a refused save).
 */
export function watchProblems(page: Page, allowStatus: number[] = [], allowConsole: RegExp[] = []) {
	const problems: string[] = []
	page.on("pageerror", e => problems.push(`pageerror: ${e.message}`))
	page.on("console", m => {
		// the browser logs a failed resource load as a console error as well; the response/requestfailed handlers report those
		if (m.type() === "error" && !/Failed to load resource/.test(m.text()) && !allowConsole.some(re => re.test(m.text()))) problems.push(`console.error: ${m.text().slice(0, 200)}`)
	})
	// a navigation or a lazy chunk cancelled by the next navigation is not a failure
	page.on("requestfailed", r => { if (r.failure()?.errorText !== "net::ERR_ABORTED") problems.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`) })
	page.on("response", r => { if (r.status() >= 400 && !allowStatus.includes(r.status())) problems.push(`HTTP ${r.status()}: ${r.url()}`) })
	return { problems, expectNone: () => expect(problems, "page problems").toEqual([]) }
}

/** The sign-in dialog (AuthDialog.vue): type `secret` into the field called `label` and press Sign in. */
export async function signInWith(page: Page, label: string, secret: string) {
	const dialog = page.getByTestId("auth-dialog")
	await dialog.getByLabel(label, { exact: true }).fill(secret)
	await dialog.getByRole("button", { name: "Sign in" }).click()
}

/** Open a PrimeVue Select that currently shows `current` and choose the option containing `option`. */
export async function choose(page: Page, current: string | RegExp, option: string | RegExp) {
	await page.locator(".p-select").filter({ hasText: current }).first().click()
	await page.getByRole("option").filter({ hasText: option }).first().click()
}

/** The save (check mark) button of the settings form in the tab that is showing. */
export const saveButton = (page: Page) => page.getByRole("tabpanel").locator("button:has(.mi-check)").first()

/**
 * Whether the server's answer is what a stored document holds: every key it answers (but its own, `_rev`, `_id`, ...) is the stored value, at any
 * depth, in any order; a key it does not answer (one it fills in, as a track's `type`) is not compared.
 */
export function servedAs(answer: unknown, stored: unknown): boolean {
	if (Array.isArray(answer)) return Array.isArray(stored) && answer.length === stored.length && answer.every((x, i) => servedAs(x, stored[i]))
	if (answer !== null && typeof answer === "object") {
		if (stored === null || typeof stored !== "object" || Array.isArray(stored)) return false
		return Object.entries(answer).every(([key, inner]) => key.startsWith("_") || servedAs(inner, (stored as Record<string, unknown>)[key]))
	}
	return answer === stored
}

/**
 * Wait until the server answers `url` with what a file written by the test holds (`select` picks it out of the answer): it serves what it read
 * until the watcher tells it the file changed, and an open page would load the old copy, then hear of the new one ("Changed elsewhere").
 */
export async function untilServed(request: APIRequestContext, url: string, select: (answer: any) => unknown, expected: unknown) {
	await expect.poll(async () => servedAs(select(await (await request.get(url)).json()), expected), { timeout: 15_000 }).toBe(true)
}
