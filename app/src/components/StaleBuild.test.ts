import { describe, expect, it, vi } from "vitest"
import { isStaleChunk, reloadOnce } from "./StaleBuild"

function fakeWindow(state: unknown = null) {
	const win = {
		history: { state, replaceState: vi.fn((next: unknown, _title: string, _url?: string) => { win.history.state = next }) },
		location: { pathname: "/", search: "", reload: vi.fn() },
	}
	return win
}

describe("a tab of an old build", () => {
	it("knows a page's code that could not be loaded, as each browser words it", () => {
		expect(isStaleChunk(new TypeError("Failed to fetch dynamically imported module: http://pi:8080/assets/Settings-OLD.js"))).toBe(true)
		expect(isStaleChunk(new TypeError("error loading dynamically imported module"))).toBe(true)
		expect(isStaleChunk(new TypeError("Importing a module script failed."))).toBe(true)
		expect(isStaleChunk(new Error("Missing or invalid API token."))).toBe(false)
		expect(isStaleChunk(null)).toBe(false)
	})

	it("reloads at the route it was going to, once: a second failure soon after is left to show", () => {
		const win = fakeWindow({ back: "/" })
		expect(reloadOnce("#/settings", win as never, 1_000_000)).toBe(true)
		expect(win.location.reload).toHaveBeenCalledTimes(1)
		const [state, , url] = win.history.replaceState.mock.calls[0]!
		expect(url).toBe("/#/settings")
		// the router's own state is kept
		expect(state).toMatchObject({ back: "/" })
		// the reloaded page (same history state) fails again at once: a broken build, not an old one
		expect(reloadOnce("#/settings", win as never, 1_005_000)).toBe(false)
		expect(win.location.reload).toHaveBeenCalledTimes(1)
		// much later (another update): it reloads again
		expect(reloadOnce("#/schedule", win as never, 1_100_000)).toBe(true)
		expect(win.location.reload).toHaveBeenCalledTimes(2)
	})
})
