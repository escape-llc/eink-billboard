import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// Play, stop and next for the playlist, from the System page, on the real server (python/web/routers/transport.py): the button follows
// what the playlist layer reports, so a click is checked by the event the layer sends.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the System page stops and plays the playlist, and goes to the next track", async ({ page, request }) => {
	const watch = watchProblems(page)
	try {
		await page.goto("/#/system")
		const gutter = page.getByRole("region", { name: "Device activity" })
		await expect(gutter).toHaveAttribute("data-link", "live")
		const playback = gutter.getByRole("group", { name: "Playback" })
		const events = gutter.getByRole("region", { name: "Events" })
		// the layer has begun: it reports its first track
		await expect(events.getByText(/^Track started/).first()).toBeVisible({ timeout: 20000 })

		// playing: the button offers to stop
		await expect(playback.getByTestId("play-stop")).toHaveAttribute("data-state", "playing")
		await playback.getByRole("button", { name: "Stop playback" }).click()
		await expect(playback.getByRole("button", { name: "Play" })).toBeVisible()
		await expect(events.getByText("Playback is stopped.")).toBeVisible()
		expect((await (await request.get("/api/transport")).json()).stopped).toBe(true)

		// next from a stopped layer plays, from the following track
		const started = events.getByText(/^Track started/)
		const before = await started.count()
		await playback.getByRole("button", { name: "Next track" }).click()
		await expect(playback.getByRole("button", { name: "Stop playback" })).toBeVisible()
		await expect(events.getByText("Playback is resumed.").first()).toBeVisible()
		await expect.poll(() => started.count()).toBeGreaterThan(before)

		// next on a layer that plays: another track starts, and it keeps playing
		const mid = await started.count()
		await playback.getByRole("button", { name: "Next track" }).click()
		await expect.poll(() => started.count()).toBeGreaterThan(mid)
		await expect(playback.getByTestId("play-stop")).toHaveAttribute("data-state", "playing")

		// stop, then play
		await playback.getByRole("button", { name: "Stop playback" }).click()
		await expect(playback.getByRole("button", { name: "Play" })).toBeVisible()
		await playback.getByRole("button", { name: "Play" }).click()
		await expect(playback.getByRole("button", { name: "Stop playback" })).toBeVisible()
		await expect.poll(async () => (await (await request.get("/api/transport")).json()).stopped).toBe(false)
	} finally {
		// the other tests share this server: leave it playing
		await request.post("/api/transport", { data: { command: "play" } })
	}
	watch.expectNone()
})

test("a page opened while the playlist is stopped shows it stopped", async ({ page, request }) => {
	const watch = watchProblems(page)
	try {
		expect((await request.post("/api/transport", { data: { command: "stop" } })).ok()).toBeTruthy()
		await expect.poll(async () => (await (await request.get("/api/transport")).json()).stopped).toBe(true)
		await page.goto("/#/system")
		await expect(page.getByRole("group", { name: "Playback" }).getByRole("button", { name: "Play" })).toBeVisible({ timeout: 15000 })
	} finally {
		await request.post("/api/transport", { data: { command: "play" } })
	}
	watch.expectNone()
})
