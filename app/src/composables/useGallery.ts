/**
 * The Gallery page's data (#517): the pictures the Gallery keeps (#238), read once through the cache (`/api/datasource/gallery/items`), and the
 * calls that change them: pin, remove, add a picture from this computer, and keep one the panel showed. The Gallery tells every change as telemetry
 * that names its routes (`changed`), so the cache asks again whoever made it (a producer, another tab); a change made here marks it stale at once.
 * What goes wrong is told through `notify` (the page shows it as a toast), so this runs and is tested without a component.
 */
import { computed, ref } from "vue"
import { useQuery, useQueryCache } from "@pinia/colada"
import { api, apiUrl } from "../api/client"
import type { components } from "../api/schema"
import { changedHere, keyOf } from "../api/resources"
import { apiUpload } from "../components/ApiClient"
import type { TelemetryEvent } from "../components/TelemetryLink"
import { shownTitle } from "./useRecentlyShown"

export type GalleryItem = components["schemas"]["Item"]
type KeepAnswer = components["schemas"]["KeepAnswer"]
export type Notify = (severity: "success" | "info" | "error", detail: string) => void

/** Every Gallery route: what a change here makes stale. */
export const GALLERY = "/api/datasource/gallery"
const ITEMS = "/api/datasource/gallery/items"
/** The pictures a person may add (what the device reads: the push API's kinds, found by their content on the server). */
export const ACCEPT = "image/png,image/jpeg,image/webp,image/gif"

/** A picture's address: a thumbnail (320 pixels on its long side) or the whole picture as kept. The answer never changes under its id. */
export function galleryImageUrl(id: string, size: "thumb" | "full" = "thumb"): string {
	return apiUrl("/api/datasource/gallery/items/{item_id}/image", { path: { item_id: id }, query: { size } })
}

/** Where a picture came from, in words. */
export function originOf(item: GalleryItem): string {
	if (item.origin === "upload") return "Added by hand"
	if (item.origin === "display") return "Saved from the panel"
	return item.origin ? `Drawn by ${item.origin}` : ""
}

/** The calls that change the Gallery (a component's setup): each is told when it fails, and the list is asked for again whatever came of it. */
function useChanges(notify: Notify) {
	const cache = useQueryCache()
	const busy = ref(false)
	async function change<T>(call: () => Promise<T>, fallback: string): Promise<T | undefined> {
		busy.value = true
		try {
			return await call()
		}
		catch (ex: any) {
			notify("error", ex?.message || fallback)
			return undefined
		}
		finally {
			busy.value = false
			void changedHere(cache, GALLERY)
		}
	}
	function told(answer: KeepAnswer | undefined): boolean {
		if (!answer) return false
		notify(answer.kept ? "success" : "info", answer.kept ? "The picture was added to the Gallery." : "That picture is in the Gallery already.")
		return answer.kept
	}
	/** Keep a picture the panel showed, as it was shown, under its title. */
	async function saveShown(e: TelemetryEvent): Promise<boolean> {
		const digest = String(e.values?.digest ?? "")
		const title = shownTitle(e).slice(0, 200)
		return told(await change(() => api.post("/api/datasource/gallery/items/from-display", {}, { digest, title }), "The picture could not be saved."))
	}
	return { busy, change, told, saveShown }
}

/** "Save to Gallery" alone (the System page): keep a picture the panel showed, without reading the Gallery. */
export function useSaveShown(notify: Notify) {
	const { busy, saveShown } = useChanges(notify)
	return { busy, saveShown }
}

export function useGallery(notify: Notify) {
	const list = useQuery({ key: keyOf(ITEMS), query: () => api.get(ITEMS) })
	const pinnedOnly = ref(false)
	const { busy, change, told, saveShown } = useChanges(notify)

	const items = computed<GalleryItem[]>(() => list.data.value?.items ?? [])
	const shown = computed(() => pinnedOnly.value ? items.value.filter(i => i.pinned) : items.value)
	const totals = computed(() => list.data.value ? { count: list.data.value.count, bytes: list.data.value.bytes, maxPictures: list.data.value.maxPictures, maxBytes: list.data.value.maxBytes } : null)
	const loading = computed(() => list.status.value === "pending")
	const failed = computed(() => list.status.value === "error")

	const pin =(item: GalleryItem, pinned: boolean) =>
		change(() => api.put("/api/datasource/gallery/items/{item_id}/pin", { path: { item_id: item.id } }, { pinned }), "The picture could not be pinned.")
	const remove = (item: GalleryItem) =>
		change(() => api.delete("/api/datasource/gallery/items/{item_id}", { path: { item_id: item.id } }), "The picture could not be removed.")
	/** Add a picture from this computer, under its file name (without the extension). */
	async function upload(file: File): Promise<boolean> {
		const title = file.name.replace(/\.[^.]+$/, "").slice(0, 200)
		return told(await change(() => apiUpload<KeepAnswer>(apiUrl(ITEMS, { query: { title } }), file), `"${file.name}" could not be added.`))
	}

	return { list, items, shown, totals, loading, failed, pinnedOnly, busy, pin, remove, upload, saveShown }
}
