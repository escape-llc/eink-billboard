/**
 * The playlist page's data (#510 A6): the stored playlists, the one being edited (a working copy saved whole), the track in the editor,
 * and every call that loads or saves them. The page keeps its template, its dialogs and the form; what goes wrong is told through `notify`
 * (the page shows it as a toast), so this runs and is tested without a component.
 *
 * The working copy's cycle is the editor machine's (#550, `useEditor`): unsaved is the tracks compared with what was loaded or last saved, so a
 * track moved and moved back, or added and removed, is no change; a stale save is a conflict whose Overwrite saves over the server's revision.
 */
import { computed, reactive, ref, watch } from "vue"
import { ApiError } from "../components/ApiClient"
import { api } from "../api/client"
import type { PlaylistItem, PlaylistSchedule, PluginDef } from "../components/ScheduleDefs"
import type { Descriptor } from "../components/FormDefs"
import { describeTrack, type Describable } from "../components/Describe"
import { useEditor } from "./useEditor"

export type Notify = (severity: "success" | "error", detail: string) => void
/** What a rename or a new playlist came to: done, refused because the playlist changed (a conflict is shown), or failed (`notify` said why). */
export type NameOutcome = "done" | "conflict" | "failed"
/** A problem the server found, by its path in the playlist (`["items", "<index>", "content", "<field>"]`). */
export type ServerError = { path?: unknown[], message?: string }

// a track that is not saved yet has an id of ours; the server gives it its own
export const NEW_PREFIX = "new-"
function uid() { return `${NEW_PREFIX}${Math.random().toString(36).slice(2, 9)}` }
// a playlist track plays on the background or foreground layer: the plugins for the timer layers (priority, overlay) are not offered.
// A stored track keeps its plugin (and shows it) even when it would not be offered now
const PLAYLIST_LAYERS = ["layer-background", "layer-foreground"]

/**
 * A 422's problems, sorted: one in a field of the selected track goes on that field (`onField`, the path the form knows), everything else is
 * listed with the track it is in.
 */
export function splitServerErrors(errors: ServerError[], tracks: PlaylistItem[], selectedIndex: number | null, fallback: string) {
	const onField: { path: unknown[], message: string }[] = []
	const listed: string[] = []
	for(const err of errors) {
		const path = err.path ?? []
		const index = path[0] === "items" ? Number(path[1]) : NaN
		const track = Number.isInteger(index) ? tracks[index] : undefined
		if(track && index === selectedIndex && path[2] === "content" && typeof path[3] === "string") {
			onField.push({ path: [path[3]], message: err.message ?? "" })
		}
		else {
			const where = track ? `Track "${track.title}": ` : ""
			listed.push(`${where}${path.slice(2).join(" / ")}${path.length > 2 ? ": " : ""}${err.message ?? fallback}`)
		}
	}
	return { onField, listed }
}

/** The stored form of a working copy: new tracks have no id yet, and nothing else of ours goes along. */
export function documentBody(name: string | undefined, tracks: PlaylistItem[], rev: string | undefined) {
	return {
		name,
		_rev: rev,
		items: tracks.map(t => {
			const { _rev, ...track } = t as PlaylistItem & { _rev?: string }
			return String(track.id).startsWith(NEW_PREFIX) ? (({ id: _id, ...rest }) => rest)(track) : track
		})
	}
}

