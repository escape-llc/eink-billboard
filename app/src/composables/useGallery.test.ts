import { beforeEach, describe, expect, it, vi } from "vitest"
import { reactive } from "vue"
import { useQueryCache } from "@pinia/colada"
import { api } from "../api/client"
import { inApp } from "../api/inApp"
import { fakeLink, settle } from "../api/fakeLink"
import { syncWithLink } from "../api/resources"
import { ApiError, apiUpload } from "../components/ApiClient"
import type { TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"
import { galleryImageUrl, hasOriginal, originOf, useGallery, useSaveShown, type GalleryItem } from "./useGallery"
import { RECENT_COUNT, useRecentlyShown } from "./useRecentlyShown"

// the Gallery page's data without the page: the API is a stand-in (the address builder is the real one), and what the page would show as a toast is collected
vi.mock("../api/client", async importOriginal => ({ ...await importOriginal<typeof import("../api/client")>(), api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
vi.mock("../components/ApiClient", async importOriginal => ({ ...await importOriginal<typeof import("../components/ApiClient")>(), apiUpload: vi.fn() }))
const mocked = api as unknown as Record<"get" | "post" | "put" | "patch" | "delete", ReturnType<typeof vi.fn>>
const upload = apiUpload as unknown as ReturnType<typeof vi.fn>

const item = (id: string, extra: Partial<GalleryItem> = {}): GalleryItem => ({ id, title: id, origin: "ai-image", added: "2026-10-28T09:00:00+00:00", size: 100, pinned: false, ...extra })
let stored: GalleryItem[] = []
function serve() {
	mocked.get.mockImplementation(async (path: string) => {
		if(path === "/api/datasource/gallery/items") return { items: stored, count: stored.length, bytes: stored.length * 100, maxPictures: 200, maxBytes: 512 * 1024 * 1024 }
		throw new Error(`no route ${path}`)
	})
}
async function started() {
	serve()
	const notices: string[] = []
	const g = inApp(() => useGallery((severity, detail) => notices.push(`${severity}: ${detail}`)))
	await g.list.refresh()
	return { g, notices }
}
const shownEvent = (seq: number, digest: string, title = digest): TelemetryEvent => ({ seq, ts: "2026-10-28T09:00:00Z", source: "display", kind: "shown", values: { digest, title } })

beforeEach(() => {
	for(const fn of Object.values(mocked)) fn.mockReset()
	upload.mockReset()
	stored = [item("b", { pinned: true }), item("a", { origin: "upload" })]
})

describe("the pictures", () => {
	it("are listed newest first with the totals, and narrowed to the pinned ones", async () => {
		const { g } = await started()
		expect(g.shown.value.map(i => i.id)).toEqual(["b", "a"])
		expect(g.totals.value).toEqual({ count: 2, bytes: 200, maxPictures: 200, maxBytes: 512 * 1024 * 1024 })
		g.pinnedOnly.value = true
		expect(g.shown.value.map(i => i.id)).toEqual(["b"])
	})
	it("each has its own address, whole or small, and a word for where it came from", () => {
		expect(galleryImageUrl("0123abcd")).toMatch(/\/api\/datasource\/gallery\/items\/0123abcd\/image\?size=thumb$/)
		expect(galleryImageUrl("0123abcd", "full")).toMatch(/size=full$/)
		expect([originOf(item("x", { origin: "upload" })), originOf(item("x", { origin: "display" })), originOf(item("x"))]).toEqual(["Added by hand", "Saved from the panel", "From ai-image"])
		// a data source by its own name, when the catalog has it
		expect(originOf(item("x", { origin: "museum-art" }), { "museum-art": "Museum Art" })).toBe("From Museum Art")
	})
	it("are asked for again when the Gallery says it changed (a producer kept one, another tab removed one)", async () => {
		serve()
		const { link, send } = fakeLink()
		const g = inApp(() => { syncWithLink(useQueryCache(), link); return useGallery(() => {}) })
		await g.list.refresh()
		stored = [item("c"), ...stored]
		send({ seq: 2, source: "data-source", kind: "gallery-kept", values: { changed: ["/api/datasource/gallery"] } })
		await vi.waitFor(() => expect(g.shown.value.map(i => i.id)).toEqual(["c", "b", "a"]))
	})
})

describe("the changes", () => {
	it("pin and remove a picture by its id, and the list is asked for again", async () => {
		const { g, notices } = await started()
		mocked.put.mockResolvedValue({ success: true })
		mocked.delete.mockResolvedValue({ success: true })
		await g.pin(g.shown.value[1], true)
		expect(mocked.put).toHaveBeenCalledWith("/api/datasource/gallery/items/{item_id}/pin", { path: { item_id: "a" } }, { pinned: true })
		stored = [stored[0]]
		await g.remove(g.shown.value[1])
		expect(mocked.delete).toHaveBeenCalledWith("/api/datasource/gallery/items/{item_id}", { path: { item_id: "a" } })
		await vi.waitFor(() => expect(g.shown.value.map(i => i.id)).toEqual(["b"]))
		expect(notices).toEqual([])
	})
	it("say in the server's words what went wrong", async () => {
		const { g, notices } = await started()
		mocked.delete.mockRejectedValue(new ApiError(404, "That picture is not in the Gallery.", "gallery"))
		await g.remove(g.shown.value[0])
		expect(notices).toEqual(["error: That picture is not in the Gallery."])
		expect(g.busy.value).toBe(false)
	})
	it("add a file under its name, and say whether it was kept or was there already", async () => {
		const { g, notices } = await started()
		upload.mockResolvedValueOnce({ success: true, kept: true, id: "c", message: "" }).mockResolvedValueOnce({ success: true, kept: false, id: "c", message: "" })
		const file = new File([new Uint8Array([1, 2, 3])], "My cat.photo.png", { type: "image/png" })
		expect(await g.upload(file)).toBe(true)
		expect(upload.mock.calls[0][0]).toMatch(/\/api\/datasource\/gallery\/items\?title=My\+cat\.photo$/)
		expect(upload.mock.calls[0][1]).toBe(file)
		expect(await g.upload(file)).toBe(false)
		expect(notices).toEqual(["success: The picture was added to the Gallery.", "info: That picture is in the Gallery already."])
	})
	it("keep a picture the panel showed by its digest, under its title, without reading the Gallery", async () => {
		const notices: string[] = []
		const s = inApp(() => useSaveShown((severity, detail) => notices.push(`${severity}: ${detail}`)))
		mocked.post.mockResolvedValue({ success: true, kept: true, id: "d", message: "" })
		expect(await s.saveShown(shownEvent(1, "f".repeat(64), "Weather"))).toBe(true)
		expect(mocked.post).toHaveBeenCalledWith("/api/datasource/gallery/items/from-display", {}, { digest: "f".repeat(64), title: "Weather", asShown: false })
		expect(mocked.get).not.toHaveBeenCalled()
		expect(notices).toEqual(["success: The picture was added to the Gallery."])
		mocked.post.mockRejectedValue(new ApiError(404, "The device no longer has that picture.", "gallery"))
		expect(await s.saveShown(shownEvent(2, "e".repeat(64)))).toBe(false)
		expect(notices[1]).toBe("error: The device no longer has that picture.")
		await settle()
	})
})

describe("the original of a page (#768)", () => {
	it("is said by the event, saved by default, and the panel's picture is saved when asked for", async () => {
		const notices: string[] = []
		const s = inApp(() => useSaveShown((severity, detail) => notices.push(`${severity}: ${detail}`)))
		const painting = { ...shownEvent(1, "a".repeat(64), "A painting"), values: { digest: "a".repeat(64), title: "A painting", original: true } }
		expect([hasOriginal(painting), hasOriginal(shownEvent(2, "b"))]).toEqual([true, false])
		mocked.post.mockResolvedValueOnce({ success: true, kept: true, id: "p", message: "", original: true }).mockResolvedValueOnce({ success: true, kept: true, id: "q", message: "", original: false })
		await s.saveShown(painting)
		await s.saveShown(painting, true)
		expect(mocked.post.mock.calls.map(c => c[2].asShown)).toEqual([false, true])
		expect(notices).toEqual(["success: The original picture was added to the Gallery.", "success: The picture was added to the Gallery."])
		await settle()
	})
})

describe("recently shown", () => {
	it("is the current picture, then the ones shown before it, each once, newest first, a few of them", () => {
		const state = reactive({ current: null as TelemetryEvent | null, events: [] as TelemetryEvent[] })
		const { current, recent } = useRecentlyShown({ state } as unknown as TelemetryLink)
		expect([current.value, recent.value]).toEqual([null, []])
		state.events = [shownEvent(3, "c"), { seq: 2, ts: "", source: "playlist_layer", kind: "track-started" }, shownEvent(2, "b"), shownEvent(1, "c")]
		state.current = shownEvent(4, "d")
		expect(recent.value.map(e => e.values?.digest)).toEqual(["d", "c", "b"])
		state.events = Array.from({ length: 12 }, (_, i) => shownEvent(20 - i, `p${i}`))
		expect(recent.value).toHaveLength(RECENT_COUNT)
	})
})
