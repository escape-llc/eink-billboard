import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { LAYERS, TelemetryLink, clockOf, isProblem, layerOf, layersOf, socketUrl, type SocketLike } from "./TelemetryLink"

class FakeSocket implements SocketLike {
	onopen: ((ev: any) => void) | null = null
	onmessage: ((ev: { data: any }) => void) | null = null
	onclose: ((ev: { code: number }) => void) | null = null
	closed = false
	url: string
	constructor(url: string) { this.url = url }
	close() { this.closed = true }
	open() { this.onopen?.({}) }
	send(event: object) { this.onmessage?.({ data: JSON.stringify(event) }) }
	drop(code = 1006) { this.onclose?.({ code }) }
}

describe("addresses and times", () => {
	it("the socket is the API's address with ws or wss", () => {
		expect(socketUrl("/", 0, { href: "http://device.local/#/settings" })).toBe("ws://device.local/api/telemetry/ws?since=0")
		expect(socketUrl("https://pi.example:8443", 7, { href: "http://localhost:5173/" })).toBe("wss://pi.example:8443/api/telemetry/ws?since=7")
	})
	it("an event's time is the device's, read from its own offset", () => {
		expect(clockOf("2026-10-11T12:05:09-07:00")).toBe("12:05:09")
		expect(clockOf(undefined)).toBe("")
	})
	it("failures and gaps are problems", () => {
		expect(isProblem({ source: "playlist_layer", kind: "track-failed" })).toBe(true)
		expect(isProblem({ source: "telemetry", kind: "gap" })).toBe(true)
		expect(isProblem({ source: "display", kind: "shown" })).toBe(false)
	})
})

describe("the link", () => {
	let sockets: FakeSocket[]
	let link: TelemetryLink
	beforeEach(() => {
		vi.useFakeTimers()
		vi.stubGlobal("fetch", vi.fn(async () => new Response("null", { status: 200, headers: { "Content-Type": "application/json" } })))
		vi.stubGlobal("window", { location: { href: "http://device.local/" } })
		sockets = []
		link = new TelemetryLink("/", (url) => { const s = new FakeSocket(url); sockets.push(s); return s }, 3)
	})
	afterEach(() => {
		link.stop()
		vi.useRealTimers()
		vi.unstubAllGlobals()
	})

	it("keeps the newest events first, at most its limit, and what is shown now", () => {
		link.start()
		sockets[0]!.open()
		expect(link.state.status).toBe("live")
		for (const seq of [1, 2, 3, 4]) sockets[0]!.send({ seq, source: "timer_layer", kind: "waiting" })
		sockets[0]!.send({ seq: 5, source: "display", kind: "shown", values: { digest: "ab", title: "Calendar" } })
		sockets[0]!.send({ source: "telemetry", kind: "ping" })
		expect(link.state.events.map(e => e.seq)).toEqual([5, 4, 3])
		expect(link.state.current?.values?.title).toBe("Calendar")
		sockets[0]!.send({ seq: 4, source: "timer_layer", kind: "waiting" })
		expect(link.state.events.length).toBe(3)
	})

	it("tells who follows it every event, and when it opens again after it was down (events may be lost then)", () => {
		const heard: string[] = []
		const stop = link.listen({ event: e => heard.push(e.kind), resumed: () => heard.push("resumed") })
		link.start()
		sockets[0]!.open()
		sockets[0]!.send({ kind: "hello", source: "telemetry", run: "r1" })
		sockets[0]!.send({ seq: 1, source: "application", kind: "config-changed", values: { changed: ["/api/settings/theme"] } })
		sockets[0]!.send({ seq: 1, source: "application", kind: "config-changed" })
		sockets[0]!.send({ source: "telemetry", kind: "gap", missed: 3 })
		// the first open is no resumption; a repeated event and the hello are not told
		expect(heard).toEqual(["config-changed", "gap"])
		sockets[0]!.drop()
		vi.advanceTimersByTime(1000)
		sockets[1]!.open()
		expect(heard).toEqual(["config-changed", "gap", "resumed"])
		// the device started again: everything it said before is of the last run
		sockets[1]!.send({ kind: "hello", source: "telemetry", run: "r2" })
		expect(heard.at(-1)).toBe("resumed")
		stop()
		sockets[1]!.send({ seq: 2, source: "application", kind: "config-changed" })
		expect(heard.filter(k => k === "config-changed").length).toBe(1)
	})

	it("tells which events are the hub's history: those up to the hello's seq", () => {
		const heard: string[] = []
		link.listen({ event: (e, replayed) => heard.push(`${e.seq}${replayed ? " replayed" : ""}`) })
		link.start()
		sockets[0]!.open()
		sockets[0]!.send({ kind: "hello", source: "telemetry", run: "r1", seq: 2 })
		for (const seq of [1, 2, 3]) sockets[0]!.send({ seq, source: "application", kind: "config-changed" })
		expect(heard).toEqual(["1 replayed", "2 replayed", "3"])
		sockets[0]!.drop()
		vi.advanceTimersByTime(1000)
		// the next connection's history is what it missed
		sockets[1]!.open()
		sockets[1]!.send({ kind: "hello", source: "telemetry", run: "r1", seq: 5 })
		for (const seq of [4, 5, 6]) sockets[1]!.send({ seq, source: "application", kind: "config-changed" })
		expect(heard.slice(3)).toEqual(["4 replayed", "5 replayed", "6"])
	})

	it("a listener that throws does not stop the others or the link", () => {
		const heard: string[] = []
		vi.spyOn(console, "error").mockImplementation(() => {})
		link.listen({ event: () => { throw new Error("boom") } })
		link.listen({ event: e => heard.push(e.kind) })
		link.start()
		sockets[0]!.open()
		sockets[0]!.send({ seq: 1, source: "timer_layer", kind: "waiting" })
		expect(heard).toEqual(["waiting"])
		expect(link.state.events.length).toBe(1)
	})

	it("when the device started again, starts over with the new run's events", () => {
		link.start()
		sockets[0]!.open()
		sockets[0]!.send({ kind: "hello", source: "telemetry", run: "r1" })
		sockets[0]!.send({ seq: 40, source: "display", kind: "shown", values: { digest: "aa", title: "Old" } })
		sockets[0]!.drop()
		vi.advanceTimersByTime(1000)
		// the same run: it resumes after the last event
		expect(sockets[1]!.url).toBe("ws://device.local/api/telemetry/ws?since=40&run=r1")
		sockets[1]!.open()
		sockets[1]!.send({ kind: "hello", source: "telemetry", run: "r1" })
		expect(link.state.events.length).toBe(1)
		sockets[1]!.drop()
		vi.advanceTimersByTime(1000)
		// another run: what was kept is the last run's, and the new run's low numbers are taken
		sockets[2]!.open()
		sockets[2]!.send({ kind: "hello", source: "telemetry", run: "r2" })
		expect(link.state.events).toEqual([])
		expect(link.state.current).toBeNull()
		sockets[2]!.send({ seq: 1, source: "timer_layer", kind: "waiting" })
		sockets[2]!.send({ seq: 2, source: "display", kind: "shown", values: { digest: "bb", title: "New" } })
		expect(link.state.events.map(e => e.seq)).toEqual([2, 1])
		expect(link.state.current?.values?.title).toBe("New")
	})

	it("reconnects with a growing wait and resumes after the last event", () => {
		link.start()
		sockets[0]!.open()
		sockets[0]!.send({ seq: 9, source: "timer_layer", kind: "waiting" })
		sockets[0]!.drop()
		expect(link.state.status).toBe("offline")
		vi.advanceTimersByTime(999)
		expect(sockets.length).toBe(1)
		vi.advanceTimersByTime(1)
		expect(sockets[1]!.url).toBe("ws://device.local/api/telemetry/ws?since=9")
		sockets[1]!.drop()
		vi.advanceTimersByTime(1999)
		expect(sockets.length).toBe(2)
		vi.advanceTimersByTime(1)
		expect(sockets.length).toBe(3)
		// a connection that opens starts the wait over
		sockets[2]!.open()
		sockets[2]!.drop()
		vi.advanceTimersByTime(1000)
		expect(sockets.length).toBe(4)
	})

	it("asks for a sign-in when the server wants one, then connects again", async () => {
		link.start()
		sockets[0]!.drop(4401)
		expect(link.state.status).toBe("signed-out")
		// the HTTP call (which signs in through ApiClient) answers, then the link connects again
		await vi.runAllTimersAsync()
		expect(sockets.length).toBe(2)
		expect((fetch as any).mock.calls.map((c: any[]) => String(c[0]))).toContain("/api/telemetry?since=0")
	})

	it("stops for good", () => {
		link.start()
		link.stop()
		expect(sockets[0]!.closed).toBe(true)
		sockets[0]!.drop()
		vi.advanceTimersByTime(60000)
		expect(sockets.length).toBe(1)
	})
})

