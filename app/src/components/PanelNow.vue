<template>
	<!-- what the device is doing now, and what it did: the telemetry link (#824: the System page's right column, and Home) -->
	<div class="panel-now" :data-link="link.state.status">
		<!-- the playlist the layer is on, its tracks in order and the one playing, with play, stop and next (usePlaylistPanel) -->
		<SystemCard title="Playlist">
			<template #head><!-- what the layer last said is not news while the link is down: the tag then says that, as the header does -->
				<Tag v-if="link.state.status !== 'live'" :severity="statusSeverity" :value="statusText" class="ml-auto" :title="`The page cannot hear from the device: ${statusText.toLowerCase()}.`" data-testid="playback-state" />
				<Tag v-else :severity="transport.state.stopped ? 'warn' : 'success'" :value="transport.state.stopped ? 'Stopped' : 'Playing'" class="ml-auto" data-testid="playback-state" /></template>
			<div class="playlist-head">
				<InputGroup class="system-actions" role="group" aria-label="Playback">
					<Button size="small" severity="secondary" type="button" data-testid="play-stop"
						:icon="transport.state.stopped ? 'mi mi-play-arrow' : 'mi mi-stop'"
						:aria-label="transport.state.stopped ? 'Play' : 'Stop playback'" :title="transport.state.stopped ? 'Play' : 'Stop playback'"
						:data-state="transport.state.stopped ? 'stopped' : 'playing'" :disabled="transport.state.busy"
						@click="press(transport.state.stopped ? 'play' : 'stop')" />
					<Button size="small" severity="secondary" type="button" icon="mi mi-skip-next" aria-label="Next track" title="Next track"
						data-testid="next-track" :disabled="transport.state.busy" @click="press('next')" />
				</InputGroup>
				<span v-if="playlist" class="playlist-name" data-testid="playlist-name">{{ playlist.name }}</span>
			</div>
			<ol v-if="playlist && tracks.length" class="track-strip" aria-label="Tracks" data-testid="track-strip">
				<li v-for="(t, i) in tracks" :key="t.id" :aria-current="i === playing ? 'true' : undefined" :class="{ playing: i === playing }" :title="t.title">
					<i v-if="i === playing" class="mi mi-play-arrow" aria-hidden="true"></i><span class="track-title">{{ t.title }}</span>
				</li>
			</ol>
			<p v-else class="muted">{{ !loaded ? "Loading." : playlists.length === 0 ? "No playlist yet: make one on the Playlist page." : playlist ? "This playlist has no tracks." : "Nothing has played yet." }}</p>
		</SystemCard>

		<!-- a media player: the picture, its title and the time it was sent, and one line per layer (its glyph, then the track or task that made it) -->
		<SystemCard title="Now showing">
			<template #head><Tag v-if="link.state.status !== 'live'" :severity="statusSeverity" :value="statusText" class="ml-auto" data-testid="link-status" /></template>
			<div v-if="current" class="now">
				<button type="button" class="thumb" :aria-label="`Show ${title(current)} full size`" @click="full = current">
					<!-- the panel's own pixels: the card is wider than the 320 pixel thumbnail, which the browser blurred when it enlarged it -->
					<img :src="link.imageUrl(current.values?.digest, 'full')" :alt="title(current)" />
				</button>
				<div class="player">
					<div class="player-head">
						<span class="title">{{ title(current) }}</span>
						<span class="clock">{{ clockOf(current.ts) }}</span>
						<Button size="small" text type="button" icon="mi mi-add-photo-alternate" aria-label="Save to Gallery" :title="hasOriginal(current) ? 'Save the picture this page was made from to the Gallery' : 'Save to the Gallery, as it was shown'"
							class="save" data-testid="save-current" :disabled="saving" @click="saveShown(current)" />
					</div>
					<ul v-if="currentLayers.length" class="layers" aria-label="Layers" data-testid="layers">
						<li v-for="(line, i) in currentLayers" :key="i" :data-layer="line.layer">
							<i :class="LAYERS[line.layer].glyph" role="img" :aria-label="LAYERS[line.layer].name" :title="LAYERS[line.layer].name"></i>
							<span class="layer-text">{{ line.text }}</span>
						</li>
					</ul>
				</div>
			</div>
			<p v-else class="muted">Nothing has been shown yet.</p>
		</SystemCard>

		<SystemCard title="Recently shown">
			<div v-if="recent.length > 1" class="strip">
				<button v-for="e in recent.slice(1)" :key="e.seq" type="button" class="mini" :title="`${clockOf(e.ts)} ${title(e)}`"
					:aria-label="`Show ${title(e)} full size`" @click="full = e">
					<img :src="link.imageUrl(e.values?.digest)" :alt="title(e)" />
				</button>
			</div>
			<p v-else class="muted">Nothing else has been shown yet.</p>
		</SystemCard>

		<SystemCard v-if="activity" ref="activityCard" title="Activity" data-testid="activity">
			<div class="filters">
				<Select v-model="source" :options="sources" optionLabel="label" optionValue="value" size="small" aria-label="Source" />
				<label class="toggle"><ToggleSwitch v-model="problemsOnly" aria-label="Problems only" /> Problems only</label>
			</div>
			<ol class="event-list">
				<li v-for="(e, i) in shownEvents" :key="e.seq ?? `x${i}`" class="event" :class="{ problem: isProblem(e) }">
					<span class="time">{{ clockOf(e.ts) }}</span>
					<i :class="iconOf(e)" :title="e.source" aria-hidden="true"></i>
					<span class="text">{{ describe(e) }}<code v-if="e.detail" class="detail">{{ e.detail }}</code></span>
				</li>
				<li v-if="shownEvents.length === 0" class="muted">Nothing yet.</li>
			</ol>
		</SystemCard>

	<Dialog :visible="full !== null" modal :header="full ? title(full) : ''" @update:visible="v => { if (!v) full = null }" style="max-width:95vw">
		<img v-if="full" class="full" :src="link.imageUrl(full.values?.digest, 'full')" :alt="title(full)" />
		<template #footer>
			<template v-if="full">
				<Button v-if="hasOriginal(full)" size="small" severity="secondary" type="button" label="Save as shown" title="Save the panel's picture, with its overlays" :disabled="saving" data-testid="save-as-shown" @click="saveShown(full, true)" />
				<Button size="small" type="button" icon="mi mi-add-photo-alternate" :label="hasOriginal(full) ? 'Save original' : 'Save to Gallery'"
					:title="hasOriginal(full) ? 'Save the picture this page was made from' : 'Save the picture as it was shown'" :disabled="saving" data-testid="save-full" @click="saveShown(full)" />
			</template>
		</template>
	</Dialog>
	</div>
</template>
<script setup lang="ts">
/**
 * What the panel shows and what the device is doing (#824): the playlist with play, stop and next, Now showing with its layers, Recently shown and,
 * unless `activity` is false (Home leaves it out), the Activity panel. The System page shows it as its right column and Home as the page.
 * `focus` opens the Activity panel narrowed to problems ("problems") or not ("all") and brings it into view: Home's activity line links here so.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { Button, Dialog, InputGroup, Select, Tag, ToggleSwitch, useToast } from "primevue"
import { LAYERS, clockOf, isProblem, type TelemetryEvent } from "./TelemetryLink"
import SystemCard from "./SystemCard.vue"
import { usePlaylistPanel } from "../composables/usePlaylistPanel"
import { hasOriginal, useSaveShown } from "../composables/useGallery"
import { SOURCES as sources, describeEvent as describe, eventIcon as iconOf, usePanelNow } from "../composables/usePanelNow"

const props = withDefaults(defineProps<{ activity?: boolean, focus?: "all" | "problems" | null }>(), { activity: true, focus: null })
const toast = useToast()
const { link, transport, source, problemsOnly, current, currentLayers, recent, shownEvents, statusText, statusSeverity, press } =
	usePanelNow(detail => toast.add({ severity: "error", summary: "Playback", detail, life: 5000 }))
const full = ref<TelemetryEvent | null>(null)
// "Save to Gallery" on what the panel shows and showed (#517)
const { busy: saving, saveShown } = useSaveShown((severity, detail) => toast.add({ severity, summary: "Gallery", detail, life: severity === "error" ? 6000 : 3000 }))
// the playlist panel follows the playlists while it is shown
const { playlists, loaded, playlist, tracks, playing, start: followPlaylists, stop: unfollowPlaylists } = usePlaylistPanel({ transport })
onMounted(() => followPlaylists())
onBeforeUnmount(() => unfollowPlaylists())

const activityCard = ref<InstanceType<typeof SystemCard> | null>(null)
watch(() => props.focus, async focus => {
	if(!focus) return
	source.value = "all"
	problemsOnly.value = focus === "problems"
	await nextTick()
	;(activityCard.value?.$el as HTMLElement | undefined)?.scrollIntoView({ block: "start" })
}, { immediate: true })

const title = (e: TelemetryEvent): string => String(e.values?.title ?? "")
</script>
<style scoped>
.muted {
	color: var(--p-text-muted-color);
	margin: 0;
}
.event.problem {
	color: var(--p-red-500);
}
.playlist-head {
	display: flex;
	align-items: center;
	gap: .5rem;
	min-width: 0;
}
.playlist-head .p-inputgroup {
	width: auto;
	flex: none;
}
.playlist-name {
	font-weight: bold;
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
/* the tracks in a row, in order, wrapping (never a sideways scroll: a phone is narrow) */
.track-strip {
	list-style: none;
	margin: 0;
	padding: 0;
	display: flex;
	flex-wrap: wrap;
	gap: .25rem;
	font-size: .85rem;
}
.track-strip li {
	display: inline-flex;
	align-items: center;
	gap: .2rem;
	max-width: 100%;
	padding: .15rem .45rem;
	border-radius: var(--p-content-border-radius);
	border: 1px solid var(--p-content-border-color);
}
.track-strip li.playing {
	background: var(--p-highlight-background);
	color: var(--p-highlight-color);
	border-color: var(--p-highlight-background);
	font-weight: bold;
}
.track-title {
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
/* the cards one under the other, as the System page's left column has them */
.panel-now {
	display: flex;
	flex-direction: column;
	gap: .75rem;
	min-width: 0;
}
.thumb, .mini {
	padding: 0;
	border: 1px solid var(--p-content-border-color);
	background: none;
	cursor: zoom-in;
	display: block;
}
.thumb img {
	display: block;
	width: 100%;
}
.now {
	border: 1px solid var(--p-content-border-color);
	border-radius: var(--p-content-border-radius);
	background: var(--p-content-background);
	overflow: hidden;
}
.now .thumb {
	width: 100%;
	border: none;
	border-bottom: 1px solid var(--p-content-border-color);
}
.player {
	padding: .4rem .5rem .5rem;
}
.player-head {
	display: flex;
	align-items: baseline;
	gap: .5rem;
}
.player-head .save {
	align-self: center;
	margin: -.25rem -.25rem -.25rem 0;
}
.title {
	font-weight: bold;
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.clock {
	margin-left: auto;
	font-size: .8rem;
	font-variant-numeric: tabular-nums;
	color: var(--p-text-muted-color);
}
.layers {
	list-style: none;
	margin: .25rem 0 0;
	padding: 0;
	display: flex;
	flex-direction: column;
	gap: .2rem;
	font-size: .85rem;
}
.layers li {
	display: flex;
	align-items: center;
	gap: .4rem;
	min-width: 0;
}
.layers i {
	color: var(--p-text-muted-color);
}
.layer-text {
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.strip {
	display: grid;
	grid-template-columns: repeat(3, 1fr);
	gap: .25rem;
}
.mini img {
	display: block;
	width: 100%;
}
.filters {
	display: flex;
	align-items: center;
	gap: .5rem;
	flex-wrap: wrap;
	margin-bottom: .25rem;
}
.toggle {
	display: flex;
	align-items: center;
	gap: .35rem;
	font-size: .85rem;
}
/* the events scroll inside their own box, so the page is not made as long as the ring of events is */
.event-list {
	list-style: none;
	margin: 0;
	padding: 0;
	font-size: .85rem;
	max-height: 36rem;
	overflow-y: auto;
}
.event {
	display: flex;
	gap: .4rem;
	align-items: baseline;
	padding: .2rem 0;
	border-bottom: 1px solid var(--p-content-border-color);
}
.time {
	font-variant-numeric: tabular-nums;
	opacity: .7;
	flex: none;
}
.detail {
	display: block;
	margin-top: .15rem;
	font-size: .75rem;
	white-space: pre-wrap;
	overflow-wrap: anywhere;
	opacity: .85;
}
.text {
	overflow-wrap: anywhere;
}
.full {
	max-width: 100%;
	display: block;
}
</style>
