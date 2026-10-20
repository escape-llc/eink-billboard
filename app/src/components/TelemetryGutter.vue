<template>
	<aside class="gutter" aria-label="Device activity">
		<div class="gutter-head">
			<strong>Activity</strong>
			<Tag :severity="statusSeverity" :value="statusText" class="ml-auto" data-testid="link-status" />
		</div>

		<!-- the playlist's transport: stop (or play, when stopped) and next; the timer tasks keep running. The button follows the layer's own events -->
		<div class="gutter-transport" role="group" aria-label="Playback">
			<Button size="small" severity="secondary" outlined type="button" data-testid="play-stop"
				:icon="transport.state.stopped ? 'pi pi-play' : 'pi pi-stop'"
				:aria-label="transport.state.stopped ? 'Play' : 'Stop playback'" :title="transport.state.stopped ? 'Play' : 'Stop playback'"
				:data-state="transport.state.stopped ? 'stopped' : 'playing'" :disabled="transport.state.busy"
				@click="press(transport.state.stopped ? 'play' : 'stop')" />
			<Button size="small" severity="secondary" outlined type="button" icon="pi pi-step-forward" aria-label="Next track" title="Next track"
				data-testid="next-track" :disabled="transport.state.busy" @click="press('next')" />
		</div>

		<!-- a media player: the picture, its title and the time it was sent, and one line per layer (its glyph, then the track or task that made it) -->
		<section v-if="current" class="gutter-now" aria-label="Now showing">
			<button type="button" class="gutter-thumb" :aria-label="`Show ${title(current)} full size`" @click="full = current">
				<img :src="link.imageUrl(current.values?.digest)" :alt="title(current)" />
			</button>
			<div class="gutter-player">
				<div class="gutter-player-head">
					<span class="gutter-title">{{ title(current) }}</span>
					<span class="gutter-clock">{{ clockOf(current.ts) }}</span>
				</div>
				<ul v-if="currentLayers.length" class="gutter-layers" aria-label="Layers" data-testid="layers">
					<li v-for="(line, i) in currentLayers" :key="i" :data-layer="line.layer">
						<i :class="LAYERS[line.layer].glyph" role="img" :aria-label="LAYERS[line.layer].name" :title="LAYERS[line.layer].name"></i>
						<span class="gutter-layer-text">{{ line.text }}</span>
					</li>
				</ul>
			</div>
		</section>

		<section v-if="recent.length > 1" class="gutter-recent" aria-label="Recently shown">
			<div class="gutter-label">Recently shown</div>
			<div class="gutter-strip">
				<button v-for="e in recent.slice(1)" :key="e.seq" type="button" class="gutter-mini" :title="`${clockOf(e.ts)} ${title(e)}`"
					:aria-label="`Show ${title(e)} full size`" @click="full = e">
					<img :src="link.imageUrl(e.values?.digest)" :alt="title(e)" />
				</button>
			</div>
		</section>

		<section class="gutter-events" aria-label="Events">
			<div class="gutter-filters">
				<Select v-model="source" :options="sources" optionLabel="label" optionValue="value" size="small" aria-label="Source" />
				<label class="gutter-toggle"><ToggleSwitch v-model="problemsOnly" aria-label="Problems only" /> Problems only</label>
			</div>
			<ol class="gutter-list">
				<li v-for="(e, i) in shownEvents" :key="e.seq ?? `x${i}`" class="gutter-event" :class="{ problem: isProblem(e) }">
					<span class="gutter-time">{{ clockOf(e.ts) }}</span>
					<i :class="iconOf(e)" :title="e.source" aria-hidden="true"></i>
					<span class="gutter-text">{{ describe(e) }}<code v-if="e.detail" class="gutter-detail">{{ e.detail }}</code></span>
				</li>
				<li v-if="shownEvents.length === 0" class="gutter-empty">Nothing yet.</li>
			</ol>
		</section>

		<Dialog :visible="full !== null" modal :header="full ? title(full) : ''" @update:visible="v => { if (!v) full = null }" style="max-width:95vw">
			<img v-if="full" class="gutter-full" :src="link.imageUrl(full.values?.digest, 'full')" :alt="title(full)" />
		</Dialog>
	</aside>
