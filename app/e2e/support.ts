import { expect, type Page } from "@playwright/test"

// a 1x1 transparent PNG: the location picker's map tiles come from the internet, which the tests must not need
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64")

export async function stubMapTiles(page: Page) {
	await page.route("**/*.tile.openstreetmap.org/**", route => route.fulfill({ status: 200, contentType: "image/png", body: PIXEL }))
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

/** Open a PrimeVue Select that currently shows `current` and choose the option containing `option`. */
export async function choose(page: Page, current: string | RegExp, option: string | RegExp) {
	await page.locator(".p-select").filter({ hasText: current }).first().click()
	await page.getByRole("option").filter({ hasText: option }).first().click()
}

/** The save (check mark) button of the settings form in the tab that is showing. */
export const saveButton = (page: Page) => page.getByRole("tabpanel").locator("button:has(.pi-check)").first()
