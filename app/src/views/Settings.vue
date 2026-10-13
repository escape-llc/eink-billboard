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
					@submit="submitForm"
					/>
				<PasswordForm />
			</TabPanel>
			<TabPanel value="1">
				<SettingsForm
					:title="`Display Settings`"
					:baseUrl="API_URL"
					:settingsUrl="settingsDisplayUrl"
					:settings="settingsDisplay"
					:schema="schemaDisplay"
					class="form"
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
					<!-- every role of the palette, as the device computes it (POST /api/theme/palette), for the values in the form -->
					<table class="palette" data-testid="palette">
						<thead><tr><th></th><th v-for="c in PALETTE_COLUMNS" :key="c.key">{{ c.title }}</th></tr></thead>
						<tbody>
							<tr v-for="row in PALETTE_ROWS" :key="row.key">
								<th>{{ row.title }}</th>
								<td v-for="c in PALETTE_COLUMNS" :key="c.key">
									<div class="swatch" :data-role="roleName(row.key, c.key)" :title="roleName(row.key, c.key)"
										:style="{ backgroundColor: paletteColors[roleName(row.key, c.key)] ?? 'transparent' }"></div>
								</td>
							</tr>
						</tbody>
					</table>
					<div class="page-row">Page background <span class="page-swatch" data-role="bg-page" :style="{ backgroundColor: paletteColors['bg-page'] ?? 'transparent' }"></span>
						Overlay outline <span class="page-swatch" data-role="text-outline" :style="{ backgroundColor: paletteColors['text-outline'] ?? 'transparent' }"></span></div>
					<h2>Theme Preview</h2>
					<!-- a page and a dark page in the palette, fonts and text size of the form, built from the same roles the device's pages use -->
					<div class="mock-row" data-testid="mockup" :style="mockVars">
						<div class="mock mock-light">
							<div class="mock-kicker">Thursday</div>
							<div class="mock-title">Sunday, October 11</div>
							<div class="mock-split">
								<div class="mock-now">
									<div class="mock-sun"></div>
									<div>
										<div class="mock-temp">14°</div>
										<div class="mock-small">Scattered clouds</div>
									</div>
								</div>
								<div class="mock-month">
									<span v-for="d in 14" :key="d" :class="{ today: d === 6 }">{{ d + 4 }}</span>
								</div>
							</div>
							<div class="mock-events">
								<div class="mock-event mock-event-1">10:00 Dentist</div>
								<div class="mock-event mock-event-2">13:30 Team lunch</div>
							</div>
						</div>
						<div class="mock mock-dark">
							<div class="mock-kicker">Next up</div>
							<div class="mock-title">Quarter-hour clock</div>
							<div class="mock-small">The text size and fonts above apply to every page, light or dark.</div>
							<div class="mock-bar"></div>
						</div>
					</div>
					<h2>Theme Typography</h2>
					<!-- the fonts are the ones the device draws with (served by /api/fonts), so the sample is what the pages will look like -->
					<component :is="'style'">{{ fontFaces }}</component>
					<div class="type-sample" data-testid="type-sample" :style="{ fontFamily: fontStack(previewFontBody), fontSize: `${previewFontScale}em` }">
						<div class="type-heading" :style="{ fontFamily: fontStack(previewFontHeading || previewFontBody) }">The quick brown fox</div>
						<div>Jumps over the lazy dog, 0123456789</div>
						<div class="type-overlay" data-testid="type-overlay" :style="{ fontFamily: fontStack(previewFontOverlay || previewFontHeading || previewFontBody) }">Friday, October 9 (overlay)</div>
					</div>
				</div>
			</TabPanel>
			<TabPanel value="3">
				<SettingsForm
					:title="`Plugin Settings`"
					:baseUrl="API_URL"
					:settingsUrl="settingsPluginUrl"
					:owner="selectedPlugin ? { kind: 'plugin', id: selectedPlugin.id } : undefined"
					:settings="settingsPlugin"
					:schema="schemaPlugin"
					class="form"
					@submit="submitForm"
					>
					<template #tb-center>
						<Select :options="plugins" optionLabel="id" v-model="selectedPlugin" style="width:20rem">
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
					:owner="selectedDatasource ? { kind: 'datasource', id: selectedDatasource.id } : undefined"
					:settings="settingsDatasource"
					:schema="schemaDatasource"
					class="form"
					@submit="submitForm"
					>
					<template #tb-center>
						<Select :options="dataSources" optionLabel="id" v-model="selectedDatasource" style="width:20rem">
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
import { apiJson, apiPost, ApiError } from "../components/ApiClient"

