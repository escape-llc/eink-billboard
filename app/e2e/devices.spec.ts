import fs from "node:fs"
import path from "node:path"
import { expect, test } from "@playwright/test"
import { OPEN } from "./servers"
import { saveButton, stubMapTiles, watchProblems } from "./support"

// The Devices tab lists the push buttons wired to the Pi: a pin and what pressing it does. The test saves on the open server, so its file is put back afterwards for the other specs.
test.describe.configure({ mode: "serial" })
const FILE = path.join(OPEN.storage, "settings", "devices-settings.json")
let original = ""
test.beforeAll(() => { original = fs.readFileSync(FILE, "utf8") })
test.afterAll(() => { fs.writeFileSync(FILE, original) })
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the devices tab lists the buttons: a pin and an action, none to start with", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Devices" }).click()
	await expect(page.getByRole("group", { name: "Triggers" })).toBeVisible()
	await expect(page.getByRole("spinbutton", { name: "GPIO Pin 1" })).toHaveCount(0)
	watch.expectNone()
})

test("a pin keeps to the header, a pin has one button, and Play, Stop, Toggle and Next are each on one button", async ({ page }) => {
	const watch = watchProblems(page)
	await page.goto("/#/settings")
	await page.getByRole("tab", { name: "Devices" }).click()
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
