/**
 * The Settings page's data (#510 A6): the installed plugins, data sources and displays, each device document's schema and settings, and the
 * settings of the plugin, data source or provider chosen on its tab. Saving is SettingsForm's own; the page keeps its template and the theme's
 * look. What goes wrong is told through `notify` (the page shows it as a toast), so this runs and is tested without a component.
 * `useThemePreview` is the Theme tab's preview: the values it shows and the palette the server computes for them.
 */
import { computed, ref, toRaw, watch, type Ref } from "vue"
import { ApiError } from "../components/ApiClient"
import { api } from "../api/client"
import type { Descriptor } from "../components/FormDefs"

export type Notify = (detail: string) => void

/** A plugin or data source with no settings block, or an empty one, has nothing to edit. */
export const hasSettings = (item: any): boolean => (item?.settings?.schema?.properties?.length ?? 0) > 0
/** A provider (`api`) supplies data and draws nothing: it has a tab of its own, and the Data Sources tab lists what draws. */
export const isProvider = (item: any): boolean => (item?.features ?? []).includes("api")
/** The data sources that rely on a provider: they require what it supplies, or use it by its id. */
export function usedBy(item: any, dataSources: any[]): string[] {
	const supplies = (item?.features ?? []).filter((f: string) => f.startsWith("data-"))
	return dataSources
		.filter(d => d.id !== item?.id && ((d.requires ?? []).some((c: string) => supplies.includes(c)) || (d.uses ?? []).includes(item?.id)))
		.map(d => d.id)
}

export function useSettings(notify: Notify) {
	const plugins = ref<Descriptor[]>([])
	const dataSources = ref<Descriptor[]>([])
	// the display devices that are installed: what the Display tab's display type (a `schema` field) chooses among
	const displays = ref<Descriptor[]>([])
	const schemaSystem = ref<any>(undefined)
	const settingsSystem = ref<any>(undefined)
	const schemaTheme = ref<any>(undefined)
	const settingsTheme = ref<any>(undefined)
	const schemaPrompts = ref<any>(undefined)
	const settingsPrompts = ref<any>(undefined)
	const schemaDevices = ref<any>(undefined)
	const settingsDevices = ref<any>(undefined)
	const schemaDisplay = ref<any>(undefined)
	const settingsDisplay = ref<any>(undefined)

	const pageSources = computed(() => (dataSources.value as any[]).filter(d => !isProvider(d)))
	const providerSources = computed(() => (dataSources.value as any[]).filter(isProvider))

	function downloadToRef(asked: Promise<unknown>, vref: Ref<any>) {
		return asked.then(data => { vref.value = data })
			.catch(ex => {
				console.error("downloadToRef.unhandled", ex)
				vref.value = undefined
				notify(`Failed to load: ${ex.message || "Unknown error"}`)
			})
	}
	/** A plugin's or data source's stored settings; none stored yet starts from its schema's defaults. */
	function fetchSettings(kind: "plugin" | "datasource", id: string, vref: Ref<any>, item: any) {
		const asked = kind === "plugin"
			? api.get("/api/plugins/{plugin_id}/settings", { path: { plugin_id: id } })
			: api.get("/api/datasources/{datasource_id}/settings", { path: { datasource_id: id } })
		return asked.then(data => { vref.value = data })
			.catch(ex => {
				if(ex instanceof ApiError && ex.status === 404) {
					// nothing stored yet: start from the defaults in the schema
					vref.value = structuredClone(toRaw(item.settings.default))
					return
				}
				console.error("fetchSettings.unhandled", ex)
				notify(`Failed to load settings: ${ex.message || "Unknown error"}`)
			})
	}
	/** The state of a tab that edits one item's settings at a time: the item chosen, its settings schema and document. */
	function itemSettings(kind: "plugin" | "datasource") {
		const selected = ref<any>(undefined)
		const schema = ref<any>(undefined)
		const settings = ref<any>(undefined)
		watch(selected, nv => {
			if(!nv) return
			if(hasSettings(nv)) {
				schema.value = nv.settings
				fetchSettings(kind, nv.id, settings, nv)
			}
			else {
				schema.value = undefined
				settings.value = undefined
			}
		})
		return { selected, schema, settings }
	}
	const plugin = itemSettings("plugin")
	const datasource = itemSettings("datasource")
	const provider = itemSettings("datasource")

	// the devices' settings: a storage that is older than them has none stored, which is not an error: the form starts from the schema's default (saving it creates the document)
	function loadDevices() {
		return api.get("/api/schemas/{name}", { path: { name: "devices" } }).then(schema => {
			schemaDevices.value = schema
			return api.get("/api/settings/{name}", { path: { name: "devices" } })
				.then(data => { settingsDevices.value = data })
				.catch(ex => {
					if(ex instanceof ApiError && ex.status === 404) {
						settingsDevices.value = structuredClone((schema as { default?: unknown }).default)
						return
					}
					throw ex
				})
		}).catch(ex => {
			console.error("loadDevices.unhandled", ex)
			notify(`Failed to load: ${ex.message || "Unknown error"}`)
		})
	}
	/** The page's first load: the lists of what is installed, then every device document (each on its own: one that fails leaves the others). */
	async function start() {
		// a descriptor's keys are its own (open in the API): read as FormDefs' Descriptor, which DescriptorSchema.test holds to every descriptor
		const list = (asked: Promise<unknown>, into: Ref<Descriptor[]>, what: string, tag: string) => asked
			.then(json => { into.value = json as Descriptor[] })
			.catch(ex => {
				console.error(tag, ex)
				notify(`Failed to load ${what} list: ${ex.message || "Unknown error"}`)
			})
		await Promise.all([
			list(api.get("/api/plugins/list"), plugins, "plugins", "fetch.pl.unhandled"),
			list(api.get("/api/datasources/list"), dataSources, "data sources", "fetch.ds.unhandled"),
			list(api.get("/api/displays/list"), displays, "displays", "fetch.dp.unhandled"),
		])
		const schema = (name: string) => api.get("/api/schemas/{name}", { path: { name } })
		const settings = (name: string) => api.get("/api/settings/{name}", { path: { name } })
		await Promise.all([
			downloadToRef(schema("theme"), schemaTheme),
			downloadToRef(schema("display"), schemaDisplay),
			downloadToRef(schema("system"), schemaSystem),
			downloadToRef(schema("master-prompts"), schemaPrompts),
			loadDevices(),
			downloadToRef(settings("system"), settingsSystem),
			downloadToRef(settings("display"), settingsDisplay),
			downloadToRef(settings("theme"), settingsTheme),
			downloadToRef(settings("master-prompts"), settingsPrompts),
		])
	}

	return {
		plugins, dataSources, displays,
		schemaSystem, settingsSystem, schemaTheme, settingsTheme, schemaPrompts, settingsPrompts, schemaDevices, settingsDevices, schemaDisplay, settingsDisplay,
		plugin, datasource, provider, pageSources, providerSources,
		usedBy: (item: any) => usedBy(item, dataSources.value as any[]),
		start,
	}
}

