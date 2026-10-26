import { beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick, reactive } from "vue"
import { api } from "../api/client"
import type { TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"
import { deviceStateOf, useDeviceStatus } from "./useDeviceStatus"

// the header's indicator without the header: the API and the telemetry link are stand-ins
vi.mock("../api/client", () => ({ api: { get: vi.fn() } }))
const mocked = api as unknown as Record<"get", ReturnType<typeof vi.fn>>

const part = (state: "ok" | "starting" | "failed") => ({ state, message: "" })
const STARTING = { ok: false, components: { display: part("ok"), "playlist-layer": part("starting"), "timer-layer": part("starting") } }
const RUNNING = { ok: true, components: { display: part("ok"), "playlist-layer": part("ok"), "timer-layer": part("ok") } }
const FAILED = { ok: false, components: { display: part("failed"), "playlist-layer": part("starting"), "timer-layer": part("starting") } }
const event = (seq: number, kind: string): TelemetryEvent => ({ seq, ts: "2026-10-25T10:00:00Z", source: "application", kind })
const settled = async () => { for(let i = 0; i < 4; i++) await Promise.resolve(); await nextTick() }

function fakeLink(status = "connecting") {
	const state = reactive({ status, events: [] as TelemetryEvent[], current: null as TelemetryEvent | null })
	return { state, link: { state } as unknown as TelemetryLink }
}

beforeEach(() => mocked.get.mockReset())

describe("the device's state", () => {
	it("is a failure when any part failed, running when all are up, else starting", () => {
		expect(deviceStateOf(FAILED)).toMatchObject({ state: "failed", severity: "danger", short: "Problem", label: "A part did not start" })
		expect(deviceStateOf(RUNNING)).toMatchObject({ state: "ok", severity: "success", short: "Running" })
		expect(deviceStateOf(STARTING)).toMatchObject({ state: "starting", short: "Starting" })
		expect(deviceStateOf(null).state).toBe("starting")
	})
})

describe("the header's indicator", () => {
	it("says the link's state until it is live, then the device's", async () => {
		mocked.get.mockResolvedValue(RUNNING)
		const { state, link } = fakeLink()
		const ds = useDeviceStatus({ link })
		expect([ds.shown.value.state, ds.shown.value.short]).toEqual(["connecting", "Connecting"])
		expect(mocked.get).not.toHaveBeenCalled()
		state.status = "live"
		await settled()
		expect(mocked.get).toHaveBeenCalledWith("/api/status")
		expect([ds.shown.value.state, ds.shown.value.short]).toEqual(["ok", "Running"])
		state.status = "offline"
		await settled()
		expect([ds.shown.value.state, ds.shown.value.short]).toEqual(["offline", "Offline"])
	})

	it("asks again when the start says a part came up or failed, and on nothing else", async () => {
		mocked.get.mockResolvedValueOnce(STARTING).mockResolvedValueOnce(RUNNING).mockResolvedValueOnce(FAILED)
		const { state, link } = fakeLink("live")
		const ds = useDeviceStatus({ link })
		await settled()
		expect(ds.shown.value.short).toBe("Starting")
		state.events = [event(1, "shown")]
		await settled()
		expect(mocked.get).toHaveBeenCalledTimes(1)
		state.events = [event(2, "configured"), ...state.events]
		await settled()
		expect(ds.shown.value.short).toBe("Running")
		state.events = [event(3, "configure-failed"), ...state.events]
		await settled()
		expect([mocked.get.mock.calls.length, ds.shown.value.short]).toEqual([3, "Problem"])
	})

	it("keeps what it knew when the status cannot be read", async () => {
		mocked.get.mockResolvedValueOnce(RUNNING).mockRejectedValueOnce(new Error("offline"))
		const { state, link } = fakeLink("live")
		const ds = useDeviceStatus({ link })
		await settled()
		state.events = [event(1, "configured")]
		await settled()
		expect(ds.shown.value.short).toBe("Running")
	})
})
