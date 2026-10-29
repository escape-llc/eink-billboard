/**
 * What the panel shows and what the device is doing, live from the telemetry link (#824): the playlist's transport, Now showing, Recently shown and the
 * Activity panel's events, as the System page's right column and Home both show them, and the one line Home sums the activity up in.
 * What goes wrong with a command is told through `notify`, so this runs and is tested without a component.
 */
import { computed, ref, watch } from "vue"
import { LAYERS, isProblem, layerOf, layersOf, useTelemetry, type TelemetryEvent, type TelemetryLink } from "../components/TelemetryLink"
import { useTransport, type Transport, type TransportCommand } from "../components/Transport"
import { LINK_WORDS } from "./useDeviceStatus"
import { useRecentlyShown } from "./useRecentlyShown"

export type Notify = (detail: string) => void
export type PanelOptions = {
	/** The telemetry link and the transport (the shared ones unless a test gives its own). */
	link?: TelemetryLink
	transport?: Transport
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

/** How long a problem stays the latest activity, over anything routine that came after it. */
export const PROBLEM_WINDOW_MS = 60 * 60 * 1000

/**
 * The one event Home sums the activity up in: a problem from the last hour, else the latest routine event (the link's own messages left out),
 * else none. `events` are the link's, newest first.
 */
export function latestActivity(events: TelemetryEvent[], now: number): { event: TelemetryEvent, problem: boolean } | null {
	const problem = events.find(e => isProblem(e) && now - Date.parse(e.ts ?? "") <= PROBLEM_WINDOW_MS)
	if(problem) return { event: problem, problem: true }
	const routine = events.find(e => !isProblem(e) && e.source !== "telemetry")
	return routine ? { event: routine, problem: false } : null
}

/**
 * How long ago `ts` was, in words ("just now", "2 min ago", "3 h ago", "2 d ago"); empty when it is not a time. It is only right when it is
 * worked out again as time passes: whoever shows it re-computes it on a timer.
 */
export function relativeTime(ts: string | undefined, now: number): string {
	const at = Date.parse(ts ?? "")
	if(Number.isNaN(at)) return ""
	const minutes = Math.floor((now - at) / 60000)
	if(minutes < 1) return "just now"
	if(minutes < 60) return `${minutes} min ago`
	const hours = Math.floor(minutes / 60)
	if(hours < 24) return `${hours} h ago`
	return `${Math.floor(hours / 24)} d ago`
}

export function usePanelNow(notify: Notify, options: PanelOptions = {}) {
	const link = options.link ?? useTelemetry()
	const transport = options.transport ?? useTransport()
	// the Activity panel's filters
	const source = ref<string>("all")
	const problemsOnly = ref(false)

	// what the panel shows and showed lately, as the Gallery page's Recently shown tab has it
	const { current, recent } = useRecentlyShown(link)
	const currentLayers = computed(() => layersOf(current.value))
	const shownEvents = computed(() => link.state.events.filter(e =>
		(source.value === "all" || e.source === source.value) && (!problemsOnly.value || isProblem(e))))
	const statusText = computed(() => LINK_WORDS[link.state.status].label)
	const statusSeverity = computed(() => LINK_WORDS[link.state.status].severity)

	// the transport's state when the link comes up (and again when it comes back), then the layer's own events keep it right
	watch(() => link.state.status, state => { if(state === "live") void transport.load() }, { immediate: true })
	watch(() => link.state.events[0], () => transport.follow(link.state.events))

	async function press(command: TransportCommand): Promise<void> {
		try {
			await transport.send(command)
		}
		catch(ex: any) {
			notify(ex?.message || "The command was not accepted.")
		}
	}

	return {
		link, transport, source, problemsOnly,
		current, currentLayers, recent, shownEvents, statusText, statusSeverity,
		press,
	}
}
