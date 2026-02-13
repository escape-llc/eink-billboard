<template>
	<div class="playlist-editor">
		<Toolbar class="p-1">
			<template #start>
				<div style="font-size:150%">Playlists</div>
			</template>
			<template #end>
				<div class="mr-3 text-xl">{{ playlistName }}</div>
				<Button title="Add Track" icon="pi pi-plus" size="small" @click="addTrack" />
			</template>
		</Toolbar>

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
								<!--
								<Button icon="pi pi-pencil" size="small" class="p-button-text" @click.stop="editTrack(idx)" />
								-->
								<Button icon="pi pi-trash" size="small" severity="danger" class="p-button-text"
									@click.stop="removeTrack(idx)" />
							</div>
						</div>
					</li>
				</ul>
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
										<Button size="small" icon="pi pi-check" severity="success" :disabled="submitDisabled" @click="handleSubmit" />
										<Button size="small" icon="pi pi-times" severity="danger" @click="handleReset" />
									</InputGroup>
								</template>
							</Toolbar>
						</template>
						<template #group-header="slotProps">
							<h3 class="mb-0">{{ slotProps.label }}</h3>
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
	</div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, provide } from 'vue'
import { InputGroup, InputGroupAddon, Toolbar, Button, Dialog, Select, InputText } from 'primevue'
import BasicForm, { type ValidateEventData } from '../components/BasicForm.vue'
import type { PlaylistItem, PlaylistSchedule } from '../components/ScheduleDefs'
const API_URL = import.meta.env.VITE_API_URL
const bf = ref<InstanceType<typeof BasicForm>>()
const submitDisabled = ref(true)
const fieldNameWidth = "10rem";

const plugins = ref([])
const dataSources = ref([])
provide("settingsPluginsList", plugins)
provide("settingsDataSourcesList", dataSources)

const listPluginsUrl = `${API_URL}api/plugins/list`
const listDatasourcesUrl = `${API_URL}api/datasources/list`

type PluginProperty = { name: string; type: string; label: string }
type PluginDef = {
	id: string
	name: string
	color?: string
	instanceSettings: any // form def consumed by BasicForm
	properties: PluginProperty[]
}

let _rev:string|undefined = undefined
const pluginList = ref<PluginDef[]>([])
const tracks = ref<PlaylistItem[]>([])
const selectedIndex = ref<number | null>(null)
const playlistName = ref<string>()

// editing model separate from the track until Apply
const editModel = reactive<Record<string,any>>({} as any) // start with empty model, populate on track select

const selectedTrack = computed(() => (selectedIndex.value !== null ? tracks.value[selectedIndex.value] : null))
const selectedPlugin = computed(() => pluginList.value.find(p => p.id === editModel.plugin_name) || null)
const pluginOptions = computed(() => pluginList.value.map(p => ({ id: p.id, name: p.name })))

function uid(prefix = 't') { return `${prefix}_${Math.random().toString(36).slice(2, 9)}` }

