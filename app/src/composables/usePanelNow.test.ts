import { describe, expect, it, vi } from "vitest"
import { nextTick, reactive } from "vue"
import type { TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"
import type { Transport } from "../components/Transport"
import { PROBLEM_WINDOW_MS, describeEvent, eventIcon, latestActivity, relativeTime, usePanelNow } from "./usePanelNow"

// what the panel shows, without a page: the telemetry link and the transport are stand-ins
const event = (seq: number, kind: string, extra: Partial<TelemetryEvent> = {}): TelemetryEvent =>
	({ seq, ts: "2026-10-23T10:00:00Z", source: "playlist_layer", kind, ...extra })
const shown = (seq: number, digest: string) => event(seq, "shown", { source: "display", values: { digest, title: digest } })
const failure = (seq: number) => event(seq, "error", { source: "data-source", message: "The feed did not answer" })

function fakes() {
	const state = reactive({ status: "connecting" as string, events: [] as TelemetryEvent[], current: null as TelemetryEvent | null })
	const link = { state, start: vi.fn(), stop: vi.fn() }
	const transport = { load: vi.fn(async () => {}), follow: vi.fn(), send: vi.fn(async () => {}) }
	return { link, transport, options: { link: link as unknown as TelemetryLink, transport: transport as unknown as Transport } }
}

describe("the transport", () => {
	it("is loaded when the link comes up and follows the layer's events", async () => {
		const { link, transport, options } = fakes()
		usePanelNow(() => {}, options)
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
		const sys = usePanelNow(d => notices.push(d), options)
		await sys.press("play")
		expect(transport.send).toHaveBeenCalledWith("play")
		expect(notices).toEqual(["The device is not set up."])
	})
})

describe("the panels", () => {
	it("Now showing is the current picture; Recent has each picture once, newest first", () => {
		const { link, options } = fakes()
		const sys = usePanelNow(() => {}, options)
		link.state.current = shown(9, "c")
		link.state.events.push(shown(8, "b"), shown(7, "c"), shown(6, "a"), event(5, "track-started"))
		expect(sys.current.value?.values?.digest).toBe("c")
		expect(sys.recent.value.map(e => e.values?.digest)).toEqual(["c", "b", "a"])
	})

	it("Activity is narrowed by source and to problems", () => {
		const { link, options } = fakes()
		const sys = usePanelNow(() => {}, options)
		link.state.events.push(failure(3), shown(2, "a"), event(1, "track-started"))
		expect(sys.shownEvents.value.length).toBe(3)
		sys.source.value = "display"
		expect(sys.shownEvents.value.map(e => e.seq)).toEqual([2])
		sys.source.value = "all"
		sys.problemsOnly.value = true
		expect(sys.shownEvents.value.map(e => e.seq)).toEqual([3])
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

describe("Home's line", () => {
	const at = (iso: string) => Date.parse(iso)
	const routine = (seq: number, ts: string) => event(seq, "shown", { source: "display", ts, values: { title: "Weather" } })
	const problem = (seq: number, ts: string) => ({ ...failure(seq), ts })

	it("is a problem from the last hour, over anything routine that came after it", () => {
		const events = [routine(3, "2026-10-23T10:50:00Z"), problem(2, "2026-10-23T10:20:00Z"), routine(1, "2026-10-23T10:00:00Z")]
		expect(latestActivity(events, at("2026-10-23T11:00:00Z"))).toEqual({ event: events[1], problem: true })
	})

	it("is the latest routine event once the problem is more than an hour old, and never the link's own messages", () => {
		const events = [event(4, "ping", { source: "telemetry", ts: "2026-10-23T10:55:00Z" }), routine(3, "2026-10-23T10:50:00Z"), problem(2, "2026-10-23T09:00:00Z")]
		const now = at("2026-10-23T09:00:00Z") + PROBLEM_WINDOW_MS + 60000
		expect(latestActivity(events, now)).toEqual({ event: events[1], problem: false })
		expect(latestActivity([], now)).toBeNull()
	})

	it("says how long ago in words, and nothing for what is not a time", () => {
		const now = at("2026-10-23T12:00:00Z")
		expect(relativeTime("2026-10-23T11:59:30Z", now)).toBe("just now")
		expect(relativeTime("2026-10-23T12:00:30Z", now)).toBe("just now")
		expect(relativeTime("2026-10-23T11:58:00Z", now)).toBe("2 min ago")
		expect(relativeTime("2026-10-23T09:00:00Z", now)).toBe("3 h ago")
		expect(relativeTime("2026-10-21T11:00:00Z", now)).toBe("2 d ago")
		expect(relativeTime(undefined, now)).toBe("")
	})
})
