<template>
	<div class="gallery-page">
	<Toolbar class="p-1">
		<template #start>
			<div style="font-size:150%">Gallery</div>
		</template>
		<template #end>
			<div class="gallery-actions">
				<span v-if="totals" class="totals muted" data-testid="gallery-totals">{{ totalsLine(totals) }}</span>
				<label class="toggle"><ToggleSwitch v-model="pinnedOnly" aria-label="Pinned only" data-testid="pinned-only" /> Pinned only</label>
				<Button size="small" severity="secondary" type="button" icon="mi mi-upload" label="Add pictures" title="Add pictures from this computer"
					data-testid="gallery-upload" :disabled="busy" @click="picker?.click()" />
				<input ref="picker" type="file" class="sr-only" :accept="ACCEPT" multiple aria-label="Pictures to add" data-testid="gallery-file" @change="picked" />
			</div>
		</template>
	</Toolbar>
	<Tabs v-model:value="tab">
		<TabList>
			<Tab value="pictures">Pictures</Tab>
			<Tab value="recent">Recently shown</Tab>
		</TabList>
		<TabPanels>
			<TabPanel value="pictures">
				<p v-if="loading" class="muted">Loading.</p>
				<p v-else-if="failed" class="muted">The Gallery could not be loaded.</p>
				<p v-else-if="shown.length === 0" class="muted" data-testid="gallery-empty">
					{{ pinnedOnly ? "No picture is pinned." : "The Gallery is empty: the pictures a Generated Image or a Weather Visualizer draws are kept here, and you can add your own or save one the panel showed." }}
				</p>
				<ul v-else class="grid" aria-label="Pictures" data-testid="gallery-grid">
					<li v-for="(item, i) in shown" :key="item.id" class="card" :data-id="item.id" :class="{ pinned: item.pinned }">
						<button type="button" class="thumb" :aria-label="`Show ${nameOf(item)} full size`" @click="open(i)">
							<img :src="galleryImageUrl(item.id)" :alt="nameOf(item)" loading="lazy" />
						</button>
						<div class="caption">
							<span class="title" :title="nameOf(item)">{{ nameOf(item) }}</span>
							<span class="muted small">{{ originOf(item, sourceNames) }} · {{ deviceMoment(item.added) }}</span>
						</div>
						<div class="card-actions">
							<Button size="small" text type="button" :icon="item.pinned ? 'mi mi-keep-off' : 'mi mi-keep'" :disabled="busy"
								:aria-label="item.pinned ? `Unpin ${nameOf(item)}` : `Pin ${nameOf(item)}`" :title="item.pinned ? 'Unpin: may be let go when the Gallery is full' : 'Pin: never let go to make room'"
								:aria-pressed="item.pinned" data-testid="pin" @click="pin(item, !item.pinned)" />
							<Button size="small" text severity="danger" type="button" icon="mi mi-delete" :disabled="busy"
								:aria-label="`Remove ${nameOf(item)}`" title="Remove from the Gallery" data-testid="remove" @click="askRemove(item)" />
						</div>
					</li>
				</ul>
			</TabPanel>
			<TabPanel value="recent">
				<!-- the same pictures as the System page's Now showing and Recently shown, from the telemetry link -->
				<ul v-if="recent.length" class="grid" aria-label="Recently shown" data-testid="recent-grid">
					<li v-for="e in recent" :key="e.values?.digest" class="card">
						<button type="button" class="thumb" :aria-label="`Show ${shownTitle(e)} full size`" @click="full = e">
							<img :src="link.imageUrl(e.values?.digest)" :alt="shownTitle(e)" />
						</button>
						<div class="caption">
							<span class="title" :title="shownTitle(e)">{{ shownTitle(e) }}</span>
							<span class="muted small">{{ clockOf(e.ts) }}</span>
						</div>
						<div class="card-actions">
							<Button size="small" text type="button" icon="mi mi-add-photo-alternate" :disabled="busy" :aria-label="`Save ${shownTitle(e)} to the Gallery`"
								:title="hasOriginal(e) ? 'Save the picture this page was made from to the Gallery' : 'Save to the Gallery, as it was shown'" data-testid="save-shown" @click="saveShown(e)" />
						</div>
					</li>
				</ul>
				<p v-else class="muted">Nothing has been shown yet.</p>
			</TabPanel>
		</TabPanels>
	</Tabs>

	<!-- the pictures full screen, one after another; a click on one shows it at its own size (zoomed), another fits it again -->
	<Galleria v-model:visible="viewing" v-model:activeIndex="active" :value="shown" fullScreen circular showItemNavigators :showThumbnails="false"
		:containerStyle="{ width: '100vw' }" data-testid="gallery-viewer" @update:activeIndex="zoomed = false">
		<template #item="{ item }">
			<div class="viewer" :class="{ zoomed }">
				<img :src="galleryImageUrl(item.id, 'full')" :alt="nameOf(item)" :title="zoomed ? 'Fit to the screen' : 'Show at its own size'" @click="zoomed = !zoomed" />
			</div>
		</template>
		<template #caption="{ item }">
			<div class="viewer-caption">
				<b>{{ nameOf(item) }}</b>
				<span v-if="item.width && item.height" class="small size">{{ item.width }} × {{ item.height }}</span>
				<div v-if="item.prompt" class="small prompt">{{ item.prompt }}</div>
			</div>
		</template>
	</Galleria>

	<Dialog :visible="full !== null" modal :header="full ? shownTitle(full) : ''" @update:visible="v => { if (!v) full = null }" style="max-width:95vw">
		<img v-if="full" class="full" :src="link.imageUrl(full.values?.digest, 'full')" :alt="shownTitle(full)" />
		<template #footer>
			<template v-if="full">
				<Button v-if="hasOriginal(full)" size="small" severity="secondary" type="button" label="Save as shown" title="Save the panel's picture, with its overlays" :disabled="busy" data-testid="save-as-shown" @click="saveShown(full, true)" />
				<Button size="small" type="button" icon="mi mi-add-photo-alternate" :label="hasOriginal(full) ? 'Save original' : 'Save to Gallery'"
					:title="hasOriginal(full) ? 'Save the picture this page was made from' : 'Save the picture as it was shown'" :disabled="busy" data-testid="save-full" @click="saveShown(full)" />
			</template>
		</template>
	</Dialog>
	</div>
