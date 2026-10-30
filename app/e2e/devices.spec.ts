import fs from "node:fs"
import path from "node:path"
import { expect, test } from "@playwright/test"
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
	await expect(page.getByRole("spinbutton", { name: "GPIO Pin 1" })).toHaveCount(0)
	watch.expectNone()
})

test("a pin keeps to the header, a pin has one button, and Play, Stop, Toggle and Next are each on one button", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "GPIO" }).click()
	await page.getByRole("button", { name: "Add to Triggers" }).click()
	await page.getByRole("button", { name: "Add to Triggers" }).click()
	const pin = (row: number) => page.getByRole("spinbutton", { name: `GPIO Pin ${row}` })
	await pin(1).fill("40")
	await pin(1).blur()
	// the number field keeps what is typed inside the header's pins
	await expect(pin(1)).toHaveValue("27")
	await pin(1).fill("5")
	await pin(1).blur()
	await pin(2).fill("5")
	await pin(2).blur()
	await expect(page.getByText("Must be unique")).toBeVisible()
	await pin(2).fill("6")
	await pin(2).blur()
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
	await page.getByRole("spinbutton", { name: "GPIO Pin 1" }).fill("16")
	await page.getByRole("spinbutton", { name: "GPIO Pin 1" }).blur()
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
