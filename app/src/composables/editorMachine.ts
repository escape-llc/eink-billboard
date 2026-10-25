/**
 * The editor cycle as one state machine (#550): load, edit, save, conflict, discard, leave, for any editor of a stored document (a settings page, a
 * playlist, a scheduled task). The machine holds the state and the revision; the document itself stays with the editor, which reports what happened
 * (the values it holds now, a load or a save that finished) as events. `useEditor` runs the loads and saves and sends their outcomes, so the machine is
 * pure: every path through it can be generated and tested (editorMachine.test.ts).
 *
 * Dirty is a comparison, not a count of edits: `VALUES` carries a key of the values the editor holds (`valuesKey`), and the editor is `dirty` while that
 * differs from the baseline, the key of what was loaded or last saved; edit a field and put it back, and it is `clean` again. The baseline is taken from
 * the first `VALUES` after a load (`settling`), because a form fills in defaults and masks after it opens: the raw document would look changed.
 *
 * Someone else may change the stored document while it is open (another tab, the device's command line, a restore: the server's `changed` events,
 * #549). `REMOTE_CHANGED` says so, once the editor has checked that the stored revision is not its own: with nothing unsaved the document is loaded
 * again, and with edits it is `stale`, still unsaved, until the person reloads or keeps editing (a save then is refused as a conflict, which asks again).
 */
import { assign, setup } from "xstate"

export interface EditorContext {
	/** the revision the editor loaded or last saved (`_rev`); a save sends it, and a stale one is a conflict */
	rev: string | undefined
	/** in a conflict: the server's revision from the 409 (undefined when it did not say: keeping mine then needs a reload) */
	theirs: string | undefined
	/** the key of what was loaded or last saved (null until the first values after a load) */
	baseline: string | null
	/** the key of what the editor holds now */
	current: string | null
	/** whether what the editor holds passes its rules */
	valid: boolean
	/** the key of what is being saved, the new baseline when the save succeeds */
	saving: string | null
	/** unsaved whatever the values: an edit the editor could not compare, or my edits kept over theirs in a conflict (cleared by a load or a save) */
	sticky: boolean
}

export type EditorEvent =
	/** the editor starts loading its document (or loading it again) */
	| { type: "LOAD" }
	/** a document was loaded (or handed to the editor) at this revision */
	| { type: "LOADED", rev?: string }
	| { type: "LOAD_FAILED" }
	/** the values the editor holds now: their key and whether they pass the rules */
	| { type: "VALUES", key: string, valid: boolean }
	/** an edit the editor cannot compare (a container without a comparison): unsaved until saved or discarded */
	| { type: "EDIT" }
	| { type: "SAVE" }
	/** the save succeeded; the server's new revision */
	| { type: "SAVED", rev?: string }
	/** the save was refused because someone else saved first (409); the server's revision when it said */
	| { type: "CONFLICT", rev?: string }
	/** the save failed otherwise (a field's problem, the network): the edits are kept */
	| { type: "SAVE_FAILED" }
	/** in a conflict: keep my edits, to be saved over theirs */
	| { type: "KEEP" }
	/** in a conflict: drop my edits and load theirs */
	| { type: "TAKE_THEIRS" }
	/** drop the edits and load the document again */
	| { type: "DISCARD" }
	/** the editor has nothing loaded (none chosen) */
	| { type: "UNLOAD" }
	/** the stored document has a new revision with the edits still the editor's (a playlist renamed on its own): what is unsaved does not change */
	| { type: "REVISED", rev: string }
	/**
	 * someone else saved the document (its stored revision is not the editor's): load it again, or, with edits, say it is stale. `held`: the editor
	 * holds work the machine does not compare (a playlist's track being edited, not applied yet), which a load would drop, so it is stale too
	 */
	| { type: "REMOTE_CHANGED", held?: boolean }

/** The tag of every state that holds work the server does not have: leaving the page asks first. */
export const UNSAVED = "unsaved"
/** The tag of the states that wait for the server. */
export const BUSY = "busy"

const initial = (): EditorContext => ({ rev: undefined, theirs: undefined, baseline: null, current: null, valid: false, saving: null, sticky: false })

