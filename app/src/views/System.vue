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
			<!-- the device in one card (#807): the application's own parts, the machine it runs on, and on a Raspberry Pi the board, each a row of pills under its name -->
			<SystemCard title="Device">
				<div class="group-label" id="device-application">Application</div>
				<template v-if="status">
					<div class="pills" role="list" aria-labelledby="device-application" data-testid="parts">
						<UsagePill v-for="p in devicePills(status.components, TITLES, info?.load.app_memory, info?.storage.areas)" :key="p.label" v-bind="p" />
					</div>
					<!-- what is not running says why in words, under the pills -->
					<p v-for="(c, name) in failedParts" :key="name" class="row problem note">{{ TITLES[name] ?? name }}: {{ c.message }}</p>
				</template>
				<p v-else class="muted">Waiting for the application.</p>
				<div class="group-label" id="device-machine">Machine</div>
				<template v-if="info">
					<div class="pills" role="list" aria-labelledby="device-machine" data-testid="machine">
						<UsagePill v-for="p in machinePills(info.host, info.load, info.storage.volume, webCommit, mismatch)" :key="p.label" v-bind="p" />
					</div>
					<p v-if="mismatch" class="row problem note">Different builds: reload the page.</p>
				</template>
				<p v-else class="muted">{{ failed ? "The readings could not be loaded." : "Loading." }}</p>
				<!-- only on a Raspberry Pi: what the board says about itself -->
				<template v-if="info?.pi">
					<div class="group-label" id="device-pi">Raspberry Pi</div>
					<div class="pills" role="list" aria-labelledby="device-pi" data-testid="pi">
						<UsagePill v-for="p in piPills(info.pi)" :key="`${p.label}-${p.value}`" v-bind="p" />
					</div>
				</template>
			</SystemCard>

			<SystemCard v-if="problems.length" title="Problems">
				<ul class="plain">
					<li v-for="e in problems" :key="e.seq" class="row problem">
						<span class="time">{{ clockOf(e.ts) }}</span>
						<span class="text">{{ describe(e) }}<code v-if="e.detail" class="detail">{{ e.detail }}</code></span>
					</li>
				</ul>
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

		<!-- what the device is doing now, and what it did (PanelNow, which Home shows too): `?activity=problems` or `=all` opens Activity so (#824) -->
		<PanelNow class="system-live" :focus="focus" />

		<Dialog :visible="dialog === 'backup'" modal header="Back up" @update:visible="v => { if (!v) dialog = null }" style="width:36rem;max-width:95vw">
			<BackupRestore part="backup" />
		</Dialog>
		<Dialog :visible="dialog === 'restore'" modal header="Restore" @update:visible="v => { if (!v) dialog = null }" style="width:36rem;max-width:95vw">
			<BackupRestore part="restore" />
		</Dialog>
		<Dialog :visible="dialog === 'password'" modal header="Device password" @update:visible="v => { if (!v) dialog = null }" style="width:30rem;max-width:95vw">
			<PasswordForm />
		</Dialog>

	</div>
	</div>
</template>
<script setup lang="ts">
/**
 * The System page (#390): how the device is (its parts, the machine, a Raspberry Pi's own readings, the storage by plugin and data source) and,
 * on the right, what it is doing: the playlist's transport, what the panel shows and what the tasks report over the telemetry link (PanelNow, #824).
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute } from "vue-router"
import { Button, Dialog, InputGroup, Message, Toolbar } from "primevue"
import { clockOf } from "../components/TelemetryLink"
import BackupRestore from "../components/BackupRestore.vue"
import SystemCard from "../components/SystemCard.vue"
import UsagePill from "../components/UsagePill.vue"
import PasswordForm from "../components/PasswordForm.vue"
import PanelNow from "../components/PanelNow.vue"
import { answerPills, deviceMoment, devicePills, machinePills, periodPills, piPills, quotaLine, quotaSeverity, quotaWarning, sizePills, storageLine, storagePills, usagePills } from "../components/SystemFormat"
import { describeEvent as describe } from "../composables/usePanelNow"
import { useSystem } from "../composables/useSystem"

const periods = [{ key: "today", label: "Today" }, { key: "week", label: "7 days" }, { key: "month", label: "Month" }] as const
const TITLES: Record<string, string> = { "display": "Display", "playlist-layer": "Playlist", "timer-layer": "Timer tasks" }
// the status and the readings (asked again every few seconds), and the latest problems the tasks reported
const { status, info, failed, mismatch, owners, problems, start, stop } = useSystem()
// the build this page's code is from (the Device card's Machine row says it beside the server's)
const webCommit = __APP_COMMIT__
// the dialog the toolbar opened (backup, restore, password)
const dialog = ref<"backup" | "restore" | "password" | null>(null)
onMounted(() => start())
onBeforeUnmount(() => stop())
// Home's activity line opens the Activity panel here, narrowed to problems when it was one
const route = useRoute()
const focus = computed(() => route.query.activity === "problems" ? "problems" : route.query.activity === "all" ? "all" : null)

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
.row.problem {
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
.pills + .group-label, .note + .group-label, .muted + .group-label {
	margin-top: .6rem;
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
/* a narrower window: the page's two columns stack */
@media (max-width: 900px) {
	.system {
		grid-template-columns: minmax(0, 1fr);
	}
}
</style>
