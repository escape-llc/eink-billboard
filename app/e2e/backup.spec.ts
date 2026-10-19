import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// Back up and restore (System tab): the backup is one locked file; a restore says what it would change, by name, before it writes anything.
// The open server's storage must end as it began (the other specs read it), so the test changes one setting, restores over it and reads it back.
test.beforeEach(async ({ page }) => stubMapTiles(page))

const PASSPHRASE = "a passphrase for the tests"

async function systemSettings(page: import("@playwright/test").Page) {
	return await (await page.request.get("/api/settings/system")).json()
}

test("a backup is downloaded, and restoring it puts a changed setting back", async ({ page }) => {
	const watch = watchProblems(page, [403])
	await page.goto("/#/settings")
	const before = await systemSettings(page)

	// the two passphrases must agree and be long enough
	const make = page.getByTestId("backup-make")
	await make.getByLabel("Backup passphrase", { exact: true }).fill("short")
	await make.getByRole("button", { name: "Download backup" }).click()
	await expect(make.getByRole("alert")).toContainText("at least 12")
	await make.getByLabel("Backup passphrase", { exact: true }).fill(PASSPHRASE)
	await make.getByLabel("Repeat the backup passphrase").fill("something else entirely")
	await make.getByRole("button", { name: "Download backup" }).click()
	await expect(make.getByRole("alert")).toContainText("not the same")

	await make.getByLabel("Repeat the backup passphrase").fill(PASSPHRASE)
	const [download] = await Promise.all([page.waitForEvent("download"), make.getByRole("button", { name: "Download backup" }).click()])
	expect(download.suggestedFilename()).toMatch(/^eink-billboard-.*\.einkbackup$/)
	const file = await download.path()
	await expect(make.getByRole("status")).toContainText("was downloaded")
	// the fields are cleared once used
	await expect(make.getByLabel("Backup passphrase", { exact: true })).toHaveValue("")

	// change a setting behind the backup's back
	const other = before.timeFormat === "24h" ? "12h" : "24h"
	const put = await page.request.put("/api/settings/system", { data: { ...before, timeFormat: other } })
	expect(put.ok()).toBeTruthy()

	const restore = page.getByTestId("backup-restore")
	await page.getByTestId("backup-file").setInputFiles(file)
	await expect(page.getByTestId("backup-file-name")).not.toHaveText("No file chosen")
	// a wrong passphrase is said in the server's words and changes nothing
	await restore.getByLabel("Passphrase of the backup", { exact: true }).fill("not the passphrase")
	await restore.getByRole("button", { name: "Check backup" }).click()
	await expect(restore.getByRole("alert")).toContainText("not the right passphrase")
	await restore.getByLabel("Passphrase of the backup", { exact: true }).fill(PASSPHRASE)
	await restore.getByRole("button", { name: "Check backup" }).click()

	const summary = page.getByTestId("backup-summary")
	await expect(summary).toContainText("Settings: system")
	await expect(summary).toContainText("(changed)")
	await expect(summary).toContainText("Nothing is deleted")
	await expect(page.getByTestId("backup-made")).toContainText("This backup was made")
	expect((await systemSettings(page)).timeFormat).toBe(other)

	await page.getByTestId("backup-apply").click()
	await expect(page.getByRole("status").filter({ hasText: "was restored" })).toBeVisible()
	expect((await systemSettings(page)).timeFormat).toBe(before.timeFormat)
	watch.expectNone()
})

test("a file that is not a backup is refused", async ({ page }) => {
	const watch = watchProblems(page, [422])
	await page.goto("/#/settings")
	await page.getByTestId("backup-file").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("just some notes") })
	const restore = page.getByTestId("backup-restore")
	await restore.getByLabel("Passphrase of the backup", { exact: true }).fill(PASSPHRASE)
	await restore.getByRole("button", { name: "Check backup" }).click()
	await expect(restore.getByRole("alert")).toContainText("not an eInk Billboard backup")
	watch.expectNone()
})
