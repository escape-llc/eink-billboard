<template>
	<Tabs value="0">
		<TabList>
			<Tab value="0">System</Tab>
			<Tab value="1">Display</Tab>
			<Tab value="2">Theme</Tab>
			<Tab value="3">Plugins</Tab>
		</TabList>
		<TabPanels>
			<TabPanel value="0">
				<SettingsForm
					:title="`System Settings`"
					:baseUrl="API_URL"
					:settingsUrl="settingsSystemUrl"
					:schemaUrl="schemaSystemUrl"
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
					:schemaUrl="schemaDisplayUrl"
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
					:schemaUrl="schemaThemeUrl"
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
					:schema="schemaPlugin"
					class="form"
					@load-settings="handlePluginSettings"
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
import { computed, onMounted, ref, watch } from 'vue';
import { useToast } from 'primevue';

const toast = useToast();

const API_URL = import.meta.env.VITE_API_URL
const settingsSystemUrl = `${API_URL}/api/settings/system`
const schemaSystemUrl = `${API_URL}/api/schemas/system`
const settingsThemeUrl = `${API_URL}/api/settings/theme`
const schemaThemeUrl = `${API_URL}/api/schemas/theme`
const settingsDisplayUrl = `${API_URL}/api/settings/display`
const schemaDisplayUrl = `${API_URL}/api/schemas/display`

const previewHue = ref(0)
const previewSaturation = ref(100)
const previewLightness = ref(50)

const plugins = ref([])
const selectedPlugin = ref(undefined)
const schemaPlugin = ref(undefined)
const settingsPluginUrl = computed(() => {
	return selectedPlugin.value ? `${API_URL}/api/plugins/${selectedPlugin.value.id}/settings` : ""
})

onMounted(() => {
	const listUrl = `${API_URL}/api/plugins/list`
	const px0 = fetch(listUrl).then(rx => rx.json())
	px0.then(json => {
		console.log("plugins", json)
		plugins.value = json
	})
	.catch(ex => {
		console.error("fetch.unhandled", ex)
	})
})

watch(selectedPlugin, (nv,ov) => {
	console.log("selectedPlugin", nv, ov)
	if(nv) {
//		form.value = nv.settings
		schemaPlugin.value = nv.settings
	}
})

const handlePluginSettings = (data:any) => {
	console.log("plugin settings", data)
	if(data.success === false) {
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load plugin settings: ${data.message || 'Unknown error'}`, life: 5000});
	}
}
const handleThemeSettings = (data:any) => {
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