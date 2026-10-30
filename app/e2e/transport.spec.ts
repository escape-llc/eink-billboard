import { expect, test } from "@playwright/test"
import { stubMapTiles, watchProblems } from "./support"

// Play, stop and next for the playlist, from the System page, on the real server (python/web/routers/transport.py): the button follows
// what the playlist layer reports, so a click is checked by the event the layer sends.
test.beforeEach(async ({ page }) => stubMapTiles(page))

test("the System page stops and plays the playlist, and goes to the next track", async ({ page, request }) => {
	const watch = watchProblems(page)
	try {
		await page.goto("/#/system")
		const live = page.locator(".system-live")
		await expect(live).toHaveAttribute("data-link", "live")
		const playback = page.getByRole("group", { name: "Playback" })
		const events = live.getByRole("region", { name: "Activity" })
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

test("the playlist panel shows the playlist that plays, and marks the track the layer says, as it moves on", async ({ page, request }) => {
	const watch = watchProblems(page)
	try {
		await page.goto("/#/system")
		const panel = page.getByRole("region", { name: "Playlist" })
		const strip = panel.getByRole("list", { name: "Tracks" })
		// the one playing is the layer's track, by id (GET /api/transport, then each track-started)
		const playing = strip.locator("li[aria-current=true]")
		await expect(playing).toHaveCount(1, { timeout: 20000 })
		const where = await (await request.get("/api/transport")).json()
		const list = await (await request.get("/api/schedule/playlist/list")).json()
		const shown = list.playlists.find((p: { id: string }) => p.id === where.playlist_id)
		await expect(panel.getByTestId("playlist-name")).toHaveText(shown.name)
		await expect(strip.getByRole("listitem")).toHaveText(shown.items.map((t: { title: string }) => t.title))
		// next: the mark moves to the track the layer starts
		const before = await playing.textContent()
		await panel.getByRole("group", { name: "Playback" }).getByRole("button", { name: "Next track" }).click()
		await expect.poll(async () => (await (await request.get("/api/transport")).json()).track_id).not.toBe(where.track_id)
		const now = await (await request.get("/api/transport")).json()
		const title = shown.items.find((t: { id: string }) => t.id === now.track_id)?.title
		if (shown.items.length > 1) await expect(playing).not.toHaveText(before ?? "")
		await expect(playing).toHaveText(title)
	} finally {
		await request.post("/api/transport", { data: { command: "play" } })
	}
	watch.expectNone()
})

test("the playback tag says so when the page cannot hear from the device, not what the layer last said", async ({ page }) => {
	await stubMapTiles(page)
	// the link never opens: the page has no news of the layer
	await page.routeWebSocket(/\/api\/telemetry/, ws => ws.close())
	await page.goto("/#/system")
	const tag = page.getByTestId("playback-state")
	await expect(tag).toHaveText(/Offline|Connecting/)
	await expect(tag).not.toHaveText("Playing")
})
