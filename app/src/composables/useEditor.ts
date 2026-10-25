/**
 * An editor's cycle (#550): the machine of editorMachine.ts, with the loads and saves that move it. The editor (a view, a composable, SettingsForm)
 * keeps its document and its form; it tells this what happened (`values`, `edit`, a document it was handed: `loaded`) and asks it to load or save, and
 * reads the state from it: whether it can save, whether it is busy, whether leaving would lose work (`hasUnsaved`, the `unsaved` tag).
 *
 * The form reports, the editor decides: BasicForm emits what it found (`validate`, `submit`); what follows (saving, a conflict, leaving) is decided here.
 *
 * An editor that says where its document is (`follow`) hears when someone else saves it: an event of the telemetry link whose `changed` paths cover
 * the document's address (#549), or a link that missed events. The watcher reports every save, this editor's own too, so the stored revision is asked
 * for and only one that is not the editor's is a change: the document is loaded again, or, with edits, it is stale.
 */
import { computed, shallowRef } from "vue"
import { createActor, type SnapshotFrom } from "xstate"
import { ApiError } from "../components/ApiClient"
import { useTelemetry, type TelemetryLink } from "../components/TelemetryLink"
import { changedPaths, covers, keyOf } from "../api/resources"
import { BUSY, UNSAVED, editorMachine, valuesKey } from "./editorMachine"

export interface EditorOperations<TPayload> {
	/**
	 * load the document: answers its revision and how to show it. The editor is told it is loaded before it is shown, so the first values the form
	 * reports about it are its baseline
	 */
	load?: () => Promise<{ rev: string | undefined, show?: () => void }>
	/** save what the editor holds over revision `rev`; answers the new revision. A 409 is a conflict; any other failure keeps the edits */
	save: (payload: TPayload, rev: string | undefined) => Promise<string | undefined>
	/** follow the stored document: changes made elsewhere load it again, or make the edits stale */
	follow?: EditorFollow
}
export interface EditorFollow {
	/** the document's address (`/api/settings/theme`); undefined while there is none */
	address: () => string | undefined
	/** the stored document's revision now (it rejects when it cannot be had: nothing is decided then) */
	revision: () => Promise<string | undefined>
	/** the telemetry link (a fake in a test); the page's own by default */
	link?: TelemetryLink
}

/** What a save came to: done, refused because someone saved first (a conflict to resolve), failed otherwise, or not allowed now; with the error, if any. */
export type SaveOutcome = { outcome: "saved" | "conflict" | "failed" | "refused", error?: unknown }

