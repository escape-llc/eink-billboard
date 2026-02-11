<template>
	<Tabs value="0">
		<TabList>
			<Tab value="0">System</Tab>
			<Tab value="1">Display</Tab>
			<Tab value="2">Theme</Tab>
			<Tab value="3">Plugins</Tab>
			<Tab value="4">Data Sources</Tab>
		</TabList>
		<TabPanels>
			<TabPanel value="0">
				<SettingsForm
					:title="`System Settings`"
					:baseUrl="API_URL"
					:settingsUrl="settingsSystemUrl"
					:settings="settingsSystem"
					:schema="schemaSystem"
					class="form"
					@validate="handleValidate"
					@submit="submitForm"
					/>
			</TabPanel>
			<TabPanel value="1">
				<SettingsForm
					:title="`Display Settings`"
					:baseUrl="API_URL"
					:settingsUrl="settingsDisplayUrl"
					:settings="settingsDisplay"
					:schema="schemaDisplay"
					class="form"
					@validate="handleValidate"
					@submit="submitForm"
					/>
			</TabPanel>
			<TabPanel value="2">
				<SettingsForm
					title="Theme Settings"
					:baseUrl="API_URL"
					:settingsUrl="settingsThemeUrl"
					:settings="settingsTheme"
					:schema="schemaTheme"
					class="form"
					@load-settings="handleThemeSettings"
					@validate="handleThemeValidate"
					@submit="submitForm"
					/>
				<div style="text-align: center">
					<h2>Theme Colors</h2>
					<div class="swatch-table">
						<div class="swatch-label">Primary</div>
						<div class="swatch" :style="`background-color:hsl(${previewHue},${previewSaturation}%,${previewLightness}%)`"></div>
						<div class="swatch-label">Secondary 1</div>
						<div class="swatch" :style="`background-color:hsl(${(previewHue + 180) % 360},${previewSaturation}%,${previewLightness}%)`"></div>
						<div class="swatch-label">Secondary 2</div>
						<div class="swatch" :style="`background-color:hsl(${(previewHue + 120) % 360},${previewSaturation}%,${previewLightness}%)`"></div>
					</div>
				</div>
			</TabPanel>
			<TabPanel value="3">
				<SettingsForm
					:title="`Plugin Settings`"
					:baseUrl="API_URL"
					:settingsUrl="settingsPluginUrl"
					:settings="settingsPlugin"
					:schema="schemaPlugin"
					class="form"
					@validate="handleValidate"
					@submit="submitForm"
					>
					<template #tb-center>
						<Select :options="plugins" v-model="selectedPlugin" style="width:20rem">
							<template #value="slotProps">
								<div v-if="slotProps.value">{{ slotProps.value.id }} ({{ slotProps.value.version }})</div>
							</template>
							<template #option="slotProps">
								<div class="flex flex-column">
									<div>{{ slotProps.option.id }} ({{ slotProps.option.version }})</div>
									<div style="max-width:17rem">{{ slotProps.option.description }}</div>
								</div>
							</template>
						</Select>
					</template>
					<template #header-end>
						<div v-if="selectedPlugin" class="m-3" style="display:grid;width:100%;place-items:center;grid-template-columns: repeat(5,1fr);grid-template-rows:repeat(2,fr)">
							<div class="plugin-label" style="grid-row:1;grid-column:1">id</div>
							<div style="grid-row:2;grid-column:1">{{ selectedPlugin.id }}</div>
							<div class="plugin-label" style="grid-row:1;grid-column:2">version</div>
							<div style="grid-row:2;grid-column:2">{{ selectedPlugin.version }}</div>
							<div class="plugin-label" style="grid-row:1;grid-column:3">enabled</div>
							<div style="grid-row:2;grid-column:3"><i class="pi" :class="selectedPlugin.disabled ? 'pi-times' : 'pi-check'"></i></div>
							<div class="plugin-label" style="grid-row:1;grid-column:4">description</div>
							<div style="grid-row:2;grid-column:4">{{ selectedPlugin.description }}</div>
							<div class="plugin-label" style="grid-row:1;grid-column:5">features</div>
							<div v-if="selectedPlugin.features" class="flex flex-row" style="grid-row:2;grid-column:5">
								<template v-for="feature in selectedPlugin.features">
									<Tag class="mr-1 ml-1" :value="feature">{{ feature }}</Tag>
								</template>
							</div>
							<div v-else>-</div>
						</div>
					</template>
				</SettingsForm>
			</TabPanel>
			<TabPanel value="4">
				<SettingsForm
					:title="`Data Source Settings`"
					:baseUrl="API_URL"
					:settingsUrl="settingsDatasourceUrl"
					:settings="settingsDatasource"
					:schema="schemaDatasource"
					class="form"
					@validate="handleValidate"
					@submit="submitForm"
					>
					<template #tb-center>
						<Select :options="dataSources" v-model="selectedDatasource" style="width:20rem">
							<template #value="slotProps">
								<div v-if="slotProps.value">{{ slotProps.value.id }} ({{ slotProps.value.version }})</div>
							</template>
							<template #option="slotProps">
								<div class="flex flex-column">
									<div>{{ slotProps.option.id }} ({{ slotProps.option.version }})</div>
									<div style="max-width:17rem">{{ slotProps.option.description }}</div>
								</div>
							</template>
						</Select>
					</template>
					<template #header-end>
						<div v-if="selectedDatasource" class="m-3" style="display:grid;width:100%;place-items:center;grid-template-columns: repeat(5,1fr);grid-template-rows:repeat(2,fr)">
							<div class="plugin-label" style="grid-row:1;grid-column:1">id</div>
							<div style="grid-row:2;grid-column:1">{{ selectedDatasource.id }}</div>
							<div class="plugin-label" style="grid-row:1;grid-column:2">version</div>
							<div style="grid-row:2;grid-column:2">{{ selectedDatasource.version }}</div>
							<div class="plugin-label" style="grid-row:1;grid-column:3">enabled</div>
							<div style="grid-row:2;grid-column:3"><i class="pi" :class="selectedDatasource.disabled ? 'pi-times' : 'pi-check'"></i></div>
							<div class="plugin-label" style="grid-row:1;grid-column:4">description</div>
							<div style="grid-row:2;grid-column:4">{{ selectedDatasource.description }}</div>
							<div class="plugin-label" style="grid-row:1;grid-column:5">features</div>
							<div v-if="selectedDatasource.features" class="flex flex-row" style="grid-row:2;grid-column:5">
								<template v-for="feature in selectedDatasource.features">
									<Tag class="mr-1 ml-1" :value="feature">{{ feature }}</Tag>
								</template>
							</div>
							<div v-else>-</div>
						</div>
					</template>
				</SettingsForm>
			</TabPanel>
		 </TabPanels>
		</Tabs>