</template>
<script setup lang="ts">
/**
 * The Gallery page (#517): the pictures the Gallery keeps (#238), to look at full screen, pin (never let go to make room) or remove, and to add
 * from this computer; and what the panel showed lately (as on the System page), to save to the Gallery as it was shown.
 */
import { computed, ref } from "vue"
import { Button, Dialog, Galleria, Tab, TabList, TabPanel, TabPanels, Tabs, ToggleSwitch, Toolbar, useToast } from "primevue"
import { useConfirm } from "primevue/useconfirm"
import { clockOf, useTelemetry, type TelemetryEvent } from "../components/TelemetryLink"
import { deviceMoment, formatBytes } from "../components/SystemFormat"
import { ACCEPT, galleryImageUrl, hasOriginal, originOf, useGallery, type GalleryItem } from "../composables/useGallery"
import { useCatalog } from "../api/resources"
import { shownTitle, useRecentlyShown } from "../composables/useRecentlyShown"

const toast = useToast()
const confirm = useConfirm()
const { shown, totals, loading, failed, pinnedOnly, busy, pin, remove, upload, saveShown } =
	useGallery((severity, detail) => toast.add({ severity, summary: "Gallery", detail, life: severity === "error" ? 6000 : 3000 }))
// the app's one link (App.vue opens it): the pictures the panel showed
const link = useTelemetry()
const { recent } = useRecentlyShown(link)
// the data sources by id, to say where a picture came from in their own names
const { dataSources } = useCatalog()
const sourceNames = computed(() => Object.fromEntries((dataSources.data.value ?? []).map(d => [d.id, d.name])))

