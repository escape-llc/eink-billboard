import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { TelemetryLink, clockOf, isProblem, socketUrl, type SocketLike } from "./TelemetryLink"

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