</template>
<script setup lang="ts">

import Tabs from 'primevue/tabs';
import TabList from 'primevue/tablist';
import Tab from 'primevue/tab';
import TabPanels from 'primevue/tabpanels';
import TabPanel from 'primevue/tabpanel';
import Select from 'primevue/select';
import Tag from 'primevue/tag';

import type { ValidateEventData } from "../components/BasicForm.vue"
import SettingsForm from "../components/SettingsForm.vue"
import { computed, onMounted, provide, ref, toRaw, watch, type Ref } from 'vue';
import { useToast } from 'primevue';

const toast = useToast();

const API_URL = import.meta.env.VITE_API_URL
const settingsSystemUrl = `${API_URL}api/settings/system`
const schemaSystemUrl = `${API_URL}api/schemas/system`
const schemaSystem = ref<any>(undefined)
const settingsSystem = ref<any>(undefined)
const settingsThemeUrl = `${API_URL}api/settings/theme`
const schemaThemeUrl = `${API_URL}api/schemas/theme`
const schemaTheme = ref<any>(undefined)
const settingsTheme = ref<any>(undefined)
const settingsDisplayUrl = `${API_URL}api/settings/display`
const schemaDisplayUrl = `${API_URL}api/schemas/display`
const schemaDisplay = ref<any>(undefined)
const settingsDisplay = ref<any>(undefined)

const previewHue = ref(0)
const previewSaturation = ref(100)
const previewLightness = ref(50)

const plugins = ref([])
const dataSources = ref([])
const selectedPlugin = ref<any>(undefined)
const schemaPlugin = ref<any>(undefined)
const settingsPlugin = ref<any>(undefined)
const settingsPluginUrl = computed(() => {
	return selectedPlugin.value ? `${API_URL}api/plugins/${selectedPlugin.value.id}/settings` : ""
})

const selectedDatasource = ref<any>(undefined)
const schemaDatasource = ref<any>(undefined)
const settingsDatasource = ref<any>(undefined)
const settingsDatasourceUrl = computed(() => {
	return selectedDatasource.value ? `${API_URL}api/datasources/${selectedDatasource.value.id}/settings` : ""
})

provide("settingsPluginsList", plugins)
provide("settingsDataSourcesList", dataSources)

const listPluginsUrl = `${API_URL}api/plugins/list`
const listDatasourcesUrl = `${API_URL}api/datasources/list`

