/**
 * An editor's cycle (#550): the machine of editorMachine.ts, with the loads and saves that move it. The editor (a view, a composable, SettingsForm)
 * keeps its document and its form; it tells this what happened (`values`, `edit`, a document it was handed: `loaded`) and asks it to load or save, and
 * reads the state from it: whether it can save, whether it is busy, whether leaving would lose work (`hasUnsaved`, the `unsaved` tag).
 *
 * The form reports, the editor decides: BasicForm emits what it found (`validate`, `submit`); what follows (saving, a conflict, leaving) is decided here.
 */
import { computed, shallowRef } from "vue"
import { createActor, type SnapshotFrom } from "xstate"
import { ApiError } from "../components/ApiClient"
import { BUSY, UNSAVED, editorMachine, valuesKey } from "./editorMachine"

export interface EditorOperations<TPayload> {
	/**
	 * load the document: answers its revision and how to show it. The editor is told it is loaded before it is shown, so the first values the form
	 * reports about it are its baseline
	 */
	load?: () => Promise<{ rev: string | undefined, show?: () => void }>
	/** save what the editor holds over revision `rev`; answers the new revision. A 409 is a conflict; any other failure keeps the edits */
	save: (payload: TPayload, rev: string | undefined) => Promise<string | undefined>
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
	/** Nothing is loaded (none chosen). */
	function unload() {
		actor.send({ type: "UNLOAD" })
	}
	async function load(event: "LOAD" | "DISCARD" | "TAKE_THEIRS" = "LOAD"): Promise<boolean> {
		if(!ops.load || !state.value.can({ type: event })) return false
		actor.send({ type: event })
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
	/** In a conflict: keep my edits, to be saved over theirs. */
	function keep(): boolean {
		if(!state.value.can({ type: "KEEP" })) return false
		actor.send({ type: "KEEP" })
		return true
	}
	/** In a conflict: drop my edits and load theirs. */
	const takeTheirs = () => load("TAKE_THEIRS")
	/** Drop my edits and load the document again. */
	const discard = () => load("DISCARD")
	const stop = () => actor.stop()

	return { state, hasUnsaved, isBusy, canSave, inConflict, canKeep, rev, values, edit, loaded, unload, load, save, keep, takeTheirs, discard, stop }
}
