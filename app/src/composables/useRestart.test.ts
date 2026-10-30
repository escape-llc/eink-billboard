import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { GIVE_UP_MS, POLL_MS, restartApp, restartFailed, restarting } from "./useRestart"

// a restart without the app: the API and the clock are stand-ins
vi.mock("../api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }))
const mocked = api as unknown as Record<"get" | "post", ReturnType<typeof vi.fn>>

function clock() {
	let at = 0
	return { now: () => at, sleep: async (ms: number) => { at += ms } }
}

beforeEach(() => {
	mocked.post.mockReset()
	restarting.value = false
	restartFailed.value = ""
})

describe("restarting the app", () => {
	it("waits until the app is seen to be gone and to answer again, then loads the page anew", async () => {
		mocked.post.mockResolvedValue({ success: true })
		const reload = vi.fn()
		// answers (still shutting down), gone twice, then back
		const answers = [true, false, false, true]
		const ask = vi.fn(async () => { if (!answers.shift()) throw new Error("gone") })
		await restartApp({ ask, reload, ...clock() })
		expect(ask).toHaveBeenCalledTimes(4)
		expect(reload).toHaveBeenCalledOnce()
		expect(restarting.value).toBe(true)
	})

	it("does not take an answer from the app that is not yet gone for the app that is back", async () => {
		mocked.post.mockResolvedValue({ success: true })
		const reload = vi.fn()
		const ask = vi.fn(async () => undefined)
		await restartApp({ ask, reload, ...clock() })
		expect(reload).not.toHaveBeenCalled()
		expect(ask.mock.calls.length).toBe(GIVE_UP_MS / POLL_MS)
		expect(restarting.value).toBe(false)
		expect(restartFailed.value).toContain("did not come back")
	})

	it("says why when the server refuses, and waits for nothing", async () => {
		mocked.post.mockRejectedValue(new Error("Nothing here starts the app again."))
		const ask = vi.fn()
		await restartApp({ ask, ...clock() })
		expect(restartFailed.value).toBe("Nothing here starts the app again.")
		expect(restarting.value).toBe(false)
		expect(ask).not.toHaveBeenCalled()
	})
})
