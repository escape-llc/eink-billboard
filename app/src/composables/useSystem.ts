/**
 * The System page's data (#510 A6): the device's status and the machine's readings (asked again every few seconds), the playlist's transport,
 * and what the tasks report over the telemetry link, filtered as the page shows it. The page keeps its template, its dialogs and the toasts;
 * what goes wrong with a command is told through `notify`, so this runs and is tested without a component.
 */
import { computed, ref, watch } from "vue"
import { api } from "../api/client"
import type { components } from "../api/schema"
import { LAYERS, isProblem, layerOf, layersOf, useTelemetry, type TelemetryEvent, type TelemetryLink } from "../components/TelemetryLink"
import { useTransport, type Transport, type TransportCommand } from "../components/Transport"
import { LINK_WORDS, deviceStateOf } from "./useDeviceStatus"

type Schemas = components["schemas"]
type Status = Schemas["Status"]
type SystemInfo = Schemas["SystemInfo"]
export type Notify = (detail: string) => void
export type SystemOptions = {
	/** The telemetry link and the transport (the shared ones unless a test gives its own). */
	link?: TelemetryLink
	transport?: Transport
	/** The build this page's code is from ('dev' outside an image). */
	webCommit?: string
	/** How often the status and the readings are asked for again. */
	pollMs?: number
}

/** The event sources the Activity panel can be narrowed to. */
export const SOURCES = [
	{ label: "Everything", value: "all" },
	{ label: "Playlist", value: "playlist_layer" },
	{ label: "Timer tasks", value: "timer_layer" },
	{ label: "Display", value: "display" },
	{ label: "Data sources", value: "data-source" },
	{ label: "Settings", value: "application" },
]

/** The glyph of an event in the Activity panel. */
export function eventIcon(e: TelemetryEvent): string {
	// what was sent to the panel: a screen, which no layer's glyph is (they are a picture, a stack and a page)
	if(e.kind === "shown") return "mi mi-screenshot-monitor"
	// the first and last markers of a slot, not "play"
	if(e.kind === "track-started" || e.kind === "task-started") return "mi mi-play-circle"
	if(e.kind === "track-ended" || e.kind === "task-ended") return "mi mi-stop-circle"
	if(e.kind === "stopped") return "mi mi-stop"
	if(e.kind === "transport") return e.values?.state === "halted" ? "mi mi-stop" : "mi mi-play-arrow"
	// a page is shown on a layer: the layer's own glyph, as in Now showing
	if(e.kind === "showing") return LAYERS[layerOf(e.values?.layer)].glyph
	return ({ playlist_layer: "mi mi-play-arrow", timer_layer: "mi mi-schedule", display: "mi mi-image", "data-source": "mi mi-database", application: "mi mi-settings", telemetry: "mi mi-wifi" } as Record<string, string>)[e.source] ?? "mi mi-circle"
}
/** Our own words for an event: its message when it has one, else what its values say. */
export function describeEvent(e: TelemetryEvent): string {
	if(e.message) return e.message
	const v = e.values ?? {}
	switch(e.kind) {
		case "track-started": return `Track started: '${v.current_track ?? "a track"}'`
		case "track-ended": return `Track ended: '${v.current_track ?? "a track"}'`
		case "task-started": return `Task started: '${v.current_track ?? "a task"}'`
		case "task-ended": return `Task ended: '${v.current_track ?? "a task"}'`
		case "showing": return `On deck: '${v.title ?? ""}'`
		case "waiting": return `Waiting ${Math.round(Number(v.delta ?? 0) / 60)} min for the next timer task`
		case "shown": return `Sent to panel: '${v.title ?? ""}'`
		case "stopped": return "The playlist stopped"
		case "faulted": return "Every track failed: playback is stopped"
		default: return e.kind
	}
}

export function useSystem(notify: Notify, options: SystemOptions = {}) {
	const link = options.link ?? useTelemetry()
	const transport = options.transport ?? useTransport()
	const webCommit = options.webCommit ?? __APP_COMMIT__
	const pollMs = options.pollMs ?? 10000

	const status = ref<Status | null>(null)
	const info = ref<SystemInfo | null>(null)
	const failed = ref(false)
	// the Activity panel's filters
	const source = ref<string>("all")
	const problemsOnly = ref(false)
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

	const current = computed(() => link.state.current?.values?.digest ? link.state.current : null)
	const currentLayers = computed(() => layersOf(current.value))
	/** What the panel showed lately, newest first, each picture once. */
	const recent = computed(() => {
		const seen = new Set<string>()
		return [current.value, ...link.state.events.filter(e => e.kind === "shown")]
			.filter((e): e is TelemetryEvent => !!e && !!e.values?.digest && !seen.has(e.values.digest) && !!seen.add(e.values.digest))
			.slice(0, 7)
	})
	const shownEvents = computed(() => link.state.events.filter(e =>
		(source.value === "all" || e.source === source.value) && (!problemsOnly.value || isProblem(e))))
	// the latest few things that went wrong, at the top where they are seen
	const problems = computed(() => link.state.events.filter(isProblem).slice(0, 5))
	const statusText = computed(() => LINK_WORDS[link.state.status].label)
	const statusSeverity = computed(() => LINK_WORDS[link.state.status].severity)

	// the transport's state when the link comes up (and again when it comes back), then the layer's own events keep it right
	watch(() => link.state.status, state => { if(state === "live") void transport.load() }, { immediate: true })
	watch(() => link.state.events[0], () => transport.follow(link.state.events))

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
	async function press(command: TransportCommand): Promise<void> {
		try {
			await transport.send(command)
		}
		catch(ex: any) {
			notify(ex?.message || "The command was not accepted.")
		}
	}

	return {
		link, transport, status, info, failed, source, problemsOnly,
		mismatch, deviceState, deviceSeverity, deviceLabel, owners,
		current, currentLayers, recent, shownEvents, problems, statusText, statusSeverity,
		load, start, stop, press,
	}
}