</template>
<script setup lang="ts">
/** The live view of the device: what the panel shows, what it showed, and what the tasks report (the telemetry link). */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { Button, Dialog, Select, Tag, ToggleSwitch, useToast } from "primevue"
import { LAYERS, clockOf, isProblem, layerOf, layersOf, useTelemetry, type TelemetryEvent } from "./TelemetryLink"
import { useTransport, type TransportCommand } from "./Transport"

const link = useTelemetry()
const transport = useTransport()
const toast = useToast()
// the state when the link comes up (and again when it comes back), then the layer's own events keep it right
watch(() => link.state.status, status => { if (status === "live") void transport.load() }, { immediate: true })
watch(() => link.state.events[0], () => transport.follow(link.state.events))
async function press(command: TransportCommand): Promise<void> {
	try {
		await transport.send(command)
	} catch (ex: any) {
		toast.add({ severity: "error", summary: "Playback", detail: ex?.message || "The command was not accepted.", life: 5000 })
	}
}
const full = ref<TelemetryEvent | null>(null)
const source = ref<string>("all")
const problemsOnly = ref(false)
const sources = [
	{ label: "Everything", value: "all" },
	{ label: "Playlist", value: "playlist_layer" },
	{ label: "Timer tasks", value: "timer_layer" },
	{ label: "Display", value: "display" },
	{ label: "Data sources", value: "data-source" },
	{ label: "Settings", value: "application" },
]
onMounted(() => link.start())
onBeforeUnmount(() => link.stop())

const current = computed(() => link.state.current?.values?.digest ? link.state.current : null)
const currentLayers = computed(() => layersOf(current.value))
const recent = computed(() => {
	const seen = new Set<string>()
	return [current.value, ...link.state.events.filter(e => e.kind === "shown")]
		.filter((e): e is TelemetryEvent => !!e && !!e.values?.digest && !seen.has(e.values.digest) && !!seen.add(e.values.digest))
		.slice(0, 7)
})
const shownEvents = computed(() => link.state.events.filter(e =>
	(source.value === "all" || e.source === source.value) && (!problemsOnly.value || isProblem(e))))

const statusText = computed(() => ({ live: "Live", connecting: "Connecting", offline: "Offline", "signed-out": "Sign in" })[link.state.status])
const statusSeverity = computed(() => ({ live: "success", connecting: "info", offline: "warn", "signed-out": "danger" })[link.state.status])

