<template>
	<div class="playlist-editor">
		<Toolbar class="p-1">
			<template #start>
				<div style="font-size:150%">Playlists</div>
			</template>
			<template #end>
				<div class="flex align-items-center gap-1">
					<Select :key="selectKey" :options="playlists" optionLabel="name" optionValue="id" :modelValue="currentId" placeholder="No playlist" style="min-width:14rem"
						aria-label="Playlist" @update:modelValue="(id: string) => guard(() => openPlaylist(id))" />
					<Button title="New playlist" aria-label="New playlist" icon="pi pi-plus-circle" size="small" severity="secondary" @click="guard(startNew)" />
					<Button title="Rename playlist" aria-label="Rename playlist" icon="pi pi-pencil" size="small" severity="secondary" :disabled="!currentId" @click="startRename" />
					<Button title="Delete playlist" aria-label="Delete playlist" icon="pi pi-trash" size="small" severity="danger" variant="outlined" :disabled="!currentId" @click="deleteOpen = true" />
					<Button title="Add Track" aria-label="Add track" icon="pi pi-plus" size="small" :disabled="!currentId" @click="addTrack" />
					<Button title="Save playlist" aria-label="Save playlist" icon="pi pi-save" size="small" severity="success" :disabled="!currentId || !dirty || saving" @click="savePlaylist(docRev)" />
				</div>
			</template>
		</Toolbar>
		<Message v-if="dirty" severity="info" size="small" variant="simple" class="mt-1">Unsaved changes to "{{ playlistName }}".</Message>
		<Message v-if="conflict" severity="warn" :closable="false" class="mt-1">
			<div class="flex align-items-center gap-2">
				<span>{{ conflict.message }}</span>
				<Button size="small" label="Reload" icon="pi pi-refresh" severity="secondary" @click="reloadPlaylist" />
				<Button v-if="conflict.rev" size="small" label="Overwrite" icon="pi pi-upload" severity="danger" @click="savePlaylist(conflict.rev)" />
			</div>
		</Message>
		<Message v-for="(problem, index) in serverProblems" :key="index" severity="error" size="small" variant="simple">{{ problem }}</Message>

		<div class="layout">
			<div class="track-list">
				<ul>
					<li v-for="(t, idx) in tracks" :key="t.id" :class="{ selected: selectedIndex === idx }">
						<div class="track-row" @click="selectTrack(idx)">
							<div class="track-meta">
								<div class="title">{{  t.title  }}</div>
								<div>{{ pluginName(t.plugin_name) || 'Unknown Plugin' }}</div>
							</div>
							<div class="actions">
								<Button icon="pi pi-arrow-up" aria-label="Move up" size="small" class="p-button-text" :disabled="idx === 0" @click.stop="moveTrack(idx, -1)" />
								<Button icon="pi pi-arrow-down" aria-label="Move down" size="small" class="p-button-text" :disabled="idx === tracks.length - 1" @click.stop="moveTrack(idx, 1)" />
								<Button icon="pi pi-trash" aria-label="Remove track" size="small" severity="danger" class="p-button-text"
									@click.stop="removeTrack(idx)" />
							</div>
						</div>
					</li>
				</ul>
				<p v-if="currentId && tracks.length === 0" class="m-1">No tracks yet.</p>
				<p v-if="!currentId" class="m-1">Create a playlist to add tracks.</p>
			</div>

			<div class="track-editor">
				<div v-if="selectedTrack" class="editor-card">
					<BasicForm ref="bf" v-if="selectedPlugin" :baseUrl="API_URL" :form="selectedPlugin.instanceSettings" :initialValues="editModel.content"
						@validate="handleValidate" @submit="submitForm">
						<template #header>
							<Toolbar style="width:100%" class="p-1 mt-2">
								<template #start>
									<div style="font-weight: bold;font-size:150%">Track Settings</div>
								</template>
								<template #end>
									<InputGroup>
										<Button size="small" icon="pi pi-check" severity="success" aria-label="Apply track" title="Apply to the playlist (then save it)" :disabled="submitDisabled" @click="handleSubmit" />
										<Button size="small" icon="pi pi-times" severity="danger" aria-label="Reset track" @click="handleReset" />
									</InputGroup>
								</template>
							</Toolbar>
						</template>
						<template #group-header="slotProps">
							<h3 class="mb-0">{{ slotProps.title }}</h3>
						</template>
						<template #before-fields>
							<InputGroup>
								<InputGroupAddon>
									<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" style="flex-shrink:0;flex-grow:1">Title</label>
								</InputGroupAddon>
								<InputText style="flex-grow:1" size="small" v-model="editModel.title" />
							</InputGroup>
							<InputGroup>
								<InputGroupAddon>
									<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" style="flex-shrink:0;flex-grow:1">Plugin</label>
								</InputGroupAddon>
								<Select :options="pluginOptions" optionLabel="name" optionValue="id" v-model="editModel.plugin_name" />
							</InputGroup>
						</template>
					</BasicForm>
				</div>

				<div v-else class="empty-state">
					<p>Select a track to edit its properties.</p>
				</div>
			</div>
		</div>

		<Dialog v-model:visible="nameOpen" modal :header="nameDialogRename ? 'Rename playlist' : 'New playlist'" style="width:24rem">
			<InputText v-model="nameValue" aria-label="Playlist name" fluid autofocus @keyup.enter="confirmName" />
			<div class="flex gap-2 justify-content-end pt-2">
				<Button type="button" label="Cancel" severity="secondary" @click="nameOpen = false"></Button>
				<Button type="button" label="OK" :disabled="!nameValue.trim() || saving" @click="confirmName"></Button>
			</div>
		</Dialog>
		<Dialog v-model:visible="deleteOpen" modal header="Delete playlist?" style="width:24rem">
			<p class="mt-0">"{{ playlistName }}" and its tracks will be removed.</p>
			<div class="flex gap-2 justify-content-end">
				<Button type="button" label="Keep" severity="secondary" @click="deleteOpen = false"></Button>
				<Button type="button" label="Delete" severity="danger" :disabled="saving" @click="deletePlaylist"></Button>
			</div>
		</Dialog>
		<Dialog v-model:visible="discardOpen" modal header="Discard unsaved changes?" style="width:24rem" @hide="onDiscardHide">
			<p class="mt-0">The changes to "{{ playlistName }}" were not saved.</p>
			<div class="flex gap-2 justify-content-end">
				<Button type="button" label="Keep editing" severity="secondary" @click="discardOpen = false"></Button>
				<Button type="button" label="Discard" severity="danger" @click="confirmDiscard"></Button>
			</div>
		</Dialog>
	</div>