function downloadToRef(url:string, vref: Ref<any>, errv: any = undefined) {
	fetch(url).then(rx => rx.json()).then(data => {
		console.log("downloadToRef", data)
		vref.value = data
	})
	.catch(ex => {
		console.error("downloadToRef.unhandled", ex)
		vref.value = errv
	})
}
function fetchSettings(url:string, vref: Ref<any>, schema:any) {
	fetch(url)
	.then(rx => ({ status: rx.status, json: rx.json() }))
	.then(data => {
		console.log("fetchSettings", data)
		if(data.status === 200) {
			data.json.then(dx => {
				vref.value = dx
			})
		}
		else {
			const defv = toRaw(schema.settings.default)
			console.log("default", defv)
			vref.value = structuredClone(defv)
		}
	})
	.catch(ex => {
		console.error("fetchSettings.unhandled", ex)
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load settings: ${ex.message || 'Unknown error'}`, life: 5000});
	})
}
onMounted(() => {
	const px0 = fetch(listPluginsUrl).then(rx => rx.json())
	const px1 = fetch(listDatasourcesUrl).then(rx => rx.json())
	const px3 = px0.then(json => {
		console.log("plugins", json)
		plugins.value = json
	})
	.catch(ex => {
		console.error("fetch.pl.unhandled", ex)
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load plugins list: ${ex.message || 'Unknown error'}`, life: 5000});
	})
	const px4 = px1.then(json2 => {
		console.log("datasources", json2)
		dataSources.value = json2
	})
	.catch(ex => {
		console.error("fetch.ds.unhandled", ex)
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load data sources list: ${ex.message || 'Unknown error'}`, life: 5000});
	})
	Promise.all([px3, px4]).then(_ => {
		downloadToRef(schemaThemeUrl, schemaTheme)
		downloadToRef(schemaDisplayUrl, schemaDisplay)
		downloadToRef(schemaSystemUrl, schemaSystem)
		// TODO account for these not being persisted
		downloadToRef(settingsSystemUrl, settingsSystem)
		downloadToRef(settingsDisplayUrl, settingsDisplay)
		downloadToRef(settingsThemeUrl, settingsTheme)
	})
})

watch(selectedPlugin, (nv,ov) => {
	console.log("selectedPlugin", nv, ov)
	if(nv) {
		if(nv.settings.schema.properties.length > 0) {
			schemaPlugin.value = nv.settings
			fetchSettings(settingsPluginUrl.value, settingsPlugin, nv)
		}
		else {
			schemaPlugin.value = undefined
			settingsPlugin.value = undefined
		}
	}
})
watch(selectedDatasource, (nv,ov) => {
	console.log("selectedDatasource", nv, ov)
	if(nv) {
		schemaDatasource.value = nv.settings
		if(nv.settings.schema.properties.length > 0) {
			fetchSettings(settingsDatasourceUrl.value, settingsDatasource, nv)
		}
		else {
			settingsDatasource.value = undefined
		}
	}
})
const handleThemeSettings = (data:any) => {
	if(!data) return;
	if("hue" in data) {
		previewHue.value = data.hue
	}
	if("saturation" in data) {
		previewSaturation.value = data.saturation
	}
	if("lightness" in data) {
		previewLightness.value = data.lightness
	}
}
const handleValidate = (e: ValidateEventData) => {
	console.log("validate", e)
}
const submitForm = (data:any) => {
	console.log("submitForm", data)
	if(data.error) {
		toast.add({severity:'error', summary: 'Error', detail: `Failed to save settings: ${data.error.message || 'Unknown error'}`, life: 5000});
	}
	else {
		toast.add({severity:'success', summary: 'Success', detail: `Settings saved successfully`, life: 3000});
	}
}
const handleThemeValidate = (e: ValidateEventData) => {
	console.log("theme.validate", e)
	if(e.result.success) {
		const data = e.result.data
		if("hue" in data) {
			previewHue.value = data.hue
		}
		if("saturation" in data) {
			previewSaturation.value = data.saturation
		}
		if("lightness" in data) {
			previewLightness.value = data.lightness
		}
	}
}
</script>
<style scoped>
.plugin-label {
	font-weight: bold;
	font-size: 120%;
}
.form {
	width: 50%;
	margin: auto;
}
.swatch-table {
	display:flex;
	flex-direction: row;
	gap: 1rem;
	flex-wrap:wrap;
	margin-top:.5rem;
	justify-content: center;
	align-items: center;
}
.swatch-label {
	margin-left: .5rem;
	font-size: 120%;
}
.swatch {
	width: 3rem;
	height: 3rem;
}
</style>