const tab = ref("pictures")
const picker = ref<HTMLInputElement | null>(null)
const viewing = ref(false)
const active = ref(0)
const zoomed = ref(false)
const full = ref<TelemetryEvent | null>(null)

const nameOf = (item: GalleryItem): string => item.title || "Untitled"
const totalsLine = (t: { count: number, bytes: number, maxPictures: number, maxBytes: number }) =>
	`${t.count} of ${t.maxPictures} pictures, ${formatBytes(t.bytes)} of ${formatBytes(t.maxBytes)}`

function open(index: number) {
	active.value = index
	zoomed.value = false
	viewing.value = true
}
async function picked(ev: Event) {
	const input = ev.target as HTMLInputElement
	const files = [...(input.files ?? [])]
	// the same file chosen again is a change too
	input.value = ""
	// one at a time, in the order chosen: the newest is the last
	for (const file of files) await upload(file)
}
function askRemove(item: GalleryItem) {
	confirm.require({
		header: "Remove the picture",
		message: `Remove "${nameOf(item)}" from the Gallery? It cannot be brought back.`,
		icon: "mi mi-warning",
		acceptLabel: "Remove",
		rejectLabel: "Keep",
		acceptProps: { severity: "danger" },
		accept: () => { void remove(item) },
	})
}
</script>
<style scoped>
.gallery-actions {
	display: flex;
	align-items: center;
	flex-wrap: wrap;
	gap: .5rem;
}
.totals {
	font-size: .85rem;
}
.toggle {
	display: flex;
	align-items: center;
	gap: .35rem;
	font-size: .85rem;
}
.muted {
	color: var(--p-text-muted-color);
	margin: 0;
}
.small {
	font-size: .8rem;
}
.sr-only {
	position: absolute;
	width: 1px;
	height: 1px;
	overflow: hidden;
	clip: rect(0 0 0 0);
	white-space: nowrap;
}
/* as many columns as fit, never a sideways scroll: a phone is narrow */
.grid {
	list-style: none;
	margin: 0;
	padding: 0;
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
	gap: .75rem;
}
.card {
	display: flex;
	flex-direction: column;
	min-width: 0;
	border: 1px solid var(--p-content-border-color);
	border-radius: var(--p-content-border-radius);
	background: var(--p-content-background);
	overflow: hidden;
}
.card.pinned {
	border-color: var(--p-primary-color);
}
.thumb {
	padding: 0;
	border: none;
	border-bottom: 1px solid var(--p-content-border-color);
	background: var(--p-content-hover-background);
	cursor: zoom-in;
	display: block;
	aspect-ratio: 4 / 3;
}
.thumb img {
	display: block;
	width: 100%;
	height: 100%;
	object-fit: contain;
}
.caption {
	display: flex;
	flex-direction: column;
	padding: .35rem .5rem 0;
	min-width: 0;
}
.title {
	font-weight: bold;
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.card-actions {
	display: flex;
	justify-content: flex-end;
	padding: 0 .25rem .25rem;
}
/* full screen: the picture fits the screen, or, zoomed, is its own size and scrolls */
.viewer {
	width: 100vw;
	height: calc(100vh - 6rem);
	display: flex;
	align-items: center;
	justify-content: center;
	overflow: hidden;
}
.viewer img {
	width: 100%;
	height: 100%;
	object-fit: contain;
	cursor: zoom-in;
}
.viewer.zoomed {
	display: block;
	overflow: auto;
}
.viewer.zoomed img {
	width: auto;
	height: auto;
	cursor: zoom-out;
}
.viewer-caption .size {
	margin-left: .5rem;
}
.viewer-caption .prompt {
	margin-top: .2rem;
	white-space: pre-wrap;
	overflow-wrap: anywhere;
}
.full {
	max-width: 100%;
	display: block;
}
</style>