const handleValidate = (e: ValidateEventData) => {
	console.log("validate", e)
	submitDisabled.value = !e.result.success
}
const submitForm = (data:any) => {
	console.log("submitForm", data)
	if(data.result.success) {
		const post = structuredClone(data.result.data)
		if(_rev) {
			post._rev = _rev
		}
		/*
		fetch(settingsUrl, {
			method: "PUT",
			headers: {
				"Content-Type": "application/json"
			},
			body: JSON.stringify(post)
		})
		.then(rx => {
			if(!rx.ok) {
				throw new Error(`Error ${rx.status}: ${rx.statusText}`)
			}
			return rx.json()
		})
		.then(jv => {
			console.log("submitForm.result", jv)
			if(jv.success) {
				_rev = jv.rev
			}
		})
		.catch(ex => {
			console.error("submitForm.unhandled", ex)
		})
		*/
	}
	else {
		console.warn("submitForm.invalid", data)
	}
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

// track operations
function addTrack() {
	const defaultPlugin = pluginList.value[0]?.id ?? 'plugin_0'
	const t: PlaylistItem = { id: uid('trk'), plugin_name: defaultPlugin, type:"PlaylistSchedule", title: "Untitled", content: {} }
	// populate default properties
	const p = pluginList.value.find(x => x.id === defaultPlugin)
	if (p) t.content = defaultPropertiesFromPlugin(p)
	tracks.value.push(t)
	selectTrack(tracks.value.length - 1)
}

function removeTrack(idx: number) {
	if (idx < 0 || idx >= tracks.value.length) return
	tracks.value.splice(idx, 1)
	if (selectedIndex.value === idx) {
		selectedIndex.value = null
	} else if (selectedIndex.value !== null && selectedIndex.value > idx) {
		selectedIndex.value!--
	}
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

function editTrack(idx: number) {
	selectTrack(idx)
}

function applyChanges() {
	if (selectedIndex.value === null) return
	const t = tracks.value[selectedIndex.value]
	t.plugin_name = editModel.plugin_name!
	t.type = "PluginSchedule"
	t.content = JSON.parse(JSON.stringify(editModel.content || {}))
	// update id if changed (rare)
	t.id = editModel.id ?? t.id
}

function cancelEdit() {
	if (selectedIndex.value !== null) selectTrack(selectedIndex.value)
	else {
		editModel.id = undefined
		editModel.plugin_name = undefined
		//editModel.type = "PluginSchedule"
		editModel.title = undefined
		editModel.content = {}
	}
}

function onFormChange(newValues: any) {
	editModel.content = newValues
}

function defaultPropertiesFromPlugin(p: PluginDef) {
	const props: Record<string, any> = {}
	for (const prop of p.properties) {
		// simple defaults based on type
		if (prop.type === 'number') props[prop.name] = 1
		else if (prop.type === 'boolean') props[prop.name] = false
		else props[prop.name] = ''
	}
	return props
}

function initProviders() {
	const px0 = fetch(listPluginsUrl).then(rx => rx.json())
	const px1 = fetch(listDatasourcesUrl).then(rx => rx.json())
	const px3 = px0.then(json => {
		console.log("plugins", json)
		plugins.value = structuredClone(json)
		pluginList.value = structuredClone(json)
	})
	.catch(ex => {
		console.error("fetch.pl.unhandled", ex)
		plugins.value = []
		pluginList.value = []
//		toast.add({severity:'error', summary: 'Error', detail: `Failed to load plugins list: ${ex.message || 'Unknown error'}`, life: 5000});
	})
	const px4 = px1.then(json2 => {
		console.log("datasources", json2)
		dataSources.value = json2
	})
	.catch(ex => {
		console.error("fetch.ds.unhandled", ex)
		dataSources.value = []
//		toast.add({severity:'error', summary: 'Error', detail: `Failed to load data sources list: ${ex.message || 'Unknown error'}`, life: 5000});
	})
	return Promise.all([px3, px4])
}
const playlistListUrl = `${API_URL}api/schedule/playlist/list`
let allPlaylists: PlaylistSchedule[] = []
function loadSchedules() {
	fetch(playlistListUrl).then(rx => rx.json()).then(json => {
		console.log("playlists", json)
		// ensure it doesnt get reactive
		allPlaylists = structuredClone(json.playlists)
		if(allPlaylists.length > 0) {
			const tx = allPlaylists[0]
			if(tx) {
				playlistName.value = tx.name
				tracks.value = structuredClone(tx.items)
			}
			else {
				playlistName.value = undefined
				tracks.value = []
			}
		}
		else {
			playlistName.value = undefined
			tracks.value = []
		}
	}).catch(err => {
		console.error('Error fetching playlists:', err)
		playlistName.value = undefined
		tracks.value = []
	})
}
onMounted(() => {
	initProviders()
	.then(_ => {
		loadSchedules()
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