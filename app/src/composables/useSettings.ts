/**
 * The Settings page's data (#510 A6): the installed plugins, data sources and displays, each device document's schema and settings, and the
 * settings of the plugin, data source or provider chosen on its tab. Saving is SettingsForm's own; the page keeps its template and the theme's
 * look. What goes wrong is told through `notify` (the page shows it as a toast), so this runs and is tested without a component.
 * `useThemePreview` is the Theme tab's preview: the values it shows and the palette the server computes for them.
 */
import { computed, ref, toRaw, watch, type Ref } from "vue"
import { ApiError } from "../components/ApiClient"
import { api } from "../api/client"
import { settled, useCatalog } from "../api/resources"
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
	// what is installed, from the cache every view shares; the display devices are what the Display tab's display type (a `schema` field) chooses among
	const catalog = useCatalog()
	const plugins = computed<Descriptor[]>(() => catalog.plugins.data.value ?? [])
	const dataSources = computed<Descriptor[]>(() => catalog.dataSources.data.value ?? [])
	const displays = computed<Descriptor[]>(() => catalog.displays.data.value ?? [])
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
		const list = (query: Parameters<typeof settled>[0], what: string, tag: string) => settled(query, ex => {
			console.error(tag, ex)
			notify(`Failed to load ${what} list: ${ex.message || "Unknown error"}`)
		})
		await Promise.all([
			list(catalog.plugins, "plugins", "fetch.pl.unhandled"),
			list(catalog.dataSources, "data sources", "fetch.ds.unhandled"),
			list(catalog.displays, "displays", "fetch.dp.unhandled"),
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

/** What a role of the theme resolved to for the panel that is attached (`POST /api/theme/palette`). */
export type PaletteRole = { name: string, ink: string, drive: string, appearance: string }

/** The ink sets, as a person names them. */
export const INK_SET_NAMES: Record<string, string> = {
	bw: "Black and white", bwr: "Black, white and red", bwy: "Black, white and yellow", bwry: "Black, white, red and yellow",
	spectra6: "Six colors (Spectra 6)", acep7: "Seven colors (ACeP)",
}
/** The custom inks of the theme: the setting, the role it becomes, and its title. */
export const CUSTOM_INKS = [
	{ key: "textPrimary", role: "text-primary", title: "Main Text Ink" },
	{ key: "textSecondary1", role: "text-secondary-1", title: "First Accent Ink" },
	{ key: "textSecondary2", role: "text-secondary-2", title: "Second Accent Ink" },
	{ key: "fill", role: "bg-fill", title: "Highlight Ink" },
	{ key: "textOnFill", role: "text-on-fill", title: "Highlight Text Ink" },
] as const
const capital = (ink: string) => ink.charAt(0).toUpperCase() + ink.slice(1)

/** The Theme tab's preview: the values shown (the stored theme, then the form's as they change) and the inks the server resolves them to for the attached panel. */
export function useThemePreview(delay = 120) {
	const preset = ref("classic")
	const background = ref("white")
	// the five inks of a custom preset, by setting name
	const inks = ref<Record<string, string | null>>({})
	const fontBody = ref("Jost")
	const fontHeading = ref<string | null>(null)
	const fontOverlay = ref<string | null>(null)
	const fontScale = ref(1)
	// every role of the palette, resolved for the ink set of the attached panel (the server's answer: the browser derives nothing)
	const roles = ref<PaletteRole[]>([])
	const inkSet = ref<string | null>(null)
	const confirmed = ref(false)
	// what the panel shows, by role, for the swatches and the mock-up
	const paletteColors = computed<Record<string, string>>(() => Object.fromEntries(roles.value.map(r => [r.name, r.appearance])))
	/** "Shown for: Spectra 6", or that it is a guess while the display has not started. */
	const shownFor = computed(() => {
		if(!inkSet.value) return ""
		const name = INK_SET_NAMES[inkSet.value] ?? inkSet.value
		return confirmed.value ? `Shown for: ${name}` : `Shown for: ${name} (a guess: the display has not started)`
	})
	/** For a custom preset, each ink the panel does not have and the one used in its place. */
	const fallbackNotes = computed(() => {
		if(preset.value !== "custom") return []
		return CUSTOM_INKS.flatMap(c => {
			const chosen = inks.value[c.key]
			const used = roles.value.find(r => r.name === c.role)?.ink
			return chosen && used && chosen !== used ? [`${c.title}: ${capital(chosen)} is not used here; ${capital(used)} is.`] : []
		})
	})

	let paletteTimer: ReturnType<typeof setTimeout> | undefined
	/** Ask the server for the roles of the values shown, once they have been still for a moment. */
	function refreshPalette() {
		if(paletteTimer) clearTimeout(paletteTimer)
		paletteTimer = setTimeout(() => {
			api.post("/api/theme/palette", {}, { preset: preset.value, background: background.value, ...inks.value })
				.then(answer => { roles.value = answer.roles; inkSet.value = answer.inkSet; confirmed.value = answer.confirmed })
				.catch(() => { /* the swatches keep what they showed */ })
		}, delay)
	}
	function values(data: any) {
		if(typeof data.preset === "string") preset.value = data.preset
		for(const c of CUSTOM_INKS) if(c.key in data) inks.value = { ...inks.value, [c.key]: typeof data[c.key] === "string" ? data[c.key] : null }
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
		values(data)
	}
	/** The form's values, once they pass its rules. */
	function fromForm(data: any) {
		values(data)
	}

	return { preset, background, inks, fontBody, fontHeading, fontOverlay, fontScale, roles, inkSet, confirmed, paletteColors, shownFor, fallbackNotes, refreshPalette, fromStored, fromForm }
}