describe("who made the image", () => {
	const track = { kind: "playlist", title: "Morning Joe", plugin: "Slide Show", name: "Main" }
	const task = { kind: "timer", title: "Clock", plugin: "Overlay" }
	it("names the playlist and track, or the timer task, for each layer", () => {
		const e = { source: "display", kind: "shown", values: { layers: [
			{ layer: "background", title: "Photo", origin: track },
			{ layer: "overlays", count: 2, origins: [task, { ...task, title: "Date" }] },
		] } }
		expect(layersOf(e)).toEqual([
			{ layer: "background", text: "Main › Morning Joe (Slide Show)", kind: "playlist" },
			{ layer: "overlay", text: "Clock (Overlay)", kind: "timer" },
			{ layer: "overlay", text: "Date (Overlay)", kind: "timer" },
		])
	})
	it("names a layer nobody marked by its title, counts overlays nobody marked, and has no lines for no event", () => {
		expect(layersOf({ source: "display", kind: "shown", values: { layers: [{ layer: "background", title: "Setup" }, { layer: "overlays", count: 2 }] } })).toEqual([
			{ layer: "background", text: "Setup" },
			{ layer: "overlay", text: "2 overlays" },
		])
		expect(layersOf(null)).toEqual([])
	})
	it("reads the compositor's override as the foreground, and every layer has a glyph", () => {
		expect(["background", "override", "blend", "timer-blend", "priority", "overlays"].map(layerOf)).toEqual(["background", "foreground", "blend", "blend", "priority", "overlay"])
		expect(LAYERS.foreground.short).toBe("fg")
		for (const layer of Object.values(LAYERS)) expect(layer.glyph).toMatch(/^mi mi-[a-z-]+$/)
	})
})