export function useEditor<TPayload = unknown>(ops: EditorOperations<TPayload>) {
	const actor = createActor(editorMachine).start()
	const state = shallowRef<SnapshotFrom<typeof editorMachine>>(actor.getSnapshot())
	actor.subscribe(snapshot => { state.value = snapshot })

	const hasUnsaved = computed(() => state.value.hasTag(UNSAVED))
	const isBusy = computed(() => state.value.hasTag(BUSY))
	const canSave = computed(() => state.value.can({ type: "SAVE" }))
	const inConflict = computed(() => state.value.matches("conflict"))
	/** in a conflict: whether my edits can be kept (the server said its revision) */
	const canKeep = computed(() => state.value.can({ type: "KEEP" }))
	const rev = computed(() => state.value.context.rev)
	/** in a conflict: the server's revision, when it said */
	const theirs = computed(() => state.value.context.theirs)
	/** someone else saved the document while it has edits */
	const isStale = computed(() => state.value.matches("stale"))

	/** The form re-checked its values: compared with the baseline (several reports of the same values change nothing). */
	function values(held: unknown, valid: boolean) {
		actor.send({ type: "VALUES", key: valuesKey(held), valid })
	}
	/** A change that cannot be compared: unsaved until saved or discarded. */
	function edit() {
		actor.send({ type: "EDIT" })
	}
	/** The editor was handed a document at revision `rev` (by its page); its first values become the baseline. */
	function loaded(revision: string | undefined) {
		actor.send({ type: "LOADED", rev: revision })
	}
	/** The stored document has a new revision and the editor's edits stay on top of it (a rename saved on its own). */
	function revised(revision: string) {
		actor.send({ type: "REVISED", rev: revision })
	}
	/** Nothing is loaded (none chosen). */
	function unload() {
		actor.send({ type: "UNLOAD" })
	}
	async function load(event: "LOAD" | "DISCARD" | "TAKE_THEIRS" | "REMOTE_CHANGED" = "LOAD"): Promise<boolean> {
		if(!ops.load || !state.value.can({ type: event })) return false
		actor.send({ type: event })
		return state.value.matches("loading") ? reload() : true
	}
	/** Run the load the machine is waiting for. */
	async function reload(): Promise<boolean> {
		if(!ops.load) return false
		try {
			const { rev: revision, show } = await ops.load()
			loaded(revision)
			show?.()
			return true
		}
		catch {
			actor.send({ type: "LOAD_FAILED" })
			return false
		}
	}
	/** Save `payload` over the revision the editor holds. */
	async function save(payload: TPayload): Promise<SaveOutcome> {
		if(!state.value.can({ type: "SAVE" })) return { outcome: "refused" }
		const over = state.value.context.rev
		actor.send({ type: "SAVE" })
		try {
			actor.send({ type: "SAVED", rev: await ops.save(payload, over) })
			return { outcome: "saved" }
		}
		catch(error) {
			if(error instanceof ApiError && error.status === 409) {
				actor.send({ type: "CONFLICT", rev: typeof error.body?.rev === "string" ? error.body.rev : undefined })
				return { outcome: "conflict", error }
			}
			actor.send({ type: "SAVE_FAILED" })
			return { outcome: "failed", error }
		}
	}
	/** In a conflict: keep my edits, to be saved over theirs. When stale: keep editing (with nothing of mine left to keep, theirs is loaded). */
	function keep(): boolean {
		if(!state.value.can({ type: "KEEP" })) return false
		actor.send({ type: "KEEP" })
		if(state.value.matches("loading")) void reload()
		return true
	}
	/** In a conflict: drop my edits and load theirs. */
	const takeTheirs = () => load("TAKE_THEIRS")
	/** Drop my edits and load the document again. */
	const discard = () => load("DISCARD")

	// --- changes made elsewhere
	let checking = false
	let again = false
	/** Ask for the stored revision; one that is not the editor's (and the editor still at the revision it asked about) is a change. */
	async function check(): Promise<void> {
		if(!ops.follow?.address()) return
		if(checking) { again = true; return }
		checking = true
		try {
			do {
				again = false
				if(!state.value.can({ type: "REMOTE_CHANGED" })) continue
				const asked = state.value.context.rev
				let stored: string | undefined
				try { stored = await ops.follow.revision() }
				catch { continue }
				// a load or a save while it was asked: the editor's revision is newer than this answer
				if(stored === asked || state.value.context.rev !== asked || !state.value.can({ type: "REMOTE_CHANGED" })) continue
				if(state.value.matches("dirty")) actor.send({ type: "REMOTE_CHANGED" })
				else await load("REMOTE_CHANGED")
			} while(again)
		}
		finally {
			checking = false
		}
	}
	const follow = ops.follow
	const unlisten = follow ? (follow.link ?? useTelemetry()).listen({
		// the history the link opens with is checked too: a save between the load and the link's opening is in it (the revision tells an old one)
		event: e => {
			const address = follow.address()
			if(!address) return
			if(e.kind === "gap" || changedPaths(e).some(path => covers(path, keyOf(address)))) void check()
		},
		resumed: () => { void check() },
	}) : () => {}
	const stop = () => {
		unlisten()
		actor.stop()
	}

	return { state, hasUnsaved, isBusy, canSave, inConflict, isStale, canKeep, rev, theirs, values, edit, loaded, revised, unload, load, save, keep, takeTheirs, discard, check, stop }
}