const title = (e: TelemetryEvent): string => String(e.values?.title ?? "")
function iconOf(e: TelemetryEvent): string {
	// what was sent to the panel: a screen, which no layer's glyph is (they are a picture, a stack and a page); Material, as PrimeIcons has none like it
	if (e.kind === "shown") return "mi mi-screenshot-monitor"
	// the first and last markers of a slot, not "play"
	if (e.kind === "track-started" || e.kind === "task-started") return "pi pi-step-backward-alt"
	if (e.kind === "track-ended" || e.kind === "task-ended") return "pi pi-step-forward-alt"
	if (e.kind === "stopped") return "pi pi-stop"
	if (e.kind === "transport") return e.values?.state === "halted" ? "pi pi-stop" : "pi pi-play"
	// a page is shown on a layer: the layer's own glyph, as in Now showing
	if (e.kind === "showing") return LAYERS[layerOf(e.values?.layer)].glyph
	return { playlist_layer: "pi pi-play", timer_layer: "pi pi-clock", display: "pi pi-image", "data-source": "pi pi-database", application: "pi pi-cog", telemetry: "pi pi-wifi" }[e.source] ?? "pi pi-circle"
}
/** Our own words for an event: its message when it has one, else what its values say. */
function describe(e: TelemetryEvent): string {
	if (e.message) return e.message
	const v = e.values ?? {}
	switch (e.kind) {
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
</script>
<style scoped>
.gutter {
	display: flex;
	flex-direction: column;
	gap: .75rem;
	width: 20rem;
	flex: none;
	min-height: 0;
	padding: .5rem;
	overflow-y: auto;
	border-radius: var(--p-toolbar-border-radius);
	border: solid 1px var(--p-toolbar-border-color);
	/* the panel's own surface, as the other panels have: it follows the theme and dark mode */
	background: var(--p-content-background);
}
.gutter-head {
	display: flex;
	align-items: center;
	gap: .5rem;
}
.gutter-transport {
	display: flex;
	gap: .5rem;
}
.gutter-label {
	font-size: .8rem;
	font-weight: bold;
	text-transform: uppercase;
	letter-spacing: .04rem;
	opacity: .7;
	margin-bottom: .25rem;
}
.gutter-thumb, .gutter-mini {
	padding: 0;
	border: 1px solid var(--p-content-border-color);
	background: none;
	cursor: zoom-in;
	display: block;
}
.gutter-thumb img {
	display: block;
	width: 100%;
}
.gutter-now {
	border: 1px solid var(--p-content-border-color);
	border-radius: var(--p-content-border-radius);
	background: var(--p-content-background);
	overflow: hidden;
}
.gutter-now .gutter-thumb {
	width: 100%;
	border: none;
	border-bottom: 1px solid var(--p-content-border-color);
}
.gutter-player {
	padding: .4rem .5rem .5rem;
}
.gutter-player-head {
	display: flex;
	align-items: baseline;
	gap: .5rem;
}
.gutter-title {
	font-weight: bold;
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.gutter-clock {
	margin-left: auto;
	font-size: .8rem;
	font-variant-numeric: tabular-nums;
	color: var(--p-text-muted-color);
}
.gutter-layers {
	list-style: none;
	margin: .25rem 0 0;
	padding: 0;
	display: flex;
	flex-direction: column;
	gap: .2rem;
	font-size: .85rem;
}
.gutter-layers li {
	display: flex;
	align-items: center;
	gap: .4rem;
	min-width: 0;
}
.gutter-layers i {
	color: var(--p-text-muted-color);
}
.gutter-layer-text {
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.gutter-strip {
	display: grid;
	grid-template-columns: repeat(3, 1fr);
	gap: .25rem;
}
.gutter-mini img {
	display: block;
	width: 100%;
}
.gutter-filters {
	display: flex;
	align-items: center;
	gap: .5rem;
	flex-wrap: wrap;
	margin-bottom: .25rem;
}
.gutter-toggle {
	display: flex;
	align-items: center;
	gap: .35rem;
	font-size: .85rem;
}
/* the events take what the thumbnails leave and scroll inside it; the whole gutter scrolls only in a window too short for even a few of them */
.gutter-events {
	display: flex;
	flex-direction: column;
	flex: 1 1 0;
	min-height: 10rem;
}
.gutter-list {
	list-style: none;
	margin: 0;
	padding: 0;
	font-size: .85rem;
	flex: 1 1 0;
	min-height: 0;
	overflow-y: auto;
}
.gutter-event {
	display: flex;
	gap: .4rem;
	align-items: baseline;
	padding: .2rem 0;
	border-bottom: 1px solid var(--p-content-border-color);
}
.gutter-event.problem {
	color: var(--p-red-500);
}
.gutter-time {
	font-variant-numeric: tabular-nums;
	opacity: .7;
	flex: none;
}
.gutter-detail {
	display: block;
	margin-top: .15rem;
	font-size: .75rem;
	white-space: pre-wrap;
	overflow-wrap: anywhere;
	opacity: .85;
}
.gutter-text {
	overflow-wrap: anywhere;
}
.gutter-empty {
	opacity: .7;
}
.gutter-full {
	max-width: 100%;
	display: block;
}
@media (max-width: 768px) {
	.gutter {
		width: auto;
		max-height: 40vh;
		flex: 0 0 auto;
	}
}
</style>