</template>

<script setup lang="ts">
import { ApiError, apiDelete, apiJson, apiPatch, apiPost, apiPut } from "../components/ApiClient"
import { ref, reactive, computed, onMounted, provide } from 'vue'
import { InputGroup, InputGroupAddon, Toolbar, Button, Select, InputText, Dialog, Message, useToast } from 'primevue'
import BasicForm, { type ValidateEventData } from '../components/BasicForm.vue'
import type { PlaylistItem, PluginDef } from '../components/ScheduleDefs'
const API_URL = import.meta.env.VITE_API_URL
const PLAYLIST_URL = `${API_URL}api/schedule/playlist`
const toast = useToast()
const bf = ref<InstanceType<typeof BasicForm>>()
const submitDisabled = ref(true)
const fieldNameWidth = "10rem";

const plugins = ref([])
const dataSources = ref([])
provide("settingsPluginsList", plugins)
provide("settingsDataSourcesList", dataSources)

const listPluginsUrl = `${API_URL}api/plugins/list`
const listDatasourcesUrl = `${API_URL}api/datasources/list`

const pluginList = ref<PluginDef[]>([])
// every stored playlist (a playlist is a self-contained document), and the one being edited: its working copy is saved whole
const playlists = ref<{ id: string, name: string }[]>([])
const currentId = ref<string|undefined>(undefined)
const playlistName = ref<string>()
const docRev = ref<string|undefined>(undefined)
const tracks = ref<PlaylistItem[]>([])
const dirty = ref(false)
const saving = ref(false)
const conflict = ref<{ message: string, rev: string|undefined }|null>(null)
const serverProblems = ref<string[]>([])
const selectedIndex = ref<number | null>(null)
const nameOpen = ref(false)
const nameDialogRename = ref(false)
const nameValue = ref("")
const deleteOpen = ref(false)
const discardOpen = ref(false)
let pendingAction: (() => void)|undefined = undefined
// the playlist select shows what was picked, even when the change is refused: a new key makes it show the playlist again
const selectKey = ref(0)

// editing model separate from the track until Apply
const editModel = reactive<Record<string,any>>({} as any) // start with empty model, populate on track select