/** The Theme tab's preview: the values shown (the stored theme, then the form's as they change) and the palette the server computes for them. */
export function useThemePreview(delay = 120) {
	const scheme = ref("complementary")
	const background = ref("white")
	const hue = ref(0)
	const saturation = ref(100)
	const lightness = ref(50)
	const fontBody = ref("Jost")
	const fontHeading = ref<string | null>(null)
	const fontOverlay = ref<string | null>(null)
	const fontScale = ref(1)
	// the roles are the CSS classes of themes.css (text-primary, bg-secondary-1-accent, ...), computed by the server from the values shown
	const paletteColors = ref<Record<string, string>>({})

	let paletteTimer: ReturnType<typeof setTimeout> | undefined
	/** Ask the server for the palette of the values shown, once they have been still for a moment. */
	function refreshPalette() {
		if(paletteTimer) clearTimeout(paletteTimer)
		paletteTimer = setTimeout(() => {
			api.post("/api/theme/palette", {}, { theme: scheme.value, hue: hue.value, saturation: saturation.value, lightness: lightness.value, background: background.value })
				.then(answer => { paletteColors.value = Object.fromEntries(answer.roles.map(r => [r.name, r.color])) })
				.catch(() => { /* the swatches keep what they showed */ })
		}, delay)
	}
	function fonts(data: any) {
		if("fontBody" in data && typeof data.fontBody === "string") fontBody.value = data.fontBody
		if("fontHeading" in data) fontHeading.value = typeof data.fontHeading === "string" ? data.fontHeading : null
		if("fontOverlay" in data) fontOverlay.value = typeof data.fontOverlay === "string" ? data.fontOverlay : null
		if(typeof data.fontScale === "number") fontScale.value = data.fontScale
		background.value = typeof data.background === "string" ? data.background : "white"
		refreshPalette()
	}
	/** The stored theme, as the form loads it. */
	function fromStored(data: any) {
		if(!data) return
		if(typeof data.theme === "string") scheme.value = data.theme
		if("hue" in data) hue.value = data.hue
		if("saturation" in data) saturation.value = data.saturation
		if("lightness" in data) lightness.value = data.lightness
		fonts(data)
	}
	/** The form's values, once they pass its rules: a number that is not one yet is left as it was. */
	function fromForm(data: any) {
		if(typeof data.theme === "string") scheme.value = data.theme
		if(typeof data.hue === "number") hue.value = data.hue
		if(typeof data.saturation === "number") saturation.value = data.saturation
		if(typeof data.lightness === "number") lightness.value = data.lightness
		fonts(data)
	}

	return { scheme, background, hue, saturation, lightness, fontBody, fontHeading, fontOverlay, fontScale, paletteColors, refreshPalette, fromStored, fromForm }
}
