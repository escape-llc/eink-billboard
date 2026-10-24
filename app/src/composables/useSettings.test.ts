import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick } from "vue"
import { ApiError } from "../components/ApiClient"
import { api } from "../api/client"
import { hasSettings, usedBy, useSettings, useThemePreview } from "./useSettings"

// the Settings page's data without the page: the API is a stand-in, and what the page would show as a toast is collected
vi.mock("../api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
const mocked = api as unknown as Record<"get" | "post" | "put" | "patch" | "delete", ReturnType<typeof vi.fn>>

const FIELDS = { schema: { properties: [{ name: "key", type: "string" }] }, default: { key: "factory" } }
const COMIC = { id: "comic", name: "Comic", features: ["layer-foreground"], settings: FIELDS }
const WEATHER_PAGE = { id: "weather", name: "Weather", features: ["layer-background"], requires: ["data-weather"] }
const MAP = { id: "thunderforest-map", name: "Map", features: ["layer-foreground"], uses: ["thunderforest-api"] }
const OWM = { id: "openweathermap-api", name: "OpenWeatherMap", features: ["api", "data-weather"], settings: FIELDS }
const TF = { id: "thunderforest-api", name: "Thunderforest", features: ["api"] }
const SOURCES = [COMIC, WEATHER_PAGE, MAP, OWM, TF]
const SLIDES = { id: "slide-show", name: "Slide Show", settings: { schema: { properties: [] } } }

/** Every route the page asks; `refuse` names the routes that fail (a 404 or another error). */
function serve(refuse: Record<string, Error> = {}) {
	mocked.get.mockImplementation(async (path: string, options?: { path?: Record<string, string> }) => {
		const name = options?.path?.name ?? options?.path?.datasource_id ?? options?.path?.plugin_id
		const key = name ? `${path}:${name}` : path
		if(refuse[key]) throw refuse[key]
		if(path === "/api/plugins/list") return [SLIDES]
		if(path === "/api/datasources/list") return SOURCES
		if(path === "/api/displays/list") return [{ id: "mock", name: "Mock" }]
		if(path === "/api/schemas/{name}") return { schema: { properties: [] }, default: { from: `${name} schema` } }
		if(path === "/api/settings/{name}") return { _id: name, _rev: "r1" }
		if(path === "/api/datasources/{datasource_id}/settings") return { _id: name, key: "stored" }
		throw new Error(`no route ${key}`)
	})
}
async function started(refuse: Record<string, Error> = {}) {
	serve(refuse)
	const notices: string[] = []
	const st = useSettings(detail => notices.push(detail))
	await st.start()
	return { st, notices }
}
const settled = async () => { await nextTick(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }

beforeEach(() => { for(const fn of Object.values(mocked)) fn.mockReset() })

describe("loading", () => {
	it("loads what is installed, then every device document", async () => {
		const { st, notices } = await started()
		expect(st.plugins.value.map(p => p.id)).toEqual(["slide-show"])
		expect(st.displays.value.map(d => d.id)).toEqual(["mock"])
		expect(st.settingsSystem.value).toEqual({ _id: "system", _rev: "r1" })
		expect(st.settingsTheme.value?._id).toBe("theme")
		expect(st.settingsPrompts.value?._id).toBe("master-prompts")
		expect(st.settingsDisplay.value?._id).toBe("display")
		expect(st.settingsDevices.value?._id).toBe("devices")
		expect(st.schemaDevices.value?.default).toEqual({ from: "devices schema" })
		expect(notices).toEqual([])
	})

	it("a storage older than the devices document starts the Devices tab from the schema's default", async () => {
		const { st, notices } = await started({ "/api/settings/{name}:devices": new ApiError(404, "Not found") })
		expect(st.settingsDevices.value).toEqual({ from: "devices schema" })
		expect(notices).toEqual([])
	})

	it("each part that fails says so, and the others still load", async () => {
		const { st, notices } = await started({ "/api/displays/list": new Error("down"), "/api/settings/{name}:theme": new Error("gone") })
		expect(notices).toEqual(["Failed to load displays list: down", "Failed to load: gone"])
		expect(st.settingsTheme.value).toBeUndefined()
		expect(st.settingsSystem.value?._id).toBe("system")
	})
})

describe("the item tabs", () => {
	it("the Data Sources tab lists what draws; the Providers tab what supplies, and who relies on each", async () => {
		const { st } = await started()
		expect(st.pageSources.value.map(d => d.id)).toEqual(["comic", "weather", "thunderforest-map"])
		expect(st.providerSources.value.map(d => d.id)).toEqual(["openweathermap-api", "thunderforest-api"])
		expect(st.usedBy(OWM)).toEqual(["weather"])
		expect(st.usedBy(TF)).toEqual(["thunderforest-map"])
	})

	it("choosing an item loads its stored settings; none stored starts from its defaults", async () => {
		const { st } = await started({ "/api/datasources/{datasource_id}/settings:openweathermap-api": new ApiError(404, "Not found") })
		st.datasource.selected.value = COMIC
		await settled()
		expect(st.datasource.schema.value).toEqual(COMIC.settings)
		expect(st.datasource.settings.value).toEqual({ _id: "comic", key: "stored" })
		st.provider.selected.value = OWM
		await settled()
		expect(st.provider.settings.value).toEqual({ key: "factory" })
	})

	it("an item with nothing to edit clears the tab", async () => {
		const { st } = await started()
		st.datasource.selected.value = COMIC
		await settled()
		st.datasource.selected.value = MAP
		await settled()
		expect([st.datasource.schema.value, st.datasource.settings.value]).toEqual([undefined, undefined])
		st.plugin.selected.value = SLIDES
		await settled()
		expect(st.plugin.schema.value).toBeUndefined()
	})

	it("an item has settings only when its block has a field", () => {
		expect([hasSettings(COMIC), hasSettings(SLIDES), hasSettings(MAP), hasSettings(undefined)]).toEqual([true, false, false, false])
		expect(usedBy(COMIC, SOURCES)).toEqual([])
	})
})

describe("the theme preview", () => {
	beforeEach(() => vi.useFakeTimers())
	afterEach(() => vi.useRealTimers())

	it("asks for the palette once the values have been still for a moment", async () => {
		mocked.post.mockResolvedValue({ roles: [{ name: "text-primary", color: "#123456" }] })
		const tp = useThemePreview()
		tp.fromStored({ theme: "triadic", hue: 200, saturation: 80, lightness: 40, background: "black" })
		tp.fromForm({ theme: "triadic", hue: 210, saturation: 80, lightness: 40, background: "black" })
		await vi.advanceTimersByTimeAsync(200)
		expect(mocked.post).toHaveBeenCalledTimes(1)
		expect(mocked.post.mock.calls[0]![2]).toEqual({ theme: "triadic", hue: 210, saturation: 80, lightness: 40, background: "black" })
		expect(tp.paletteColors.value).toEqual({ "text-primary": "#123456" })
	})

	it("the form's value that is not a number yet leaves the preview as it was; an unset background is white", () => {
		const tp = useThemePreview()
		tp.fromStored({ hue: 30, fontBody: "Lexend", fontHeading: "Bitter", fontScale: 1.2, background: "tinted" })
		expect([tp.hue.value, tp.fontBody.value, tp.fontHeading.value, tp.fontScale.value, tp.background.value]).toEqual([30, "Lexend", "Bitter", 1.2, "tinted"])
		tp.fromForm({ hue: null, fontHeading: null })
		expect([tp.hue.value, tp.fontHeading.value, tp.background.value]).toEqual([30, null, "white"])
	})

	it("a palette the server cannot compute keeps what the swatches showed", async () => {
		const tp = useThemePreview()
		tp.paletteColors.value = { "text-primary": "#000000" }
		mocked.post.mockRejectedValue(new Error("down"))
		tp.refreshPalette()
		await vi.advanceTimersByTimeAsync(200)
		expect(tp.paletteColors.value).toEqual({ "text-primary": "#000000" })
	})
})
