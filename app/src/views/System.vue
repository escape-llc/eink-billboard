<template>
	<div class="system-page">
	<!-- the page's commands, as on the playlist and schedule pages: the playlist's transport, then what changes the whole device (each opens its own dialog) -->
	<Toolbar class="p-1">
		<template #start>
			<div style="font-size:150%">System</div>
		</template>
		<template #end>
			<InputGroup class="system-actions" role="group" aria-label="Playback">
				<Button size="small" severity="secondary" type="button" data-testid="play-stop"
					:icon="transport.state.stopped ? 'mi mi-play-arrow' : 'mi mi-stop'"
					:aria-label="transport.state.stopped ? 'Play' : 'Stop playback'" :title="transport.state.stopped ? 'Play' : 'Stop playback'"
					:data-state="transport.state.stopped ? 'stopped' : 'playing'" :disabled="transport.state.busy"
					@click="press(transport.state.stopped ? 'play' : 'stop')" />
				<Button size="small" severity="secondary" type="button" icon="mi mi-skip-next" aria-label="Next track" title="Next track"
					data-testid="next-track" :disabled="transport.state.busy" @click="press('next')" />
			</InputGroup>
			<InputGroup class="system-actions ml-2">
				<Button size="small" severity="secondary" type="button" icon="mi mi-download" aria-label="Back up" title="Back up" data-testid="open-backup" @click="dialog = 'backup'" />
				<Button size="small" severity="secondary" type="button" icon="mi mi-history" aria-label="Restore" title="Restore from a backup" data-testid="open-restore" @click="dialog = 'restore'" />
				<Button size="small" severity="secondary" type="button" icon="mi mi-key" aria-label="Device password" title="Change the device password" data-testid="open-password" @click="dialog = 'password'" />
			</InputGroup>
		</template>
	</Toolbar>
	<div class="system">
		<div class="system-main">
			<section class="card" aria-label="Device">
				<div class="card-head">
					<strong>Device</strong>
					<Tag :severity="deviceSeverity" :value="deviceLabel" class="ml-auto" data-testid="status" :data-state="deviceState" />
				</div>
				<ul v-if="status" class="plain">
					<li v-for="(c, name) in status.components" :key="name" class="row">
						<i :class="c.state === 'failed' ? 'mi mi-cancel' : c.state === 'ok' ? 'mi mi-check-circle' : 'mi mi-schedule'" aria-hidden="true"></i>
						<span><b>{{ TITLES[name] ?? name }}</b>: {{ c.message }}</span>
					</li>
				</ul>
				<p v-else class="muted">Waiting for the device.</p>
			</section>

			<section v-if="problems.length" class="card" aria-label="Problems">
				<div class="card-head"><strong>Problems</strong></div>
				<ul class="plain">
					<li v-for="e in problems" :key="e.seq" class="row problem">
						<span class="time">{{ clockOf(e.ts) }}</span>
						<span class="text">{{ describe(e) }}<code v-if="e.detail" class="detail">{{ e.detail }}</code></span>
					</li>
				</ul>
			</section>

			<section class="card" aria-label="Machine">
				<div class="card-head"><strong>Machine</strong></div>
				<dl v-if="info" class="facts">
					<dt>System</dt><dd>{{ info.host.os }} {{ info.host.os_release }} ({{ info.host.machine }})</dd>
					<dt>App</dt>
					<dd data-testid="builds">
						Server {{ info.host.commit }}, web app {{ webCommit }}
						<Tag v-if="mismatch" severity="warn" value="Different builds: reload the page" class="ml-2" />
					</dd>
					<dt>Python</dt><dd>{{ info.host.python }}</dd>
					<dt>Machine up for</dt><dd>{{ formatUptime(info.host.uptime_seconds) }}</dd>
					<dt>App running for</dt><dd data-testid="app-uptime">{{ formatUptime(info.host.app_uptime_seconds) }}</dd>
					<dt>Processor</dt>
					<dd>
						{{ info.host.cpus }} {{ info.host.cpus === 1 ? "core" : "cores" }}<template v-if="info.load.cpu_percent !== undefined">, {{ info.load.cpu_percent }}% busy</template>
						<span v-if="info.load.load" class="muted"> (load {{ info.load.load.join(" ") }})</span>
					</dd>
					<template v-if="info.load.memory">
						<dt>Memory</dt>
						<dd>
							{{ formatBytes(info.load.memory.used) }} of {{ formatBytes(info.load.memory.total) }}
							<div class="gauge" role="meter" aria-label="Memory in use" :aria-valuenow="info.load.memory.percent" aria-valuemin="0" aria-valuemax="100">
								<div :class="gaugeSeverity(info.load.memory.percent)" :style="{ width: `${info.load.memory.percent}%` }"></div>
							</div>
						</dd>
					</template>
					<template v-if="info.load.app_memory !== undefined">
						<dt>This app</dt><dd>{{ formatBytes(info.load.app_memory) }}</dd>
					</template>
					<template v-if="info.storage.volume">
						<dt>Disk</dt>
						<dd>
							{{ formatBytes(info.storage.volume.free) }} free of {{ formatBytes(info.storage.volume.total) }}
							<div class="gauge" role="meter" aria-label="Disk in use" :aria-valuenow="info.storage.volume.percent" aria-valuemin="0" aria-valuemax="100">
								<div :class="gaugeSeverity(info.storage.volume.percent)" :style="{ width: `${info.storage.volume.percent}%` }"></div>
							</div>
						</dd>
					</template>
				</dl>
				<p v-else class="muted">{{ failed ? "The readings could not be loaded." : "Loading." }}</p>
			</section>

			<!-- only on a Raspberry Pi: what the board says about itself -->
			<section v-if="info?.pi" class="card" aria-label="Raspberry Pi">
				<div class="card-head"><strong>Raspberry Pi</strong></div>
				<dl class="facts">
					<dt>Model</dt><dd>{{ info.pi.model }}</dd>
					<template v-if="info.pi.temperature_c !== undefined">
						<dt>Temperature</dt>
						<dd><Tag :severity="temperatureSeverity(info.pi.temperature_c)" :value="`${info.pi.temperature_c} °C`" /></dd>
					</template>
					<template v-if="info.pi.cpu_mhz !== undefined">
						<dt>Clock</dt><dd>{{ info.pi.cpu_mhz }} MHz<span v-if="info.pi.cpu_max_mhz" class="muted"> (up to {{ info.pi.cpu_max_mhz }})</span></dd>
					</template>
					<template v-if="info.pi.throttled">
						<dt>Power</dt>
						<dd>
							<Tag v-if="info.pi.throttled.length === 0" severity="success" value="No warnings" />
							<span v-else class="tags">
								<Tag v-for="w in info.pi.throttled" :key="w" :severity="w.endsWith('now') ? 'danger' : 'warn'" :value="w" />
							</span>
						</dd>
					</template>
				</dl>
			</section>

			<section class="card" aria-label="Storage">
				<div class="card-head"><strong>Storage</strong></div>
				<template v-if="info">
					<table class="usage">
						<caption class="sr-only">Storage by area</caption>
						<thead><tr><th scope="col">Area</th><th scope="col" class="num">Files</th><th scope="col" class="num">Size</th></tr></thead>
						<tbody>
							<tr v-for="a in info.storage.areas" :key="a.name"><th scope="row">{{ a.name }}</th><td class="num">{{ a.files }}</td><td class="num">{{ formatBytes(a.bytes) }}</td></tr>
						</tbody>
					</table>
					<table v-for="group in owners" :key="group.title" class="usage">
						<caption>{{ group.title }}</caption>
						<thead><tr><th scope="col">Name</th><th scope="col" class="num">Files</th><th scope="col" class="num">Size</th><th scope="col" class="num">Kept</th></tr></thead>
						<tbody>
							<tr v-for="o in group.items" :key="o.id"><th scope="row">{{ o.id }}</th><td class="num">{{ o.files }}</td><td class="num">{{ formatBytes(o.bytes) }}</td><td class="num">{{ o.kept_bytes ? formatBytes(o.kept_bytes) : "" }}</td></tr>
							<tr v-if="group.items.length === 0"><td colspan="4" class="muted">None keep files.</td></tr>
						</tbody>
					</table>
					<p class="muted note">Kept: what a plugin or data source can fetch again (downloads, answers, lists).</p>
				</template>
			</section>

			<!-- what each API data source asks of its service (#440): the calls, what went wrong, the bytes, and how much the cache spared -->
			<section class="card" aria-label="API usage">
				<div class="card-head"><strong>API usage</strong></div>
				<template v-if="info">
					<p v-if="info.usage.length === 0" class="muted note">No API data source has made a call yet.</p>
					<div v-for="source in info.usage" :key="source.id" class="api-source" :data-source="source.id">
						<table class="usage">
							<caption>{{ source.name }}</caption>
							<thead><tr><th scope="col">Period</th><th scope="col" class="num">Calls</th><th scope="col" class="num">Failed</th><th scope="col" class="num">Sent</th><th scope="col" class="num">Received</th><th scope="col" class="num">Cache</th></tr></thead>
							<tbody>
								<tr v-for="p in periods" :key="p.key">
									<th scope="row">{{ p.label }}</th>
									<td class="num">{{ source[p.key].calls }}</td>
									<td class="num">{{ failedCalls(source[p.key].status) || "" }}</td>
									<td class="num">{{ formatBytes(source[p.key].sent) }}</td>
									<td class="num">{{ formatBytes(source[p.key].received) }}</td>
									<td class="num" :title="`Saved ${formatBytes(source[p.key].bytesSaved)}`">{{ formatShare(source[p.key].hitRate) }}</td>
								</tr>
							</tbody>
						</table>
						<p v-if="statusSummary(source.month.status)" class="muted note">This month, by answer: {{ statusSummary(source.month.status) }}.</p>
						<p v-if="source.lastLimited" class="muted note">Told "too many requests" last on {{ deviceMoment(source.lastLimited) }}.</p>
					</div>
					<p class="muted note">Calls the service saw, with the bytes of their bodies as they went over the wire. Cache: the share of lookups answered without a download (hover for the bytes saved). Days are the device's.</p>
				</template>
			</section>
		</div>

		<!-- what the device is doing now, and what it did: the telemetry link; two panels, as on the left -->
		<div class="system-live" :data-link="link.state.status">
			<!-- a media player: the picture, its title and the time it was sent, and one line per layer (its glyph, then the track or task that made it) -->
			<section class="card" aria-label="Now showing">
				<div class="card-head">
					<strong>Now showing</strong>
					<Tag v-if="link.state.status !== 'live'" :severity="statusSeverity" :value="statusText" class="ml-auto" data-testid="link-status" />
				</div>
				<div v-if="current" class="now">
					<button type="button" class="thumb" :aria-label="`Show ${title(current)} full size`" @click="full = current">
						<!-- the panel's own pixels: the card is wider than the 320 pixel thumbnail, which the browser blurred when it enlarged it -->
						<img :src="link.imageUrl(current.values?.digest, 'full')" :alt="title(current)" />
					</button>
					<div class="player">
						<div class="player-head">
							<span class="title">{{ title(current) }}</span>
							<span class="clock">{{ clockOf(current.ts) }}</span>
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
			</section>

			<section class="card" aria-label="Recently shown">
				<div class="card-head"><strong>Recently shown</strong></div>
				<div v-if="recent.length > 1" class="strip">
					<button v-for="e in recent.slice(1)" :key="e.seq" type="button" class="mini" :title="`${clockOf(e.ts)} ${title(e)}`"
						:aria-label="`Show ${title(e)} full size`" @click="full = e">
						<img :src="link.imageUrl(e.values?.digest)" :alt="title(e)" />
					</button>
				</div>
				<p v-else class="muted">Nothing else has been shown yet.</p>
			</section>

			<section class="card" aria-label="Activity">
				<div class="card-head"><strong>Activity</strong></div>
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
			</section>
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
		</Dialog>
	</div>
	</div>
</template>
<script setup lang="ts">
/**
 * The System page (#390): how the device is (its parts, the machine, a Raspberry Pi's own readings, the storage by plugin and data source) and what it is doing
 * (the playlist's transport, what the panel shows, and what the tasks report over the telemetry link).
 */
import { onBeforeUnmount, onMounted, ref } from "vue"
import { Button, Dialog, InputGroup, Select, Tag, Toolbar, ToggleSwitch, useToast } from "primevue"
import { LAYERS, clockOf, isProblem, type TelemetryEvent } from "../components/TelemetryLink"
import BackupRestore from "../components/BackupRestore.vue"
import PasswordForm from "../components/PasswordForm.vue"
import { deviceMoment, failedCalls, formatBytes, formatShare, formatUptime, gaugeSeverity, statusSummary, temperatureSeverity } from "../components/SystemFormat"
import { SOURCES as sources, describeEvent as describe, eventIcon as iconOf, useSystem } from "../composables/useSystem"

const periods = [{ key: "today", label: "Today" }, { key: "week", label: "7 days" }, { key: "month", label: "Month" }] as const
const TITLES: Record<string, string> = { "display": "Display", "playlist-layer": "Playlist", "timer-layer": "Timer tasks" }
const toast = useToast()
// the status and the readings (asked again every few seconds), the transport, and the telemetry link's events as the panels show them
const {
	link, transport, status, info, failed, source, problemsOnly,
	mismatch, deviceState, deviceSeverity, deviceLabel, owners,
	current, currentLayers, recent, shownEvents, problems, statusText, statusSeverity,
	start, stop, press,
} = useSystem(detail => toast.add({ severity: "error", summary: "Playback", detail, life: 5000 }))
// the build this page's code is from (the Machine card says it beside the server's)
const webCommit = __APP_COMMIT__
const full = ref<TelemetryEvent | null>(null)
// the dialog the toolbar opened (backup, restore, password)
const dialog = ref<"backup" | "restore" | "password" | null>(null)
onMounted(start)
onBeforeUnmount(stop)

const title = (e: TelemetryEvent): string => String(e.values?.title ?? "")
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
/* each part has its own surface, as the other panels have: it follows the theme and dark mode */
.card {
	display: flex;
	flex-direction: column;
	gap: .5rem;
	min-width: 0;
	padding: .5rem .75rem;
	border-radius: var(--p-toolbar-border-radius);
	border: solid 1px var(--p-toolbar-border-color);
	background: var(--p-content-background);
}
.card-head {
	display: flex;
	align-items: center;
	gap: .5rem;
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
.facts {
	display: grid;
	grid-template-columns: max-content minmax(0, 1fr);
	gap: .35rem 1rem;
	margin: 0;
}
.facts dt {
	color: var(--p-text-muted-color);
}
.facts dd {
	margin: 0;
	min-width: 0;
}
.tags {
	display: inline-flex;
	flex-wrap: wrap;
	gap: .25rem;
}
.gauge {
	height: .5rem;
	margin-top: .2rem;
	border-radius: .25rem;
	background: var(--p-content-hover-background);
	overflow: hidden;
}
.gauge > div {
	height: 100%;
}
.gauge .success { background: var(--p-green-500); }
.gauge .warn { background: var(--p-orange-500); }
.gauge .danger { background: var(--p-red-500); }
.usage {
	width: 100%;
	border-collapse: collapse;
	font-size: .85rem;
}
.usage caption {
	text-align: left;
	font-weight: bold;
	padding: .35rem 0 .15rem;
}
.usage th, .usage td {
	padding: .15rem .25rem;
	border-bottom: 1px solid var(--p-content-border-color);
	text-align: left;
	font-weight: normal;
}
.usage thead th {
	color: var(--p-text-muted-color);
	font-size: .75rem;
	text-transform: uppercase;
}
.usage .num {
	text-align: right;
	font-variant-numeric: tabular-nums;
}
.sr-only {
	position: absolute;
	width: 1px;
	height: 1px;
	overflow: hidden;
	clip: rect(0 0 0 0);
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
