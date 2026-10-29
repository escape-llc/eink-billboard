import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { reactive } from "vue"
import { api } from "../api/client"
import type { TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"
import { useSystem } from "./useSystem"

// the System page's device data without the page: the API is a stand-in, and so is the telemetry link (what the panel shows is usePanelNow's)
vi.mock("../api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
const mocked = api as unknown as Record<"get", ReturnType<typeof vi.fn>>

const event = (seq: number, kind: string, extra: Partial<TelemetryEvent> = {}): TelemetryEvent =>
	({ seq, ts: "2026-10-23T10:00:00Z", source: "playlist_layer", kind, ...extra })
const shown = (seq: number, digest: string) => event(seq, "shown", { source: "display", values: { digest, title: digest } })
const failure = (seq: number) => event(seq, "error", { source: "data-source", message: "The feed did not answer" })

function fakes() {
	const state = reactive({ status: "connecting" as string, events: [] as TelemetryEvent[], current: null as TelemetryEvent | null })
	const link = { state, start: vi.fn(), stop: vi.fn() }
	return { link, options: { link: link as unknown as TelemetryLink, webCommit: "abc1234", pollMs: 1000 } }
}
function serve(system: object = { host: { commit: "abc1234" }, storage: { datasources: [{ id: "rss" }], plugins: [] } }, status: object = { ok: true, components: { display: { state: "running" } } }) {
	mocked.get.mockImplementation(async (path: string) => {
		if(path === "/api/status") return status
		if(path === "/api/system") return system
		throw new Error(`no route ${path}`)
	})
}
const settled = async () => { for(let i = 0; i < 4; i++) await Promise.resolve() }

beforeEach(() => { mocked.get.mockReset(); vi.useFakeTimers() })
afterEach(() => vi.useRealTimers())

describe("the device", () => {
	it("loads the status and the readings, opens the link after the first answer, and asks again on its interval", async () => {
		serve()
		const { link, options } = fakes()
		const sys = useSystem(options)
		sys.start()
		await settled()
		expect([sys.deviceState.value, sys.deviceSeverity.value, sys.deviceLabel.value]).toEqual(["ok", "success", "Running"])
		expect(sys.owners.value.map(o => o.title)).toEqual(["Data sources", "Plugins"])
		expect(sys.mismatch.value).toBe(false)
		expect(link.start).toHaveBeenCalledTimes(1)
		await vi.advanceTimersByTimeAsync(1000)
		expect(mocked.get).toHaveBeenCalledTimes(4)
		sys.stop()
		// the link is the app's: leaving the page leaves it open
		expect(link.stop).not.toHaveBeenCalled()
		await vi.advanceTimersByTimeAsync(5000)
		expect(mocked.get).toHaveBeenCalledTimes(4)
	})

	it("a part that did not start is a failure; a server of another build is a mismatch; readings that fail say so", async () => {
		serve({ host: { commit: "fff0000" }, storage: { datasources: [], plugins: [] } }, { ok: false, components: { display: { state: "failed" } } })
		const sys = useSystem(fakes().options)
		await sys.load()
		await settled()
		expect([sys.deviceState.value, sys.deviceLabel.value]).toEqual(["failed", "A part did not start"])
		expect(sys.mismatch.value).toBe(true)
		mocked.get.mockRejectedValue(new Error("down"))
		await sys.load()
		await settled()
		expect(sys.failed.value).toBe(true)
	})

	it("a server outside the container, or a page of a development build, is never a mismatch", async () => {
		serve({ host: { commit: "unknown" }, storage: { datasources: [], plugins: [] } })
		const sys = useSystem(fakes().options)
		await sys.load(); await settled()
		expect(sys.mismatch.value).toBe(false)
		serve()
		const dev = useSystem({ ...fakes().options, webCommit: "dev" })
		await dev.load(); await settled()
		expect(dev.mismatch.value).toBe(false)
	})
})

describe("the problems", () => {
	it("are the latest few that went wrong, newest first", () => {
		const { link, options } = fakes()
		const sys = useSystem(options)
		link.state.events.push(failure(3), shown(2, "a"), failure(1))
		expect(sys.problems.value.map(e => e.seq)).toEqual([3, 1])
	})
})
