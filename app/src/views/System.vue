<template>
	<div class="system-page">
	<!-- the page's commands: what changes the whole device (each opens its own dialog); the playlist's transport is in its panel -->
	<Toolbar class="p-1">
		<template #start>
			<div style="font-size:150%">System</div>
		</template>
		<template #end>
			<InputGroup class="system-actions">
				<Button size="small" severity="secondary" type="button" icon="mi mi-download" aria-label="Back up" title="Back up" data-testid="open-backup" @click="dialog = 'backup'" />
				<Button size="small" severity="secondary" type="button" icon="mi mi-history" aria-label="Restore" title="Restore from a backup" data-testid="open-restore" @click="dialog = 'restore'" />
				<Button size="small" severity="secondary" type="button" icon="mi mi-key" aria-label="Device password" title="Change the device password" data-testid="open-password" @click="dialog = 'password'" />
			</InputGroup>
		</template>
	</Toolbar>
	<div class="system">
		<div class="system-main">
			<SystemCard title="Device">
				<template v-if="status">
					<div class="pills" role="list" aria-label="The parts of the device" data-testid="parts">
						<UsagePill v-for="p in devicePills(status.components, TITLES)" :key="p.label" v-bind="p" />
					</div>
					<!-- what is not running says why in words, under the pills -->
					<p v-for="(c, name) in failedParts" :key="name" class="row problem note">{{ TITLES[name] ?? name }}: {{ c.message }}</p>
				</template>
				<p v-else class="muted">Waiting for the device.</p>
			</SystemCard>

			<SystemCard v-if="problems.length" title="Problems">
				<ul class="plain">
					<li v-for="e in problems" :key="e.seq" class="row problem">
						<span class="time">{{ clockOf(e.ts) }}</span>
						<span class="text">{{ describe(e) }}<code v-if="e.detail" class="detail">{{ e.detail }}</code></span>
					</li>
				</ul>
			</SystemCard>

			<SystemCard title="Machine">
				<template v-if="info">
					<div class="pills" role="list" aria-label="The machine" data-testid="machine">
						<UsagePill v-for="p in machinePills(info.host, info.load, info.storage.volume, webCommit, mismatch)" :key="p.label" v-bind="p" />
					</div>
					<p v-if="mismatch" class="row problem note">Different builds: reload the page.</p>
				</template>
				<p v-if="!info" class="muted">{{ failed ? "The readings could not be loaded." : "Loading." }}</p>
			</SystemCard>

			<!-- only on a Raspberry Pi: what the board says about itself -->
			<SystemCard v-if="info?.pi" title="Raspberry Pi">
				<div class="pills" role="list" aria-label="The Raspberry Pi" data-testid="pi">
					<UsagePill v-for="p in piPills(info.pi)" :key="`${p.label}-${p.value}`" v-bind="p" />
				</div>
			</SystemCard>

			<SystemCard title="Storage" collapsed>
				<template #summary><span v-if="info" class="pills" role="list" aria-label="Storage" data-testid="storage-pills">
					<UsagePill v-for="p in storagePills(info.storage.areas, info.storage.volume)" :key="p.label" v-bind="p" />
				</span></template>
				<template v-if="info">
					<p class="total" data-testid="storage-total">{{ storageLine(info.storage.areas, info.storage.volume) }}</p>
					<div class="group-label">Areas</div>
					<div class="pills" role="list" aria-label="Areas">
						<UsagePill v-for="p in sizePills(info.storage.areas)" :key="p.label" v-bind="p" />
					</div>
					<template v-for="group in owners" :key="group.title">
						<div class="group-label">{{ group.title }}</div>
						<div v-if="group.items.length" class="pills" role="list" :aria-label="group.title">
							<UsagePill v-for="p in sizePills(group.items.map(o => ({ name: o.id, files: o.files, bytes: o.bytes, kept: o.kept_bytes })))" :key="p.label" v-bind="p" />
						</div>
						<p v-else class="muted note">None keep files.</p>
					</template>
					<p class="muted note">Hover a pill for its files, and what of it is kept: what a plugin or data source can fetch again (downloads, answers, lists).</p>
				</template>
			</SystemCard>

			<!-- what each API data source asks of its service (#440): the calls, what went wrong, the bytes, and how much the cache spared -->
			<SystemCard title="API usage" collapsed>
				<template #summary>
					<template v-if="info">
						<span v-if="info.usage.length === 0">No API data source has made a call yet.</span>
						<template v-else>
							<div class="answers-label">This month</div>
							<ul class="plain usage-summary" data-testid="usage-summary">
								<li v-for="source in info.usage" :key="source.id">
									<b>{{ source.name }}</b>
									<span class="pills" role="list" :aria-label="`${source.name}, this month`">
										<UsagePill v-for="p in usagePills(source.month, source.quota)" :key="p.label" v-bind="p" />
									</span>
								</li>
							</ul>
						</template>
					</template>
				</template>
				<template v-if="info">
					<p v-if="info.usage.length === 0" class="muted note">No API data source has made a call yet.</p>
					<div v-for="source in info.usage" :key="source.id" class="api-source" :data-source="source.id">
						<div class="source-name">{{ source.name }}</div>
						<div v-for="p in periods" :key="p.key" class="answers" role="list" :aria-label="`${source.name}, ${p.label}`" :data-period="p.key">
							<span class="answers-label">{{ p.label }}</span>
							<UsagePill v-for="pill in periodPills(p.label, source[p.key])" :key="pill.label" v-bind="pill" />
						</div>
						<div v-if="source.quota" class="quota" :data-quota="source.id">
							<div class="answers" role="list" :aria-label="`${source.name} quota`">
								<span class="answers-label">Plan</span>
								<UsagePill label="quota" :value="`${Math.round(source.quota.percent)}%`" :kind="quotaSeverity(source.quota.percent)" :title="quotaLine(source.quota)" />
								<span class="note">{{ quotaLine(source.quota) }}</span>
							</div>
							<Message size="small" v-if="quotaWarning(source.quota.percent)" :severity="source.quota.percent >= 100 ? 'error' : 'warn'" :closable="false" class="note" data-testid="quota-warning">{{ quotaWarning(source.quota.percent) }}</Message>
						</div>
						<div v-if="answerPills(source.month.status).length" class="answers" role="list" aria-label="This month, by answer" data-testid="answers">
							<span class="answers-label">Month</span>
							<UsagePill v-for="a in answerPills(source.month.status)" :key="a.code" :label="a.code" :value="a.count" :kind="a.kind" :title="a.title" />
						</div>
						<p v-if="source.lastLimited" class="muted note">Told "too many requests" last on {{ deviceMoment(source.lastLimited) }}.</p>
					</div>
					<p class="muted note">Calls the service saw, with the bytes of their bodies as they went over the wire. Cache: the share of lookups answered without a download (hover for the bytes saved). Days are the device's.</p>
				</template>
			</SystemCard>
		</div>

		<!-- what the device is doing now, and what it did: the telemetry link; two panels, as on the left -->
		<div class="system-live" :data-link="link.state.status">
			<!-- the playlist the layer is on, its tracks in order and the one playing, with play, stop and next (usePlaylistPanel) -->
			<SystemCard title="Playlist">
				<template #head><Tag :severity="transport.state.stopped ? 'warn' : 'success'" :value="transport.state.stopped ? 'Stopped' : 'Playing'" class="ml-auto" data-testid="playback-state" /></template>
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

			<SystemCard title="Activity">
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
		</div>

		<Dialog :visible="dialog === 'backup'" modal header="Back up" @update:visible="v => { if (!v) dialog = null }" style="width:36rem;max-width:95vw">
			<BackupRestore part="backup" />
		</Dialog>
		<Dialog :visible="dialog === 'restore'" modal header="Restore" @update:visible="v => { if (!v) dialog = null }" style="width:36rem;max-width:95vw">
			<BackupRestore part="restore" />
		</Dialog>
		<Dialog :visible="dialog === 'password'" modal header="Device password" @update:visible="v => { if (!v) dialog = null }" style="width:30rem;max-width:95vw">
			<PasswordForm />
		</Dialog>

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
	</div>
</template>
<script setup lang="ts">
/**
 * The System page (#390): how the device is (its parts, the machine, a Raspberry Pi's own readings, the storage by plugin and data source) and what it is doing
 * (the playlist's transport, what the panel shows, and what the tasks report over the telemetry link).
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Button, Dialog, InputGroup, Message, Select, Tag, Toolbar, ToggleSwitch, useToast } from "primevue"
import { LAYERS, clockOf, isProblem, type TelemetryEvent } from "../components/TelemetryLink"
import BackupRestore from "../components/BackupRestore.vue"
import SystemCard from "../components/SystemCard.vue"
import UsagePill from "../components/UsagePill.vue"
import PasswordForm from "../components/PasswordForm.vue"
import { answerPills, deviceMoment, devicePills, machinePills, periodPills, piPills, quotaLine, quotaSeverity, quotaWarning, sizePills, storageLine, storagePills, usagePills } from "../components/SystemFormat"
import { usePlaylistPanel } from "../composables/usePlaylistPanel"
import { hasOriginal, useSaveShown } from "../composables/useGallery"
import { SOURCES as sources, describeEvent as describe, eventIcon as iconOf, useSystem } from "../composables/useSystem"

const periods = [{ key: "today", label: "Today" }, { key: "week", label: "7 days" }, { key: "month", label: "Month" }] as const
const TITLES: Record<string, string> = { "display": "Display", "playlist-layer": "Playlist", "timer-layer": "Timer tasks" }
const toast = useToast()
// the status and the readings (asked again every few seconds), the transport, and the telemetry link's events as the panels show them
const {
	link, transport, status, info, failed, source, problemsOnly,
	mismatch, owners,
	current, currentLayers, recent, shownEvents, problems, statusText, statusSeverity,
	start, stop, press,
} = useSystem(detail => toast.add({ severity: "error", summary: "Playback", detail, life: 5000 }))
// the build this page's code is from (the Machine card says it beside the server's)
const webCommit = __APP_COMMIT__
const full = ref<TelemetryEvent | null>(null)
// "Save to Gallery" on what the panel shows and showed (#517)
const { busy: saving, saveShown } = useSaveShown((severity, detail) => toast.add({ severity, summary: "Gallery", detail, life: severity === "error" ? 6000 : 3000 }))
// the dialog the toolbar opened (backup, restore, password)
const dialog = ref<"backup" | "restore" | "password" | null>(null)
// the playlist panel follows the playlists while the page is shown
const { playlists, loaded, playlist, tracks, playing, start: followPlaylists, stop: unfollowPlaylists } = usePlaylistPanel({ transport })
onMounted(() => { start(); followPlaylists() })
onBeforeUnmount(() => { stop(); unfollowPlaylists() })

const title = (e: TelemetryEvent): string => String(e.values?.title ?? "")
// the parts that are not running say why in words under the Device card's pills
const failedParts = computed(() => Object.fromEntries(Object.entries(status.value?.components ?? {}).filter(([, c]) => c.state === "failed")))
</script>
<style scoped>
.system {
	display: grid;
	/* the facts on the left, the activity (the larger part) on the right */
	grid-template-columns: minmax(20rem, 2fr) minmax(0, 3fr);
	gap: .75rem;
	padding: .5rem;
	align-items: start;
}
.system-main {
	display: flex;
	flex-direction: column;
	gap: .75rem;
	min-width: 0;
}
.total {
	margin: 0;
	font-weight: bold;
}
.plain {
	list-style: none;
	margin: 0;
	padding: 0;
	display: flex;
	flex-direction: column;
	gap: .25rem;
}
.row {
	display: flex;
	gap: .5rem;
	align-items: baseline;
}
.row.problem, .event.problem {
	color: var(--p-red-500);
}
.muted {
	color: var(--p-text-muted-color);
	margin: 0;
}
.note {
	font-size: .8rem;
}
/* what the service answered and the closed card's summary: pills (UsagePill), wrapped, with a small label */
.answers {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: .3rem;
	margin: .35rem 0;
}
.answers-label {
	font-size: .75rem;
	color: var(--p-text-muted-color);
	text-transform: uppercase;
	letter-spacing: .04rem;
	margin-right: .15rem;
}
.usage-summary li {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: .2rem .5rem;
	margin: .25rem 0;
}
.group-label, .source-name {
	font-size: .8rem;
	font-weight: bold;
	margin: .5rem 0 .25rem;
}
.group-label:first-child, .source-name:first-child {
	margin-top: 0;
}
.pills {
	display: inline-flex;
	flex-wrap: wrap;
	gap: .3rem;
}
.sr-only {
	position: absolute;
	width: 1px;
	height: 1px;
	overflow: hidden;
	clip: rect(0 0 0 0);
	white-space: nowrap;
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
/* the right column: Now showing, Recently shown and Activity, each a panel of its own like the facts on the left */
.system-live {
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
/* a narrower window: the page's two columns stack */
@media (max-width: 900px) {
	.system {
		grid-template-columns: minmax(0, 1fr);
	}
}
</style>
