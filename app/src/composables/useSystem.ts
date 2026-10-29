/**
 * The System page's data (#510 A6): the device's status and the machine's readings, asked again every few seconds, and the latest problems the
 * tasks reported. What the panel shows, the playlist's transport and the Activity panel are the panel's own (`usePanelNow`, #824), which Home shows too.
 * The page keeps its template and its dialogs, so this runs and is tested without a component.
 */
import { computed, ref } from "vue"
import { api } from "../api/client"
import type { components } from "../api/schema"
import { isProblem, useTelemetry, type TelemetryLink } from "../components/TelemetryLink"
import { deviceStateOf } from "./useDeviceStatus"

type Schemas = components["schemas"]
type Status = Schemas["Status"]
type SystemInfo = Schemas["SystemInfo"]
export type SystemOptions = {
	/** The telemetry link (the shared one unless a test gives its own). */
	link?: TelemetryLink
	/** The build this page's code is from ('dev' outside an image). */
	webCommit?: string
	/** How often the status and the readings are asked for again. */
	pollMs?: number
}

export function useSystem(options: SystemOptions = {}) {
	const link = options.link ?? useTelemetry()
	const webCommit = options.webCommit ?? __APP_COMMIT__
	const pollMs = options.pollMs ?? 10000

	const status = ref<Status | null>(null)
	const info = ref<SystemInfo | null>(null)
	const failed = ref(false)
	let timer: ReturnType<typeof setInterval> | undefined

	// the build this page's code is from, and the server's: they differ when the page was opened before an update (the server's is 'unknown' outside the container)
	const mismatch = computed(() => !!info.value && info.value.host.commit !== "unknown" && webCommit !== "dev" && info.value.host.commit !== webCommit)
	// the same words as the header's indicator (useDeviceStatus), the long ones
	const device = computed(() => deviceStateOf(status.value))
	const deviceState = computed(() => device.value.state)
	const deviceSeverity = computed(() => device.value.severity)
	const deviceLabel = computed(() => device.value.label)
	const owners = computed(() => info.value ? [
		{ title: "Data sources", items: info.value.storage.datasources },
		{ title: "Plugins", items: info.value.storage.plugins },
	] : [])
	// the latest few things that went wrong, at the top where they are seen
	const problems = computed(() => link.state.events.filter(isProblem).slice(0, 5))

	/** Ask for the status and the readings; answers when the status has been answered (the readings may come later). */
	function load(): Promise<unknown> {
		const asked = api.get("/api/status").then(s => { status.value = s }).catch(() => {})
		api.get("/api/system").then(s => { info.value = s; failed.value = false }).catch(() => { failed.value = true })
		return asked
	}
	/**
	 * The page is shown: load, then make sure the link is open once the first request is answered (on a device that asks for a sign-in, that is after it:
	 * a WebSocket cannot ask, it is refused), and keep asking. The link is the app's (App.vue opens it too): leaving the page leaves it open.
	 */
	function start() {
		void load().finally(() => link.start())
		timer = setInterval(load, pollMs)
	}
	function stop() {
		if(timer) clearInterval(timer)
		timer = undefined
	}

	return {
		status, info, failed,
		mismatch, deviceState, deviceSeverity, deviceLabel, owners, problems,
		load, start, stop,
	}
}