import Tabs from 'primevue/tabs';
import TabList from 'primevue/tablist';
import Tab from 'primevue/tab';
import TabPanels from 'primevue/tabpanels';
import TabPanel from 'primevue/tabpanel';
import Select from 'primevue/select';
import Tag from 'primevue/tag';

import type { ValidateEventData } from "../components/BasicForm.vue"
import SettingsForm from "../components/SettingsForm.vue"
import PasswordForm from "../components/PasswordForm.vue"
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

const previewScheme = ref("complementary")
const previewBackground = ref("white")
const previewHue = ref(0)
const previewSaturation = ref(100)
const previewLightness = ref(50)
const previewFontBody = ref("Jost")
const previewFontHeading = ref<string|null>(null)
const previewFontOverlay = ref<string|null>(null)
const previewFontScale = ref(1)
// the families the device ships, loaded under names of their own so they cannot be mistaken for a font of the computer
const FONTS = [["Jost", ["normal", "bold"]], ["Napoli", ["normal"]], ["Dogica", ["normal", "bold"]], ["DS-Digital", ["normal"]]] as const
const fontFaces = FONTS.flatMap(([family, weights]) => weights.map(weight =>
	`@font-face { font-family: "eink-${family}"; font-weight: ${weight}; src: url("${API_URL}api/fonts/${family}?weight=${weight}") format("truetype"); }`)).join(" ")
const fontStack = (family: string) => `"eink-${family}", sans-serif`
// the palette: the roles are the CSS classes of themes.css (text-primary, bg-secondary-1-accent, ...), computed by the server from the form's values
const PALETTE_COLUMNS = [{ key: "primary", title: "Primary" }, { key: "secondary-1", title: "Secondary 1" }, { key: "secondary-2", title: "Secondary 2" }]
const PALETTE_ROWS = [{ key: "text", title: "Text" }, { key: "text|light", title: "Text, light" }, { key: "bg", title: "Background" }, { key: "bg|accent", title: "Accent" }, { key: "bg|dark", title: "Background, dark" }]
// "text|light" and "primary" make "text-primary-light"
const roleName = (row: string, column: string) => { const [kind, tone] = row.split("|"); return `${kind}-${column}${tone ? `-${tone}` : ""}` }
const paletteColors = ref<Record<string, string>>({})
// the mock-up reads the palette through variables, named like the roles
const mockVars = computed(() => ({
	...Object.fromEntries(Object.entries(paletteColors.value).map(([role, color]) => [`--m-${role}`, color])),
	"--m-body": fontStack(previewFontBody.value),
	"--m-heading": fontStack(previewFontHeading.value || previewFontBody.value),
	"--m-scale": String(previewFontScale.value),
}))
let paletteTimer: ReturnType<typeof setTimeout> | undefined
function refreshPalette() {
	if (paletteTimer) clearTimeout(paletteTimer)
	paletteTimer = setTimeout(() => {
		apiPost<{ roles: { name: string, color: string }[] }>(`${API_URL}api/theme/palette`, { theme: previewScheme.value, hue: previewHue.value, saturation: previewSaturation.value, lightness: previewLightness.value, background: previewBackground.value })
			.then(answer => { paletteColors.value = Object.fromEntries(answer.roles.map(r => [r.name, r.color])) })
			.catch(() => { /* the swatches keep what they showed */ })
	}, 120)
}
onMounted(refreshPalette)

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
	apiJson(url).then(data => {
		vref.value = data
	})
	.catch(ex => {
		console.error("downloadToRef.unhandled", ex)
		vref.value = errv
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load: ${ex.message || 'Unknown error'}`, life: 5000});
	})
}
function fetchSettings(url:string, vref: Ref<any>, schema:any) {
	apiJson(url)
	.then(data => {
		vref.value = data
	})
	.catch(ex => {
		if(ex instanceof ApiError && ex.status === 404) {
			// nothing stored yet: start from the defaults in the schema
			const defv = toRaw(schema.settings.default)
			vref.value = structuredClone(defv)
			return
		}
		console.error("fetchSettings.unhandled", ex)
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load settings: ${ex.message || 'Unknown error'}`, life: 5000});
	})
}
onMounted(() => {
	const px0 = apiJson(listPluginsUrl)
	const px1 = apiJson(listDatasourcesUrl)
	const px3 = px0.then(json => {
		plugins.value = json
	})
	.catch(ex => {
		console.error("fetch.pl.unhandled", ex)
		toast.add({severity:'error', summary: 'Error', detail: `Failed to load plugins list: ${ex.message || 'Unknown error'}`, life: 5000});
	})
	const px4 = px1.then(json2 => {
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
		// a settings file that was never saved is a 404; fetchSettings then starts from the schema's `default`
		downloadToRef(settingsSystemUrl, settingsSystem)
		downloadToRef(settingsDisplayUrl, settingsDisplay)
		downloadToRef(settingsThemeUrl, settingsTheme)
	})
})