export function usePlaylists(notify: Notify) {
	const plugins = ref<PluginDef[]>([])
	const dataSources = ref<Descriptor[]>([])
	// every stored playlist, and the one being edited: its working copy is saved whole
	const playlists = ref<{ id: string, name: string }[]>([])
	const currentId = ref<string | undefined>(undefined)
	const playlistName = ref<string>()
	const tracks = ref<PlaylistItem[]>([])
	// a rename or a delete is not the working copy's save: refused because the playlist changed, it says so, and Reload is the way on
	const refused = ref<string | null>(null)
	const busy = ref(false)
	const conflictMessage = ref("")
	// what a save came back with: the stored playlist, with the ids the server gave the new tracks
	let savedDoc: PlaylistSchedule | undefined = undefined
	// what was loaded or last saved, so the changes can be dropped without asking the server again
	let storedDoc: PlaylistSchedule | undefined = undefined
	const editor = useEditor<ReturnType<typeof documentBody>>({
		save: async (body, rev) => {
			const rx = await api.put("/api/schedule/playlist/{doc_id}", { path: { doc_id: currentId.value! } }, { ...body, _rev: rev })
			savedDoc = rx.schedule
			return rx.rev
		},
	})
	const docRev = editor.rev
	const dirty = editor.hasUnsaved
	const saving = computed(() => busy.value || editor.isBusy.value)
	const conflict = computed<{ message: string, rev: string | undefined } | null>(() =>
		editor.inConflict.value ? { message: conflictMessage.value, rev: editor.theirs.value } : refused.value !== null ? { message: refused.value, rev: undefined } : null)
	// the working copy is the editor's values: every change to the tracks is compared with what was loaded
	const report = () => editor.values(tracks.value, true)
	watch(tracks, report, { deep: true, flush: "sync" })
	const serverProblems = ref<string[]>([])
	const selectedIndex = ref<number | null>(null)
	// a track being added: edited like the others, but not in the playlist (nor an unsaved change) until it is applied; cancel drops it
	const draft = ref<PlaylistItem | null>(null)
	// the page shows a loading bar until the plugins, the data sources and the playlists are here (a failure of any is a notice, never an empty page)
	const loading = ref(true)
	// the editor's copy of the track: the track changes only when it is applied
	const editModel = reactive<Record<string, any>>({})

	const selectedTrack = computed(() => draft.value ?? (selectedIndex.value !== null ? tracks.value[selectedIndex.value] : null))
	const selectedPlugin = computed(() => plugins.value.find(p => p.id === editModel.plugin_name) || null)
	const playlistPlugins = computed(() => plugins.value.filter(p => (p.features ?? []).some(f => PLAYLIST_LAYERS.includes(f))))
	const pluginOptions = computed(() => plugins.value.filter(p => playlistPlugins.value.includes(p) || p.id === editModel.plugin_name).map(p => ({ id: p.id, name: p.name })))

	/** The line under a track's title: what the track plays ("Comic XKCD"), not only which plugin does it. */
	function describeOf(t: PlaylistItem): string {
		const plugin = plugins.value.find(x => x.id === t.plugin_name)
		return describeTrack(plugin, t.content ?? {}, dataSources.value as Describable[]) || "Unknown Plugin"
	}
	function resetMessages() {
		refused.value = null
		serverProblems.value = []
	}

	// --- the track in the editor
	/** Put a track into the editor (a copy). */
	function load(trk: PlaylistItem) {
		editModel.id = trk.id
		editModel.plugin_name = trk.plugin_name
		editModel.type = trk.type
		editModel.title = trk.title
		editModel.content = JSON.parse(JSON.stringify(trk.content || {}))
	}
	function clearEditor() {
		editModel.id = undefined
		editModel.plugin_name = undefined
		editModel.title = undefined
		editModel.content = {}
	}
	function selectTrack(idx: number) {
		// choosing another track leaves a draft that was not applied: it is dropped, as cancel would
		draft.value = null
		selectedIndex.value = idx
		const trk = tracks.value[idx]
		if(trk) load(trk)
	}
	function cancelEdit() {
		if(draft.value) {
			// cancel on a new track: it was never added, so nothing is left behind
			draft.value = null
			selectedIndex.value = null
			clearEditor()
		}
		else if(selectedIndex.value !== null) selectTrack(selectedIndex.value)
		else clearEditor()
	}
	/** Apply: the form's fields are the track's content; the title and the plugin are the editor's. A draft becomes a track only now. */
	function applyEdit(content: Record<string, unknown>) {
		const edited = { title: editModel.title, plugin_name: editModel.plugin_name, type: "PlaylistSchedule" as const, content: structuredClone(content) }
		if(draft.value) {
			tracks.value.push({ ...draft.value, ...edited })
			draft.value = null
			selectedIndex.value = tracks.value.length - 1
		}
		else {
			if(selectedIndex.value === null) return
			const old = tracks.value[selectedIndex.value]
			if(!old) return
			tracks.value[selectedIndex.value] = { ...old, ...edited }
		}
		serverProblems.value = []
	}

	// --- track operations: they change the working copy; a save sends the playlist
	function addTrack() {
		const first = playlistPlugins.value[0]
		if(!first) return
		// a draft, not a track yet: nothing changes in the playlist until it is applied
		const track: PlaylistItem = { id: uid(), plugin_name: first.id, type: "PlaylistSchedule", title: "Untitled", content: {} }
		draft.value = track
		selectedIndex.value = null
		load(track)
	}
	function removeTrack(idx: number) {
		if(idx < 0 || idx >= tracks.value.length) return
		tracks.value.splice(idx, 1)
		if(selectedIndex.value === idx) selectedIndex.value = null
		else if(selectedIndex.value !== null && selectedIndex.value > idx) selectedIndex.value--
	}
	function moveTrack(idx: number, by: number) {
		const to = idx + by
		if(to < 0 || to >= tracks.value.length) return
		const moved = tracks.value.splice(idx, 1)
		tracks.value.splice(to, 0, ...moved)
		if(selectedIndex.value === idx) selectedIndex.value = to
		else if(selectedIndex.value === to) selectedIndex.value = idx
	}

	// --- loading
	function loadProviders() {
		// a descriptor's keys are its own (open in the API): the web app reads them as PluginDef and Descriptor, which DescriptorSchema.test holds to every descriptor
		const px = api.get("/api/plugins/list").then(json => { plugins.value = structuredClone(json) as PluginDef[] })
			.catch(ex => {
				console.error("fetch.pl.unhandled", ex)
				notify("error", `Failed to load the plugins: ${ex.message || "Unknown error"}`)
				plugins.value = []
			})
		const dx = api.get("/api/datasources/list").then(json => { dataSources.value = json as Descriptor[] })
			.catch(ex => {
				console.error("fetch.ds.unhandled", ex)
				notify("error", `Failed to load the data sources: ${ex.message || "Unknown error"}`)
				dataSources.value = []
			})
		return Promise.all([px, dx])
	}
	/** Put a stored playlist into the working copy. */
	function adopt(doc: PlaylistSchedule, keepSelection = false) {
		storedDoc = structuredClone(doc)
		currentId.value = doc.id
		playlistName.value = doc.name
		// the machine hears of the document first: the tracks it then reports are its baseline
		editor.loaded(doc._rev)
		tracks.value = structuredClone(doc.items)
		report()
		draft.value = null
		resetMessages()
		const keep = keepSelection ? selectedIndex.value : null
		selectedIndex.value = null
		if(keep !== null && keep < tracks.value.length) selectTrack(keep)
	}
	/** Load the playlists and edit `selectId` (else the first; none is an empty page). */
	async function loadPlaylists(selectId?: string) {
		try {
			const all = (await api.get("/api/schedule/playlist/list")).playlists
			playlists.value = all.map(p => ({ id: p.id, name: p.name }))
			const target = all.find(p => p.id === selectId) ?? all[0]
			if(target) adopt(target)
			else {
				currentId.value = undefined
				playlistName.value = undefined
				editor.unload()
				storedDoc = undefined
				tracks.value = []
				draft.value = null
				selectedIndex.value = null
			}
		}
		catch(err: any) {
			console.error("Error fetching playlists:", err)
			notify("error", `Failed to load the playlists: ${err.message || "Unknown error"}`)
		}
	}
	/** The page's first load: the plugins and data sources, then the playlists. */
	async function start() {
		try {
			await loadProviders()
			await loadPlaylists()
		}
		catch(ex: any) {
			console.error("initProviders.unhandled", ex)
			notify("error", `Failed to load the page: ${ex.message || "Unknown error"}`)
		}
		finally {
			loading.value = false
		}
	}

	// --- the playlists
	async function createPlaylist(name: string): Promise<NameOutcome> {
		return named(async () => {
			const rx = await api.post("/api/schedule/playlist", {}, { name, items: [] })
			await loadPlaylists(rx.id)
		})
	}
	/** Only the name changes in the store: the unsaved edits stay, on top of the new revision. */
	async function renamePlaylist(name: string): Promise<NameOutcome> {
		const id = currentId.value
		if(!id) return "failed"
		return named(async () => {
			const rx = await api.patch("/api/schedule/playlist/{doc_id}", { path: { doc_id: id } }, { name, _rev: docRev.value })
			playlistName.value = rx.schedule.name
			editor.revised(rx.rev)
			if(storedDoc) storedDoc = { ...storedDoc, name: rx.schedule.name, _rev: rx.rev }
			playlists.value = playlists.value.map(p => p.id === id ? { id: p.id, name: rx.schedule.name } : p)
		})
	}
	async function named(call: () => Promise<void>): Promise<NameOutcome> {
		busy.value = true
		try {
			await call()
			return "done"
		}
		catch(ex: any) {
			if(ex instanceof ApiError && ex.status === 409) {
				refused.value = "The playlist changed since it was loaded."
				return "conflict"
			}
			notify("error", `Failed: ${ex.message || "Unknown error"}`)
			return "failed"
		}
		finally {
			busy.value = false
		}
	}
	async function deletePlaylist() {
		if(!currentId.value || !docRev.value) return
		busy.value = true
		try {
			await api.delete("/api/schedule/playlist/{doc_id}", { path: { doc_id: currentId.value }, query: { rev: docRev.value } })
			notify("success", "Playlist deleted")
			await loadPlaylists()
		}
		catch(ex: any) {
			if(ex instanceof ApiError && ex.status === 409) {
				refused.value = "The playlist changed since it was loaded; reload it before deleting."
			}
			else notify("error", `Failed to delete the playlist: ${ex.message || "Unknown error"}`)
		}
		finally {
			busy.value = false
		}
	}
	/**
	 * Save the whole playlist over the revision the editor holds (a stale one is a conflict the person can resolve). A problem in a field
	 * of the selected track is handed to `showOnField`, which answers how many it could show; the rest is listed in `serverProblems`.
	 */
	async function savePlaylist(showOnField: (errors: { path: unknown[], message: string }[]) => number) {
		if(!currentId.value) return
		resetMessages()
		const { outcome, error } = await editor.save(documentBody(playlistName.value, tracks.value, undefined))
		const ex = error as any
		if(outcome === "saved" && savedDoc) {
			notify("success", "Playlist saved")
			adopt(savedDoc, true)
		}
		else if(outcome === "conflict") conflictMessage.value = ex.message
		else if(outcome === "failed" && ex instanceof ApiError && ex.status === 422 && Array.isArray(ex.body?.errors)) {
			const { onField, listed } = splitServerErrors(ex.body.errors, tracks.value, selectedIndex.value, ex.message)
			const shown = onField.length > 0 ? showOnField(onField) : 0
			if(shown < onField.length) listed.push(ex.message)
			serverProblems.value = listed
		}
		else if(outcome === "failed") notify("error", `Failed to save the playlist: ${ex?.message || "Unknown error"}`)
		savedDoc = undefined
	}
	/** In a conflict: save my working copy over the server's revision. */
	async function overwritePlaylist(showOnField: (errors: { path: unknown[], message: string }[]) => number) {
		if(editor.keep()) await savePlaylist(showOnField)
	}
	/** Drop the unsaved changes: the working copy is the playlist as it was loaded or last saved. */
	function discardChanges() {
		if(storedDoc) adopt(storedDoc)
	}
	/** Someone else changed the playlist: take their version (the unsaved edits are dropped). */
	async function reloadPlaylist() {
		await loadPlaylists(currentId.value)
	}

	return {
		plugins, dataSources, playlists, currentId, playlistName, docRev, tracks, dirty, saving, conflict, serverProblems, selectedIndex, draft, loading, editModel,
		selectedTrack, selectedPlugin, playlistPlugins, pluginOptions,
		describeOf, selectTrack, cancelEdit, applyEdit, addTrack, removeTrack, moveTrack,
		start, loadPlaylists, createPlaylist, renamePlaylist, deletePlaylist, savePlaylist, overwritePlaylist, reloadPlaylist, discardChanges, stop: editor.stop,
	}
}
