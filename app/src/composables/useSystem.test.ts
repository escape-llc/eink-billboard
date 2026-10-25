import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick, reactive } from "vue"
import { api } from "../api/client"
import type { TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"
import type { Transport } from "../components/Transport"
import { describeEvent, eventIcon, useSystem } from "./useSystem"

// the System page's data without the page: the API is a stand-in, and so are the telemetry link and the transport
vi.mock("../api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
const mocked = api as unknown as Record<"get", ReturnType<typeof vi.fn>>

const event = (seq: number, kind: string, extra: Partial<TelemetryEvent> = {}): TelemetryEvent =>
	({ seq, ts: "2026-10-23T10:00:00Z", source: "playlist_layer", kind, ...extra })
const shown = (seq: number, digest: string) => event(seq, "shown", { source: "display", values: { digest, title: digest } })
const failure = (seq: number) => event(seq, "error", { source: "data-source", message: "The feed did not answer" })

function fakes() {
	const state = reactive({ status: "connecting" as string, events: [] as TelemetryEvent[], current: null as TelemetryEvent | null })
	const link = { state, start: vi.fn(), stop: vi.fn() }
	const transport = { load: vi.fn(async () => {}), follow: vi.fn(), send: vi.fn(async () => {}) }
	return { link, transport, options: { link: link as unknown as TelemetryLink, transport: transport as unknown as Transport, webCommit: "abc1234", pollMs: 1000 } }
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
		const sys = useSystem(() => {}, options)
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
		const sys = useSystem(() => {}, fakes().options)
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
		const sys = useSystem(() => {}, fakes().options)
		await sys.load(); await settled()
		expect(sys.mismatch.value).toBe(false)
		serve()
		const dev = useSystem(() => {}, { ...fakes().options, webCommit: "dev" })
		await dev.load(); await settled()
		expect(dev.mismatch.value).toBe(false)
	})
})

describe("the transport", () => {
	it("is loaded when the link comes up and follows the layer's events", async () => {
		const { link, transport, options } = fakes()
		useSystem(() => {}, options)
		expect(transport.load).not.toHaveBeenCalled()
		link.state.status = "live"
		await nextTick()
		expect(transport.load).toHaveBeenCalledTimes(1)
		link.state.events.unshift(event(1, "transport"))
		await nextTick()
		expect(transport.follow).toHaveBeenCalledWith(link.state.events)
	})

	it("a command that is refused is a notice", async () => {
		const { transport, options } = fakes()
		transport.send.mockRejectedValueOnce(new Error("The device is not set up."))
		const notices: string[] = []
		const sys = useSystem(d => notices.push(d), options)
		await sys.press("play")
		expect(transport.send).toHaveBeenCalledWith("play")
		expect(notices).toEqual(["The device is not set up."])
	})
})

describe("the panels", () => {
	it("Now showing is the current picture; Recent has each picture once, newest first", () => {
		const { link, options } = fakes()
		const sys = useSystem(() => {}, options)
		link.state.current = shown(9, "c")
		link.state.events.push(shown(8, "b"), shown(7, "c"), shown(6, "a"), event(5, "track-started"))
		expect(sys.current.value?.values?.digest).toBe("c")
		expect(sys.recent.value.map(e => e.values?.digest)).toEqual(["c", "b", "a"])
	})

	it("Activity is narrowed by source and to problems; the latest problems are on top", () => {
		const { link, options } = fakes()
		const sys = useSystem(() => {}, options)
		link.state.events.push(failure(3), shown(2, "a"), event(1, "track-started"))
		expect(sys.shownEvents.value.length).toBe(3)
		sys.source.value = "display"
		expect(sys.shownEvents.value.map(e => e.seq)).toEqual([2])
		sys.source.value = "all"
		sys.problemsOnly.value = true
		expect(sys.shownEvents.value.map(e => e.seq)).toEqual([3])
		expect(sys.problems.value.map(e => e.seq)).toEqual([3])
		expect([sys.statusText.value, sys.statusSeverity.value]).toEqual(["Connecting", "info"])
	})

	it("an event reads in our words, with its glyph", () => {
		expect(describeEvent(event(1, "track-started", { values: { current_track: "Morning" } }))).toBe("Track started: 'Morning'")
		expect(describeEvent(event(1, "waiting", { values: { delta: 300 } }))).toBe("Waiting 5 min for the next timer task")
		expect(describeEvent(failure(1))).toBe("The feed did not answer")
		expect(describeEvent(event(1, "something-new"))).toBe("something-new")
		expect(eventIcon(shown(1, "a"))).toBe("mi mi-screenshot-monitor")
		expect(eventIcon(event(1, "transport", { values: { state: "halted" } }))).toBe("mi mi-stop")
		expect(eventIcon(event(1, "unknown", { source: "timer_layer" }))).toBe("mi mi-schedule")
		expect(eventIcon(event(1, "unknown", { source: "elsewhere" }))).toBe("mi mi-circle")
	})
})