// a plugin or data source with no settings block, or an empty one, has nothing to edit
const hasSettings = (item: any): boolean => (item?.settings?.schema?.properties?.length ?? 0) > 0
watch(selectedPlugin, (nv) => {
	if(nv) {
		if(hasSettings(nv)) {
			schemaPlugin.value = nv.settings
			fetchSettings(settingsPluginUrl.value, settingsPlugin, nv)
		}
		else {
			schemaPlugin.value = undefined
			settingsPlugin.value = undefined
		}
	}
})
watch(selectedDatasource, (nv) => {
	if(nv) {
		if(hasSettings(nv)) {
			schemaDatasource.value = nv.settings
			fetchSettings(settingsDatasourceUrl.value, settingsDatasource, nv)
		}
		else {
			schemaDatasource.value = undefined
			settingsDatasource.value = undefined
		}
	}
})
const handleThemeSettings = (data:any) => {
	if(!data) return;
	if(typeof data.theme === "string") {
		previewScheme.value = data.theme
	}
	if("hue" in data) {
		previewHue.value = data.hue
	}
	if("saturation" in data) {
		previewSaturation.value = data.saturation
	}
	if("lightness" in data) {
		previewLightness.value = data.lightness
	}
	if("fontBody" in data && typeof data.fontBody === "string") {
		previewFontBody.value = data.fontBody
	}
	if("fontHeading" in data) {
		previewFontHeading.value = typeof data.fontHeading === "string" ? data.fontHeading : null
	}
	if("fontOverlay" in data) {
		previewFontOverlay.value = typeof data.fontOverlay === "string" ? data.fontOverlay : null
	}
	if(typeof data.fontScale === "number") {
		previewFontScale.value = data.fontScale
	}
	previewBackground.value = typeof data.background === "string" ? data.background : "white"
	refreshPalette()
}
const submitForm = (data:any) => {
	if(data.handled) {
		return
	}
	if(data.error) {
		toast.add({severity:'error', summary: 'Error', detail: `Failed to save settings: ${data.error.message || 'Unknown error'}`, life: 5000});
	}
	else {
		toast.add({severity:'success', summary: 'Success', detail: `Settings saved successfully`, life: 3000});
	}
}
const handleThemeValidate = (e: ValidateEventData) => {
	if(e.result.success) {
		const data = e.result.data
		if(typeof data.theme === "string") {
			previewScheme.value = data.theme
		}
		if("hue" in data) {
			previewHue.value = data.hue
		}
		if("saturation" in data) {
			previewSaturation.value = data.saturation
		}
		if("lightness" in data) {
			previewLightness.value = data.lightness
		}
		if("fontBody" in data && typeof data.fontBody === "string") {
			previewFontBody.value = data.fontBody
		}
		if("fontHeading" in data) {
			previewFontHeading.value = typeof data.fontHeading === "string" ? data.fontHeading : null
		}
		if("fontOverlay" in data) {
			previewFontOverlay.value = typeof data.fontOverlay === "string" ? data.fontOverlay : null
		}
		if(typeof data.fontScale === "number") {
			previewFontScale.value = data.fontScale
		}
		previewBackground.value = typeof data.background === "string" ? data.background : "white"
		refreshPalette()
	}
}
</script>
<style scoped>
.plugin-label {
	font-weight: bold;
	font-size: 120%;
}
.form {
	/* the whole tab, up to a width where a row of fields is still easy to read */
	width: 100%;
	max-width: 72rem;
	margin: auto;
}
.palette {
	margin: .5rem auto;
	border-collapse: separate;
	border-spacing: .4rem;
}
.palette th {
	font-weight: normal;
	font-size: .9rem;
	text-align: left;
}
.palette thead th {
	text-align: center;
}
.palette .swatch {
	width: 5rem;
	height: 2.5rem;
	border: 1px solid var(--p-content-border-color);
}
.mock-row {
	display: flex;
	gap: 1rem;
	flex-wrap: wrap;
	justify-content: center;
	margin: .5rem auto 1rem;
}
.mock {
	box-sizing: border-box;
	width: 24rem;
	max-width: 100%;
	aspect-ratio: 5 / 3;
	padding: 1rem 1.25rem;
	display: flex;
	flex-direction: column;
	gap: calc(0.4 * var(--m-unit));
	overflow: hidden;
	text-align: left;
	font-family: var(--m-body);
	--m-unit: calc(.85rem * var(--m-scale));
	font-size: var(--m-unit);
	border: 1px solid var(--p-content-border-color);
}
.mock-light {
	background: var(--m-bg-page);
	color: var(--m-text-secondary-2);
}
.mock-dark {
	background: var(--m-bg-primary-dark);
	color: var(--m-text-secondary-1-light);
}
.page-row {
	display: flex;
	gap: .6rem;
	align-items: center;
	justify-content: center;
}
.page-swatch {
	width: 5rem;
	height: 1.5rem;
	border: 1px solid var(--p-content-border-color);
}
.mock-kicker {
	font-family: var(--m-heading);
	font-size: calc(0.75 * var(--m-unit));
	font-weight: bold;
	letter-spacing: calc(0.1125 * var(--m-unit));
	text-transform: uppercase;
	padding-bottom: calc(0.15 * var(--m-unit));
	border-bottom: calc(0.09 * var(--m-unit)) solid currentColor;
}
.mock-light .mock-kicker { color: var(--m-text-secondary-1); }
.mock-title {
	font-family: var(--m-heading);
	font-size: calc(1.6 * var(--m-unit));
	font-weight: bold;
	line-height: 1.1;
}
.mock-light .mock-title { color: var(--m-text-primary); }
.mock-dark .mock-title { color: var(--m-text-primary-light); }
.mock-split {
	display: flex;
	gap: var(--m-unit);
	align-items: center;
	justify-content: space-between;
}
.mock-now {
	display: flex;
	gap: calc(0.6 * var(--m-unit));
	align-items: center;
}
.mock-sun {
	width: calc(2.2 * var(--m-unit));
	height: calc(2.2 * var(--m-unit));
	border-radius: 50%;
	background: var(--m-bg-secondary-2-accent);
}
.mock-temp {
	font-family: var(--m-heading);
	font-size: calc(1.8 * var(--m-unit));
	font-weight: bold;
	line-height: 1;
	color: var(--m-text-primary);
}
.mock-small {
	font-size: calc(0.8 * var(--m-unit));
}
.mock-month {
	display: grid;
	grid-template-columns: repeat(7, calc(1.05 * var(--m-unit)));
	gap: calc(0.105 * var(--m-unit));
	font-size: calc(0.7 * var(--m-unit));
	text-align: center;
}
.mock-month .today {
	background: var(--m-bg-primary-accent);
	color: var(--m-text-primary-light);
	border-radius: calc(0.14 * var(--m-unit));
}
.mock-events {
	display: flex;
	flex-direction: column;
	gap: calc(0.2 * var(--m-unit));
	font-size: calc(0.8 * var(--m-unit));
}
.mock-event {
	padding: calc(0.12 * var(--m-unit)) calc(0.4 * var(--m-unit));
	border-left: calc(0.24 * var(--m-unit)) solid;
}
.mock-event-1 { background: var(--m-bg-secondary-1); border-color: var(--m-bg-secondary-1-accent); color: var(--m-text-secondary-1); }
.mock-event-2 { background: var(--m-bg-secondary-2); border-color: var(--m-bg-secondary-2-accent); color: var(--m-text-secondary-2); }
.mock-bar {
	margin-top: auto;
	height: calc(1.2 * var(--m-unit));
	background: linear-gradient(to right, var(--m-bg-secondary-1-accent) 60%, var(--m-bg-secondary-2-dark) 60%);
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
.type-sample {
	margin: .5rem auto;
	max-width: 36rem;
	padding: .75rem 1rem;
	border: 1px solid var(--p-content-border-color);
	border-radius: 4px;
}
.type-heading {
	font-size: 1.6rem;
	font-weight: bold;
}
.type-overlay {
	margin-top: .5rem;
	font-size: 1.3rem;
	font-weight: bold;
}
</style>