const selectedTrack = computed(() => (selectedIndex.value !== null ? tracks.value[selectedIndex.value] : null))
const selectedPlugin = computed(() => pluginList.value.find(p => p.id === editModel.plugin_name) || null)
// a playlist track plays on the background or foreground layer: the plugins for the timer layers (priority, overlay) are not offered.
// A stored track keeps its plugin (and shows it) even when it would not be offered now
const PLAYLIST_LAYERS = ["layer-background", "layer-foreground"]
const playlistPlugins = computed(() => pluginList.value.filter(p => (p.features ?? []).some(f => PLAYLIST_LAYERS.includes(f))))
const pluginOptions = computed(() => pluginList.value.filter(p => playlistPlugins.value.includes(p) || p.id === editModel.plugin_name).map(p => ({ id: p.id, name: p.name })))

// a track that is not saved yet has an id of ours; the server gives it its own
const NEW_PREFIX = "new-"
function uid() { return `${NEW_PREFIX}${Math.random().toString(36).slice(2, 9)}` }

const handleValidate = (e: ValidateEventData) => {
	submitDisabled.value = !e.result.success
}
/** Apply: the form's fields (only the selected plugin's) are the track's content; title and plugin are the editor's. */
const submitForm = (data:any) => {
	if(!data.result?.success || selectedIndex.value === null) return
	const index = selectedIndex.value
	const old = tracks.value[index]
	if(!old) return
	tracks.value[index] = { ...old, title: editModel.title, plugin_name: editModel.plugin_name, type: "PlaylistSchedule", content: structuredClone(data.result.data) }
	dirty.value = true
	serverProblems.value = []
}
const handleReset = () => {
	cancelEdit()
	bf.value?.reset()
}
const handleSubmit = () => {
	bf.value?.submit()
}

// helpers
function pluginName(id?: string) {
	const p = pluginList.value.find(x => x.id === id)
	return p ? p.name : null
}
function resetMessages() {
	conflict.value = null
	serverProblems.value = []
}

// track operations: they change the working copy; Save sends the playlist
function addTrack() {
	const first = playlistPlugins.value[0]
	if(!first) return
	tracks.value.push({ id: uid(), plugin_name: first.id, type: "PlaylistSchedule", title: "Untitled", content: {} })
	dirty.value = true
	selectTrack(tracks.value.length - 1)
}

function removeTrack(idx: number) {
	if (idx < 0 || idx >= tracks.value.length) return
	tracks.value.splice(idx, 1)
	dirty.value = true
	if (selectedIndex.value === idx) {
		selectedIndex.value = null
	} else if (selectedIndex.value !== null && selectedIndex.value > idx) {
		selectedIndex.value!--
	}
}

function moveTrack(idx: number, by: number) {
	const to = idx + by
	if (to < 0 || to >= tracks.value.length) return
	const moved = tracks.value.splice(idx, 1)
	tracks.value.splice(to, 0, ...moved)
	dirty.value = true
	if (selectedIndex.value === idx) selectedIndex.value = to
	else if (selectedIndex.value === to) selectedIndex.value = idx
}

function selectTrack(idx: number) {
	selectedIndex.value = idx
	const trk = tracks.value[idx]
	if(trk) {
		editModel.id = trk.id
		editModel.plugin_name = trk.plugin_name
		editModel.type = trk.type
		editModel.title = trk.title
		editModel.content = JSON.parse(JSON.stringify(trk.content || {})) // clone
	}
}

function cancelEdit() {
	if (selectedIndex.value !== null) selectTrack(selectedIndex.value)
	else {
		editModel.id = undefined
		editModel.plugin_name = undefined
		editModel.title = undefined
		editModel.content = {}
	}
}

function initProviders() {
	const px0 = apiJson(listPluginsUrl)
	const px1 = apiJson(listDatasourcesUrl)
	const px3 = px0.then(json => {
		plugins.value = structuredClone(json)
		pluginList.value = structuredClone(json)
	})
	.catch(ex => {
		console.error("fetch.pl.unhandled", ex)
		plugins.value = []
		pluginList.value = []
	})
	const px4 = px1.then(json2 => {
		dataSources.value = json2
	})
	.catch(ex => {
		console.error("fetch.ds.unhandled", ex)
		dataSources.value = []
	})
	return Promise.all([px3, px4])
}

