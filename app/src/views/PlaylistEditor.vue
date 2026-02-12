<template>
	<div class="playlist-editor">
		<Toolbar class="p-1">
			<template #start>
				<div style="font-size:150%">Playlists</div>
			</template>
			<template #end>
				<Button title="Add Track" icon="pi pi-plus" class="p-button-sm" @click="addTrack" />
			</template>
		</Toolbar>

		<div class="layout">
			<div class="track-list">
				<ul>
					<li v-for="(t, idx) in tracks" :key="t.id" :class="{ selected: selectedIndex === idx }">
						<div class="track-row" @click="selectTrack(idx)">
							<div class="color-swatch" :style="{ 'background-color': pluginColor(t.plugin_name) }"></div>
							<div class="track-meta">
								<div class="title">{{ pluginName(t.plugin_name) || 'Unknown Plugin' }}</div>
							</div>
							<div class="actions">
								<Button icon="pi pi-pencil" class="p-button-text p-button-sm" @click.stop="editTrack(idx)" />
								<Button icon="pi pi-trash" class="p-button-text p-button-sm p-button-danger"
									@click.stop="removeTrack(idx)" />
							</div>
						</div>
					</li>
				</ul>
			</div>

			<div class="track-editor">
				<div v-if="selectedTrack" class="editor-card">
					<BasicForm ref="bf" v-if="selectedPlugin" :baseUrl="API_URL" :form="selectedPlugin.instanceSettings" :initialValues="editModel.properties"
						@validate="handleValidate" @submit="submitForm">
						<template #header>
							<Toolbar style="width:100%" class="p-1 mt-2">
								<template #start>
									<div style="font-weight: bold;font-size:150%">Item Settings</div>
								</template>
								<template #end>
									<InputGroup>
										<Button size="small" icon="pi pi-check" severity="success" :disabled="submitDisabled" @click="handleSubmit" />
										<Button size="small" icon="pi pi-times" severity="danger" @click="handleReset" />
									</InputGroup>
								</template>
							</Toolbar>
							<InputGroup>
								<InputGroupAddon>
									<label :style="{'width': fieldNameWidth, 'max-width': fieldNameWidth }" style="flex-shrink:0;flex-grow:1">Plugin</label>
								</InputGroupAddon>
								<Select :options="pluginOptions" optionLabel="name" optionValue="id" v-model="editModel.plugin_name" />
							</InputGroup>
						</template>
						<template #group-header="slotProps">
							<h3 class="mb-0">{{ slotProps.label }}</h3>
						</template>
					</BasicForm>

					<div class="editor-actions">
						<Button label="Apply" icon="pi pi-check" class="p-button-success" :disabled="submitDisabled" @click="applyChanges" />
						<Button label="Cancel" icon="pi pi-times" class="p-button-secondary" @click="cancelEdit" />
					</div>
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
import { InputGroup, InputGroupAddon, Toolbar, Button, Dialog, Select, InputNumber } from 'primevue'
import BasicForm, { type ValidateEventData } from '../components/BasicForm.vue'
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
type Track = {
	id: string
	type: string
	plugin_name: string
	properties: Record<string, any>
}

let _rev:string|undefined = undefined
const pluginList = ref<PluginDef[]>([])
const tracks = ref<Track[]>([])
const selectedIndex = ref<number | null>(null)

// editing model separate from the track until Apply
const editModel = reactive<{ id?: string; plugin_name?: string; properties: Record<string, any> }>({
	id: undefined,
	plugin_name: undefined,
	properties: {}
})

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
	if(data.valid) {
		const post = structuredClone(data.values)
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
	bf.value?.reset()
}
const handleSubmit = () => {
	bf.value?.submit()
}

// color wheel assignment
function assignColors(plugs: PluginDef[]) {
	const leng = plugs.length || 1
	for (let ix = 0; ix < plugs.length; ix++) {
		const hue = Math.round((ix * 360) / leng)
		plugs[ix].color = `hsl(${hue} 70% 60%)`
	}
}

// helpers
function pluginName(id?: string) {
	const p = pluginList.value.find(x => x.id === id)
	return p ? p.name : null
}
function pluginColor(id?: string) {
	const p = pluginList.value.find(x => x.id === id)
	return p ? p.color : '#ddd'
}

// track operations
function addTrack() {
	const defaultPlugin = pluginList.value[0]?.id ?? 'plugin_0'
	const t: Track = { id: uid('trk'), plugin_name: defaultPlugin, type:"PlaylistSchedule", properties: {} }
	// populate default properties
	const p = pluginList.value.find(x => x.id === defaultPlugin)
	if (p) t.properties = defaultPropertiesFromPlugin(p)
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
	const t = tracks.value[idx]
	editModel.id = t.id
	editModel.plugin_name = t.plugin_name
	editModel.properties = JSON.parse(JSON.stringify(t.properties || {})) // clone
}

function editTrack(idx: number) {
	selectTrack(idx)
}

function applyChanges() {
	if (selectedIndex.value === null) return
	const t = tracks.value[selectedIndex.value]
	t.plugin_name = editModel.plugin_name!
	t.type = "PluginSchedule"
	t.properties = JSON.parse(JSON.stringify(editModel.properties))
	// update id if changed (rare)
	t.id = editModel.id ?? t.id
}

function cancelEdit() {
	if (selectedIndex.value !== null) selectTrack(selectedIndex.value)
	else {
		editModel.id = undefined
		editModel.plugin_name = undefined
		editModel.properties = {}
	}
}

function onFormChange(newValues: any) {
	editModel.properties = newValues
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
		plugins.value = json
	})
	.catch(ex => {
		console.error("fetch.pl.unhandled", ex)
//		toast.add({severity:'error', summary: 'Error', detail: `Failed to load plugins list: ${ex.message || 'Unknown error'}`, life: 5000});
	})
	const px4 = px1.then(json2 => {
		console.log("datasources", json2)
		dataSources.value = json2
	})
	.catch(ex => {
		console.error("fetch.ds.unhandled", ex)
//		toast.add({severity:'error', summary: 'Error', detail: `Failed to load data sources list: ${ex.message || 'Unknown error'}`, life: 5000});
	})
	return Promise.all([px3, px4])
}
// bootstrap a sample plugin list if none provided
onMounted(() => {
	initProviders()
	// create 6 sample plugins with 3 made-up properties each
	const samples: PluginDef[] = Array.from({ length: 6 }).map((_, i) => {
		const id = `plugin_${i + 1}`
		const name = `Plugin ${String.fromCharCode(65 + i)}`
		const properties: PluginProperty[] = [
			{ name: 'level', type: 'number', label: 'Level' },
			{ name: 'mode', type: 'string', label: 'Mode' },
			{ name: 'enabled', type: 'boolean', label: 'Enabled' },
		]
		// build a minimal instanceSettings form definition compatible with BasicForm
		const instanceSettings = {
			fields: properties.map(p => ({ name: p.name, type: p.type, label: p.label }))
		}
		return { id, name, properties, instanceSettings } as PluginDef
	})
	const listUrl = `${API_URL}api/plugins/list`
	fetch(listUrl).then(rx => rx.json()).then(json => {
		pluginList.value = json
		assignColors(pluginList.value)
		// sample tracks
		tracks.value = pluginList.value.map((p, idx) => ({
			id: uid(`trk${idx}`),
			type:"PlaylistSchedule",
			plugin_name: p.id,
			properties: []
		}))
	}).catch(err => {
		console.error('Error fetching plugins:', err)
		pluginList.value = samples
		assignColors(pluginList.value)
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