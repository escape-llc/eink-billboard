import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { Transport, stoppedBy } from "./Transport"
import type { TelemetryEvent } from "./TelemetryLink"

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
const event = (kind: string, state?: string): TelemetryEvent => ({ source: "playlist_layer", kind, values: state ? { state } : {} })

describe("what the events say", () => {
	it("is the newest transport event, whatever happened since", () => {
		// newest first, as the link keeps them
		expect(stoppedBy([event("track-started", "playing"), event("transport", "halted"), event("transport", "playing")])).toBe(true)
		expect(stoppedBy([event("transport", "playing"), event("transport", "halted")])).toBe(false)
	})
	it("is nothing when no event is about it", () => {
		expect(stoppedBy([])).toBeUndefined()
		expect(stoppedBy([event("track-started", "playing")])).toBeUndefined()
	})
})

describe("the transport", () => {
	let calls: { url: string; init?: RequestInit }[]
	let answer: (url: string, init?: RequestInit) => Response | Promise<Response>
	let transport: Transport
	beforeEach(() => {
		calls = []
		answer = () => json({ success: true })
		vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => { calls.push({ url, init }); return answer(url, init) }))
		transport = new Transport()
	})
	afterEach(() => vi.unstubAllGlobals())

	it("asks the device whether it is stopped", async () => {
		answer = () => json({ stopped: true })
		await transport.load()
		expect(calls[0]?.url).toBe("/api/transport")
		expect(transport.state.stopped).toBe(true)
	})

	it("keeps what it knew when the device does not answer", async () => {
		transport.state.stopped = true
		answer = () => json({ success: false, message: "The device is still starting." }, 503)
		await transport.load()
		expect(transport.state.stopped).toBe(true)
	})

	it("sends the command as JSON and shows the result at once", async () => {
		await transport.send("stop")
		expect(calls[0]?.url).toBe("/api/transport")
		expect(calls[0]?.init?.method).toBe("POST")
		expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ command: "stop" })
		expect(transport.state.stopped).toBe(true)
		await transport.send("play")
		expect(transport.state.stopped).toBe(false)
		await transport.send("stop")
		await transport.send("next")
		// a next from a stopped layer plays
		expect(transport.state.stopped).toBe(false)
	})

	it("drops a click while one is on its way, and is free again after", async () => {
		let release: (r: Response) => void = () => {}
		answer = () => new Promise<Response>(resolve => { release = resolve })
		const first = transport.send("stop")
		expect(transport.state.busy).toBe(true)
		await transport.send("next")
		expect(calls).toHaveLength(1)
		release(json({ success: true }))
		await first
		expect(transport.state.busy).toBe(false)
	})

	it("passes on the server's own message when a command is refused, and does not change what it shows", async () => {
		answer = () => json({ success: false, message: "The device is still starting.", id: null }, 503)
		await expect(transport.send("stop")).rejects.toThrow("The device is still starting.")
		expect(transport.state).toMatchObject({ stopped: false, busy: false })
	})

	it("follows the link's events", () => {
		transport.follow([event("transport", "halted")])
		expect(transport.state.stopped).toBe(true)
		transport.follow([event("track-started", "playing")])
		expect(transport.state.stopped).toBe(true)
		transport.follow([event("transport", "playing"), event("transport", "halted")])
		expect(transport.state.stopped).toBe(false)
	})
})
