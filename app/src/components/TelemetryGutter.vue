<template>
	<aside class="gutter" aria-label="Device activity">
		<div class="gutter-head">
			<strong>Activity</strong>
			<Tag :severity="statusSeverity" :value="statusText" class="ml-auto" data-testid="link-status" />
		</div>

		<section v-if="current" class="gutter-now" aria-label="Now showing">
			<div class="gutter-label">Now showing</div>
			<button type="button" class="gutter-thumb" :aria-label="`Show ${title(current)} full size`" @click="full = current">
				<img :src="link.imageUrl(current.values?.digest)" :alt="title(current)" />
			</button>
			<div class="gutter-title">{{ title(current) }}</div>
			<div class="gutter-meta">
				<span>{{ clockOf(current.ts) }}</span>
				<Tag v-for="(layer, i) in current.values?.layers ?? []" :key="i" severity="secondary" class="gutter-chip"
					:value="layer.layer === 'overlays' ? `overlays (${layer.count})` : layer.layer" />
			</div>
			<ul v-if="currentOrigins.length" class="gutter-origins" aria-label="Made by" data-testid="origins">
				<li v-for="(line, i) in currentOrigins" :key="i">
					<MaterialIcon :name="line.kind === 'timer' ? 'schedule' : 'playlist_play'" />
					<span class="gutter-origin-layer">{{ line.layer }}</span> {{ line.text }}
				</li>
			</ul>
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
					<MaterialIcon v-if="materialOf(e)" :name="materialOf(e)!" class="gutter-glyph" :title="e.source" />
					<i v-else :class="iconOf(e)" :title="e.source" aria-hidden="true"></i>
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
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Dialog, Select, Tag, ToggleSwitch } from "primevue"
import MaterialIcon from "./MaterialIcon.vue"
import type { MaterialIconName } from "./MaterialIcons"
import { clockOf, isProblem, originsOf, useTelemetry, type TelemetryEvent } from "./TelemetryLink"

const link = useTelemetry()
const full = ref<TelemetryEvent | null>(null)
const source = ref<string>("all")
const problemsOnly = ref(false)
const sources = [
	{ label: "Everything", value: "all" },
	{ label: "Playlist", value: "playlist_layer" },
	{ label: "Timer tasks", value: "timer_layer" },
	{ label: "Display", value: "display" },
	{ label: "Settings", value: "application" },
]
onMounted(() => link.start())
onBeforeUnmount(() => link.stop())

const current = computed(() => link.state.current?.values?.digest ? link.state.current : null)
const currentOrigins = computed(() => originsOf(current.value))
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
/** The events whose glyph is a Material Symbol (PrimeIcons has none like it); the rest use PrimeIcons (`iconOf`). */
function materialOf(e: TelemetryEvent): MaterialIconName | null {
	// what was sent to the panel: a screen, which no layer's glyph is (they are a picture, a stack and a page)
	return e.kind === "shown" ? "screenshot_monitor" : null
}
function iconOf(e: TelemetryEvent): string {
	// the first and last markers of a slot, not "play"
	if (e.kind === "track-started" || e.kind === "task-started") return "pi pi-step-backward-alt"
	if (e.kind === "track-ended" || e.kind === "task-ended") return "pi pi-step-forward-alt"
	if (e.kind === "stopped") return "pi pi-stop"
	// a page is shown on a layer: a picture is a background, a washed one is a blend, a text page covers everything (a document)
	if (e.kind === "showing") return { background: "pi pi-image", blend: "pi pi-clone", override: "pi pi-file" }[String(e.values?.layer)] ?? "pi pi-image"
	return { playlist_layer: "pi pi-play", timer_layer: "pi pi-clock", display: "pi pi-image", application: "pi pi-cog", telemetry: "pi pi-wifi" }[e.source] ?? "pi pi-circle"
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
}
.gutter-head {
	display: flex;
	align-items: center;
	gap: .5rem;
}
.gutter-label {
	font-size: .8rem;
	font-weight: bold;
	text-transform: uppercase;
	letter-spacing: .05em;
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
.gutter-title {
	font-weight: bold;
	margin-top: .25rem;
}
.gutter-meta {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: .25rem;
	font-size: .85rem;
}
.gutter-origins {
	list-style: none;
	margin: .25rem 0 0;
	padding: 0;
	display: flex;
	flex-direction: column;
	gap: .15rem;
	font-size: .85em;
}
.gutter-origins .material-icon {
	margin-right: .3rem;
	color: var(--p-text-muted-color);
}
.gutter-origin-layer {
	color: var(--p-text-muted-color);
	margin-right: .25rem;
}
.gutter-chip {
	font-size: .7rem;
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
.gutter-glyph {
	font-size: 1.2em;
	flex: none;
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
