import fs from "node:fs"
import path from "node:path"
import { expect, test, type Page } from "@playwright/test"
import { OPEN } from "./servers"
import { saveButton, stubMapTiles, untilServed, watchProblems } from "./support"

// The GPIO tab lists the push buttons wired to the Pi: a pin and what pressing it does. The test saves on the open server, so its file is put back afterwards for the other specs.
test.describe.configure({ mode: "serial" })
const FILE = path.join(OPEN.storage, "settings", "devices-settings.json")
let original = ""
test.beforeAll(() => { original = fs.readFileSync(FILE, "utf8") })
test.afterAll(() => { fs.writeFileSync(FILE, original) })
test.beforeEach(async ({ page, request }) => {
	// the page must load the fixture, not what the last test saved
	if (fs.readFileSync(FILE, "utf8") !== original) {
		fs.writeFileSync(FILE, original)
		await untilServed(request, `${OPEN.url}/api/settings/devices`, answer => answer.triggers, JSON.parse(original).triggers)
	}
	await stubMapTiles(page)
})

test("the devices tab lists the buttons: a pin and an action, none to start with", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "GPIO" }).click()
	await expect(page.getByRole("group", { name: "Triggers" })).toBeVisible()
	await expect(page.getByRole("combobox", { name: "GPIO Pin 1" })).toHaveCount(0)
	watch.expectNone()
})

// a row's pin is chosen from the list the server gives (`GET /api/system/gpio-pins`: the header's pins, the panel's not available)
async function choosePin(page: Page, row: number, pin: number) {
	await page.getByRole("combobox", { name: `GPIO Pin ${row}` }).click()
	// the list that was just opened is the last one in the page: the one a row chose from before may still be leaving
	await page.getByRole("option", { name: `GPIO ${pin}`, exact: true }).last().click()
}

test("a pin is one of the header's, a pin has one button, and Play, Stop, Toggle and Next are each on one button", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "GPIO" }).click()
	await page.getByRole("button", { name: "Add to Triggers" }).click()
	await page.getByRole("button", { name: "Add to Triggers" }).click()
	// the list is the header's pins, 2 to 27, and nothing else can be chosen
	await page.getByRole("combobox", { name: "GPIO Pin 1" }).click()
	await expect(page.getByRole("option", { name: /^GPIO \d+/ })).toHaveCount(26)
	await expect(page.getByRole("option", { name: "GPIO 28", exact: true })).toHaveCount(0)
	await page.keyboard.press("Escape")
	await choosePin(page, 1, 5)
	await choosePin(page, 2, 5)
	await expect(page.getByText("Must be unique")).toBeVisible()
	await choosePin(page, 2, 6)
	// both buttons start as Toggle: only one may
	await expect(page.getByText("Already used by another row")).toBeVisible()
	await page.getByRole("combobox", { name: "Action 2" }).click()
	await page.getByRole("option", { name: "next", exact: true }).click()
	await expect(page.getByText("Already used by another row")).toHaveCount(0)
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	expect(JSON.parse(fs.readFileSync(FILE, "utf8")).triggers).toEqual([{ pin: 5, action: "toggle" }, { pin: 6, action: "next" }])
	watch.expectNone()
})

test("a button can run a task: its Priority Update is set up on the row, Run now starts the saved one, and another action drops it", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "GPIO" }).click()
	await page.getByRole("button", { name: "Add to Triggers" }).click()
	await choosePin(page, 1, 16)
	await page.getByRole("combobox", { name: "Action 1" }).click()
	await page.getByRole("option", { name: "task", exact: true }).click()
	// a task needs its settings: nothing to run, and a save is refused until they are set
	await expect(page.getByRole("button", { name: "Run task 1 now" })).toBeDisabled()
	await page.getByRole("button", { name: "Task settings 1" }).click()
	const dialog = page.getByRole("dialog", { name: "Task for Triggers 1" })
	await expect(dialog).toBeVisible()
	await expect(dialog.getByText("Priority Update", { exact: true })).toBeVisible()
	await dialog.locator(".p-select").filter({ hasText: "Data Source" }).first().click()
	await page.getByRole("option").filter({ hasText: "Year Progress" }).first().click()
	await dialog.getByRole("button", { name: "Apply" }).click()
	await expect(dialog).toHaveCount(0)
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully")).toBeVisible()
	const row = () => JSON.parse(fs.readFileSync(FILE, "utf8")).triggers[0]
	expect(row()).toMatchObject({ pin: 16, action: "task", content: { dataSource: "year-progress" } })
	// the saved task runs as if the button was pressed
	await page.getByRole("button", { name: "Run task 1 now" }).click()
	await expect(page.getByText("Started.")).toBeVisible()
	// another action keeps none of the task's settings
	await page.getByRole("combobox", { name: "Action 1" }).click()
	await page.getByRole("option", { name: "next", exact: true }).click()
	await saveButton(page).click()
	await expect(page.getByText("Settings saved successfully").last()).toBeVisible()
	await expect.poll(() => row().content).toBeUndefined()
	expect(row()).toEqual({ pin: 16, action: "next" })
	watch.expectNone()
})

test("a pin the panel uses is listed and cannot be chosen, and the server says so if it is saved anyway", async ({ page }) => {
	const watch = watchProblems(page)
	// the open server's display is a mock with no lines of its own: the list a Waveshare gives is stood in for
	const pins = Array.from({ length: 26 }, (_, i) => ({ value: i + 2, name: i + 2 === 17 ? "GPIO 17 · not available: the panel's reset" : `GPIO ${i + 2}`, disabled: i + 2 === 17 }))
	await page.route("**/api/system/gpio-pins", route => route.fulfill({ json: pins }))
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "GPIO" }).click()
	await page.getByRole("button", { name: "Add to Triggers" }).click()
	await page.getByRole("combobox", { name: "GPIO Pin 1" }).click()
	const taken = page.getByRole("option", { name: "GPIO 17 · not available: the panel's reset" })
	await expect(taken).toBeVisible()
	await expect(taken).toHaveAttribute("aria-disabled", "true")
	await expect(page.getByRole("option", { name: "GPIO 5", exact: true })).not.toHaveAttribute("aria-disabled", "true")
	watch.expectNone()
})

test("the GPIO tab shows the buttons live: what each pin did, and what the device made of it", async ({ page }) => {
	const watch = watchProblems(page)
	// the link is the page's own stand-in: what the server would send for a press of a bound pin, and for one the device could not act on
	await page.routeWebSocket(/\/api\/telemetry/, ws => {
		ws.send(JSON.stringify({ kind: "hello", run: "r1", seq: 0 }))
		const event = (seq: number, source: string, kind: string, message: string, values: object = {}) =>
			ws.send(JSON.stringify({ seq, ts: `2026-10-30T10:00:0${seq}Z`, source, kind, message, values }))
		event(1, "device-io", "gpio", "GPIO 5: pressed")
		event(2, "application", "input", "The button on pin 5 was pressed: next.", { result: "done" })
		event(3, "device-io", "gpio", "GPIO 6: pressed")
		event(4, "application", "input", "The button on pin 6 was pressed: next ignored, the device is not set up yet (not claimed, or its clock is not set).", { result: "ignored" })
	})
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "GPIO" }).click()
	const live = page.getByTestId("gpio-live")
	await expect(live.locator("[data-level=pin]")).toHaveText([/GPIO 6: pressed/, /GPIO 5: pressed/])
	await expect(live.locator("[data-level=action]")).toHaveText([/next ignored, the device is not set up yet/, /pressed: next\./])
	watch.expectNone()
})