// --- the playlists
/** Put a stored playlist into the working copy. */
function adopt(doc: any, keepSelection = false) {
	currentId.value = doc.id
	playlistName.value = doc.name
	docRev.value = doc._rev
	tracks.value = structuredClone(doc.items)
	dirty.value = false
	resetMessages()
	const keep = keepSelection ? selectedIndex.value : null
	selectedIndex.value = null
	if(keep !== null && keep < tracks.value.length) selectTrack(keep)
}
async function loadPlaylists(selectId?: string) {
	try {
		const json = await apiJson(`${PLAYLIST_URL}/list`)
		const all: any[] = json.playlists ?? []
		playlists.value = all.map(p => ({ id: p.id, name: p.name }))
		const target = all.find(p => p.id === selectId) ?? all[0]
		if(target) {
			adopt(target)
		}
		else {
			currentId.value = undefined
			playlistName.value = undefined
			docRev.value = undefined
			tracks.value = []
			selectedIndex.value = null
			dirty.value = false
		}
	}
	catch(err: any) {
		console.error('Error fetching playlists:', err)
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load the playlists: ${err.message || 'Unknown error'}`, life: 5000});
	}
}
async function openPlaylist(id: string) {
	await loadPlaylists(id)
}
/** Run an action that drops the working copy; ask first when it has changes that were not saved. */
function guard(action: () => void) {
	if(dirty.value) {
		pendingAction = action
		discardOpen.value = true
	}
	else {
		action()
	}
}
function onDiscardHide() {
	pendingAction = undefined
	selectKey.value++
}
function confirmDiscard() {
	discardOpen.value = false
	dirty.value = false
	const action = pendingAction
	pendingAction = undefined
	action?.()
}
function startNew() {
	nameDialogRename.value = false
	nameValue.value = ""
	nameOpen.value = true
}
function startRename() {
	nameDialogRename.value = true
	nameValue.value = playlistName.value ?? ""
	nameOpen.value = true
}
async function confirmName() {
	const name = nameValue.value.trim()
	if(!name) return
	saving.value = true
	try {
		if(nameDialogRename.value && currentId.value) {
			const rx = await apiPatch(`${PLAYLIST_URL}/${encodeURIComponent(currentId.value)}`, { name, _rev: docRev.value })
			// only the name changed in the store: the unsaved edits stay, on top of the new revision
			playlistName.value = rx.schedule.name
			docRev.value = rx.rev
			playlists.value = playlists.value.map(p => p.id === currentId.value ? { id: p.id, name: rx.schedule.name } : p)
		}
		else {
			const rx = await apiPost(PLAYLIST_URL, { name, items: [] })
			nameOpen.value = false
			await loadPlaylists(rx.id)
		}
		nameOpen.value = false
	}
	catch(ex: any) {
		if(ex instanceof ApiError && ex.status === 409) {
			nameOpen.value = false
			conflict.value = { message: "The playlist changed since it was loaded.", rev: undefined }
		}
		else {
			toast.add({severity:'error', summary: 'Error', detail: `Failed: ${ex.message || 'Unknown error'}`, life: 5000});
		}
	}
	finally {
		saving.value = false
	}
}
async function deletePlaylist() {
	if(!currentId.value || !docRev.value) return
	saving.value = true
	try {
		await apiDelete(`${PLAYLIST_URL}/${encodeURIComponent(currentId.value)}?rev=${encodeURIComponent(docRev.value)}`)
		toast.add({severity:'success', summary: 'Success', detail: 'Playlist deleted', life: 3000});
		deleteOpen.value = false
		dirty.value = false
		await loadPlaylists()
	}
	catch(ex: any) {
		deleteOpen.value = false
		if(ex instanceof ApiError && ex.status === 409) {
			conflict.value = { message: "The playlist changed since it was loaded; reload it before deleting.", rev: undefined }
		}
		else {
			toast.add({severity:'error', summary: 'Error', detail: `Failed to delete the playlist: ${ex.message || 'Unknown error'}`, life: 5000});
		}
	}
	finally {
		saving.value = false
	}
}
/** The stored form of the working copy: new tracks have no id yet, nothing else of ours goes along. */
function documentBody(rev: string|undefined) {
	return {
		name: playlistName.value,
		_rev: rev,
		items: tracks.value.map(t => {
			const { _rev, ...track } = t as PlaylistItem & { _rev?: string }
			return String(track.id).startsWith(NEW_PREFIX) ? (({ id, ...rest }) => rest)(track) : track
		})
	}
}
/** Save the whole playlist; `rev` is the revision it was loaded at (a stale one is a 409 the person can resolve). */
async function savePlaylist(rev: string|undefined) {
	if(!currentId.value) return
	saving.value = true
	resetMessages()
	try {
		const rx = await apiPut(`${PLAYLIST_URL}/${encodeURIComponent(currentId.value)}`, documentBody(rev))
		toast.add({severity:'success', summary: 'Success', detail: 'Playlist saved', life: 3000});
		adopt(rx.schedule, true)
	}
	catch(ex: any) {
		if(ex instanceof ApiError && ex.status === 409) {
			conflict.value = { message: ex.message, rev: typeof ex.body?.rev === "string" ? ex.body.rev : undefined }
		}
		else if(ex instanceof ApiError && ex.status === 422 && Array.isArray(ex.body?.errors)) {
			showServerErrors(ex.body.errors, ex.message)
		}
		else {
			toast.add({severity:'error', summary: 'Error', detail: `Failed to save the playlist: ${ex.message || 'Unknown error'}`, life: 5000});
		}
	}
	finally {
		saving.value = false
	}
}
/** A problem in a field of the selected track shows on that field; everything else is listed, naming its track. */
function showServerErrors(errors: { path?: unknown[], message?: string }[], fallback: string) {
	const onField: { path: unknown[], message: string }[] = []
	const listed: string[] = []
	for(const err of errors) {
		const path = err.path ?? []
		const index = path[0] === "items" ? Number(path[1]) : NaN
		const track = Number.isInteger(index) ? tracks.value[index] : undefined
		if(track && index === selectedIndex.value && path[2] === "content" && typeof path[3] === "string") {
			onField.push({ path: [path[3]], message: err.message ?? "" })
		}
		else {
			const where = track ? `Track "${track.title}": ` : ""
			listed.push(`${where}${path.slice(2).join(" / ")}${path.length > 2 ? ": " : ""}${err.message ?? fallback}`)
		}
	}
	const shown = onField.length > 0 ? (bf.value?.setServerErrors(onField) ?? 0) : 0
	if(shown < onField.length) listed.push(fallback)
	serverProblems.value = listed
}
/** Someone else changed the playlist: take their version (the unsaved edits are dropped). */
async function reloadPlaylist() {
	await loadPlaylists(currentId.value)
}
onMounted(() => {
	initProviders()
	.then(_ => {
		loadPlaylists()
	})
	.catch(ex => {
		console.error("initProviders.unhandled", ex)
	})
})
</script>
<style scoped>
.label-panel {
	width: 20rem;
}
.playlist-editor {
	padding: 0.5rem;
}

.layout {
	display: flex;
	gap: .5rem;
	margin-top: 0.5rem;
}

.track-list {
	width: 25rem;
	border: 1px solid #eee;
	border-radius: 4px;
	padding: 0.5rem;
	background: #fafafa;
	max-height: 70vh;
	overflow: auto;
}

.track-list ul {
	list-style: none;
	padding: 0;
	margin: 0;
}

.track-row {
	display: flex;
	align-items: center;
	gap: 0.5rem;
	padding: 0.4rem;
	border-radius: 4px;
	cursor: pointer;
}

.track-row:hover {
	background: #f5f5f5;
}

.track-row.selected {
	background: #eef7ff;
}

.color-swatch {
	width: 28px;
	height: 28px;
	border-radius: 4px;
	border: 1px solid rgba(0, 0, 0, 0.08);
}

.track-meta {
	flex: 1;
	display: flex;
	flex-direction: column;
}

.title {
	font-weight: 600;
}

.muted {
	color: #666;
	font-size: 0.85rem;
}

.actions {
	display: flex;
	gap: 0.25rem;
}
.selected {
	background: #eef7ff;
	border: 1px solid #cce4ff;
}
.track-editor {
	flex: 1;
	border: 1px solid #eee;
	border-radius: 4px;
	padding: 0.75rem;
	min-height: 200px;
	background: #fff;
}

.editor-card {
	display: flex;
	flex-direction: column;
	gap: 0.6rem;
}

.field {
	display: flex;
	flex-direction: column;
	gap: 0.25rem;
}

.editor-actions {
	display: flex;
	gap: 0.5rem;
	justify-content: flex-end;
	margin-top: 0.5rem;
}

.empty-state {
	color: #777;
	display: flex;
	align-items: center;
	justify-content: center;
	height: 100%;
}
</style>