export const editorMachine = setup({
	types: {
		context: {} as EditorContext,
		events: {} as EditorEvent,
	},
	guards: {
		valid: ({ context }) => context.valid,
		changed: ({ context, event }) => event.type === "VALUES" && event.key !== context.baseline,
		unchanged: ({ context, event }) => event.type === "VALUES" && event.key === context.baseline && !context.sticky,
		knowsTheirs: ({ context }) => context.theirs !== undefined,
		held: ({ event }) => event.type === "REMOTE_CHANGED" && event.held === true,
		stillAsSaved: ({ context }) => context.current === context.saving,
		asLoaded: ({ context }) => context.current === context.baseline && !context.sticky,
	},
	actions: {
		values: assign(({ event }) => event.type === "VALUES" ? { current: event.key, valid: event.valid } : {}),
		loaded: assign(({ event }) => ({ ...initial(), rev: event.type === "LOADED" ? event.rev : undefined })),
		// the first values after a load are the baseline
		settle: assign(({ event }) => event.type === "VALUES" ? { baseline: event.key, current: event.key, valid: event.valid } : {}),
		startSave: assign(({ context }) => ({ saving: context.current, theirs: undefined })),
		saved: assign(({ context, event }) => ({ rev: event.type === "SAVED" ? event.rev ?? context.rev : context.rev, baseline: context.saving, saving: null, sticky: false })),
		conflict: assign(({ event }) => ({ theirs: event.type === "CONFLICT" ? event.rev : undefined, saving: null })),
		// keeping mine: the next save is made over their revision, so it is not refused again
		keep: assign(({ context }) => ({ rev: context.theirs, theirs: undefined, sticky: true })),
		edit: assign({ sticky: true }),
		failed: assign({ saving: null }),
		clear: assign(() => initial()),
		revised: assign(({ event }) => event.type === "REVISED" ? { rev: event.rev } : {}),
	},
}).createMachine({
	id: "editor",
	initial: "empty",
	context: initial,
	on: {
		LOADED: { target: ".settling", actions: "loaded" },
		UNLOAD: { target: ".empty", actions: "clear" },
	},
	states: {
		empty: {
			on: { LOAD: "loading" },
		},
		loading: {
			tags: [BUSY],
			on: { LOAD_FAILED: "failed" },
		},
		failed: {
			on: { LOAD: "loading" },
		},
		settling: {
			on: {
				VALUES: { target: "clean", actions: "settle" },
				EDIT: { target: "dirty", actions: "edit" },
				LOAD: "loading",
				REVISED: { actions: "revised" },
				REMOTE_CHANGED: [{ guard: "held", target: "stale" }, { target: "loading" }],
			},
		},
		clean: {
			on: {
				VALUES: [{ guard: "changed", target: "dirty", actions: "values" }, { actions: "values" }],
				EDIT: { target: "dirty", actions: "edit" },
				// saving what was loaded is allowed: a document that is not stored yet is created from its defaults
				SAVE: { guard: "valid", target: "saving", actions: "startSave" },
				LOAD: "loading",
				REVISED: { actions: "revised" },
				// nothing would be lost: show theirs (unless the editor holds work of its own)
				REMOTE_CHANGED: [{ guard: "held", target: "stale" }, { target: "loading" }],
			},
		},
		dirty: {
			tags: [UNSAVED],
			on: {
				VALUES: [{ guard: "unchanged", target: "clean", actions: "values" }, { actions: "values" }],
				EDIT: { actions: "edit" },
				SAVE: { guard: "valid", target: "saving", actions: "startSave" },
				DISCARD: "loading",
				REVISED: { actions: "revised" },
				REMOTE_CHANGED: "stale",
			},
		},
		// someone else saved while there are edits: they stay, unsaved, until the person reloads (theirs) or keeps editing
		stale: {
			tags: [UNSAVED],
			on: {
				VALUES: { actions: "values" },
				EDIT: { actions: "edit" },
				// still over the revision that was loaded: the server refuses it, and the conflict asks whether to overwrite
				SAVE: { guard: "valid", target: "saving", actions: "startSave" },
				// keep editing: unsaved until saved (the conflict then asks) or discarded, whatever the values (work it does not compare may be kept)
				KEEP: { target: "dirty", actions: "edit" },
				TAKE_THEIRS: "loading",
				DISCARD: "loading",
				REVISED: { actions: "revised" },
			},
		},
		saving: {
			tags: [UNSAVED, BUSY],
			on: {
				VALUES: { actions: "values" },
				EDIT: { actions: "edit" },
				SAVED: [{ guard: "stillAsSaved", target: "clean", actions: "saved" }, { target: "dirty", actions: "saved" }],
				CONFLICT: { target: "conflict", actions: "conflict" },
				// the edits are kept; an unchanged document (saved to create it) is clean again
				SAVE_FAILED: [{ guard: "asLoaded", target: "clean", actions: "failed" }, { target: "dirty", actions: "failed" }],
			},
		},
		conflict: {
			tags: [UNSAVED],
			on: {
				VALUES: { actions: "values" },
				KEEP: { guard: "knowsTheirs", target: "dirty", actions: "keep" },
				TAKE_THEIRS: "loading",
			},
		},
	},
})

/**
 * A key of a form's values for comparing them with the baseline: keys in order, a document's own keys (`_id`, `_rev`) left out, and unset values
 * (`null`, `undefined`, `""`) the same as a missing key, so a field the form fills with `null` does not count as an edit. A list keeps its order.
 */
export function valuesKey(values: unknown): string {
	return JSON.stringify(canonical(values)) ?? ""
}

function canonical(value: unknown): unknown {
	if(Array.isArray(value)) return value.map(item => canonical(item) ?? null)
	if(value !== null && typeof value === "object") {
		const out: Record<string, unknown> = {}
		for(const key of Object.keys(value).sort()) {
			if(key.startsWith("_")) continue
			const inner = canonical((value as Record<string, unknown>)[key])
			if(inner !== undefined) out[key] = inner
		}
		return out
	}
	if(value === null || value === undefined || value === "") return undefined
	return value
}
