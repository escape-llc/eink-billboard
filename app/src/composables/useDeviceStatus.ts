/**
 * The device's state for every page (#520): the header's indicator says whether the device is running, starting, or has a part that did not start, and
 * whether the page can reach it at all (the telemetry link). The System page's Device card says the same in more words (`deviceStateOf`).
 *
 * It asks `GET /api/status` when the link comes up (and again when it comes back), and when the Application says a part of the start happened
 * (`configured`, `configure-failed`): never on a timer.
 */
import { computed, ref, watch } from "vue"
import { api } from "../api/client"
import type { components } from "../api/schema"
import { useTelemetry, type TelemetryLink } from "../components/TelemetryLink"

type Status = components["schemas"]["Status"]
export type DeviceState = "ok" | "starting" | "failed"
export type Severity = "success" | "secondary" | "danger" | "info" | "warn"

/** What a status says: its state, the colour of its tag and its words (`label` on the System page, `short` in the header). */
export function deviceStateOf(status: Status | null | undefined): { state: DeviceState, severity: Severity, label: string, short: string } {
	if (Object.values(status?.components ?? {}).some(c => c.state === "failed")) return { state: "failed", severity: "danger", label: "A part did not start", short: "Problem" }
	if (status?.ok) return { state: "ok", severity: "success", label: "Running", short: "Running" }
	return { state: "starting", severity: "secondary", label: "Starting", short: "Starting" }
}

/** The link's own state, when it is not live: the page cannot hear from the device. */
export const LINK_WORDS = {
	live: { label: "Live", severity: "success" },
	connecting: { label: "Connecting", severity: "info" },
	offline: { label: "Offline", severity: "warn" },
	"signed-out": { label: "Sign in", severity: "danger" },
} as const

/** The events of the start that change the status (`GET /api/status`). */
export const STARTUP_KINDS = ["configured", "configure-failed"]

export interface DeviceStatusOptions {
	link?: TelemetryLink
}

export function useDeviceStatus(options: DeviceStatusOptions = {}) {
	const link = options.link ?? useTelemetry()
	const status = ref<Status | null>(null)

	const device = computed(() => deviceStateOf(status.value))
	/** what the header shows: the link's state while it is not live (what the device said last is not news), else the device's */
	const shown = computed(() => {
		const words = LINK_WORDS[link.state.status]
		if (link.state.status !== "live") return { state: link.state.status, severity: words.severity as Severity, short: words.label, title: `The page cannot hear from the device: ${words.label.toLowerCase()}.` }
		return { state: device.value.state, severity: device.value.severity, short: device.value.short, title: `The device: ${device.value.label.toLowerCase()}. Open the System page for more.` }
	})

	async function load(): Promise<void> {
		try {
			status.value = await api.get("/api/status")
		}
		catch {
			// the link says when the device cannot be reached; a status that could not be read keeps the last one
		}
	}

	watch(() => link.state.status, state => { if (state === "live") void load() }, { immediate: true })
	watch(() => link.state.events[0], e => { if (e && STARTUP_KINDS.includes(e.kind)) void load() })

	return { status, device, shown, load }
}
