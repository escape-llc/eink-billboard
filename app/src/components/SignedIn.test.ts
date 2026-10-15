import { describe, expect, it, vi } from "vitest"
import { justSignedIn, reloadAfterSignIn } from "./SignedIn"

function fakeWindow(state: unknown = null) {
	const win = {
		history: { state, replaceState: vi.fn((next: unknown, _title: string) => { win.history.state = next }) },
		location: { reload: vi.fn() },
	}
	return win
}

describe("after a sign-in", () => {
	it("the whole page is loaded again, and the new page says why once", () => {
		const win = fakeWindow({ back: "/" })
		reloadAfterSignIn(win as never, 1_000_000)
		expect(win.location.reload).toHaveBeenCalledTimes(1)
		// the reloaded page (the same history state)
		expect(justSignedIn(win as never, 1_002_000)).toBe(true)
		// the router's own state is kept, and the mark is gone: a reload by hand later says nothing
		expect(win.history.state).toEqual({ back: "/" })
		expect(justSignedIn(win as never, 1_003_000)).toBe(false)
	})

	it("a mark from long ago is not this reload's", () => {
		const win = fakeWindow({ signedInAt: 1_000_000 })
		expect(justSignedIn(win as never, 1_100_000)).toBe(false)
		expect(win.history.state).toEqual({})
	})
})
