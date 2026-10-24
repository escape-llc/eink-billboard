import { describe, expect, it } from "vitest"
import { createActor, type SnapshotFrom } from "xstate"
import { getShortestPaths } from "@xstate/graph"
import { BUSY, UNSAVED, editorMachine, valuesKey, type EditorEvent } from "./editorMachine"

type Snap = SnapshotFrom<typeof editorMachine>

// the events the paths are made of: two sets of values (A is what loads, B an edit), one of them invalid, and both answers a conflict can have
const EVENTS: EditorEvent[] = [
	{ type: "LOAD" }, { type: "LOADED", rev: "r1" }, { type: "LOAD_FAILED" },
	{ type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: true }, { type: "VALUES", key: "B", valid: false },
	{ type: "EDIT" }, { type: "SAVE" }, { type: "SAVED", rev: "r2" },
	{ type: "CONFLICT", rev: "r9" }, { type: "CONFLICT" }, { type: "SAVE_FAILED" },
	{ type: "KEEP" }, { type: "TAKE_THEIRS" }, { type: "DISCARD" }, { type: "UNLOAD" }, { type: "REVISED", rev: "r5" },
]

/** What must hold in every state any path reaches. */
function invariants(snap: Snap) {
	const { context } = snap
	// unsaved work is exactly: changed values, an edit that cannot be compared, a save under way, or a conflict
	const unsaved = snap.matches("dirty") || snap.matches("saving") || snap.matches("conflict")
	expect(snap.hasTag(UNSAVED)).toBe(unsaved)
	// clean means the values are the baseline; dirty that they are not
	if(snap.matches("clean")) {
		expect(context.current).toBe(context.baseline)
		expect(context.sticky).toBe(false)
	}
	// dirty: the values differ, or an edit it could not compare (or mine kept in a conflict) holds it there
	if(snap.matches("dirty")) expect(context.current !== context.baseline || context.sticky).toBe(true)
	// invalid values are never saved
	if(snap.can({ type: "SAVE" })) expect(context.valid).toBe(true)
	// a save is made only after a load, and is busy while it waits
	if(snap.matches("saving")) {
		expect(snap.hasTag(BUSY)).toBe(true)
		expect(context.saving).not.toBeNull()
	}
	if(snap.matches("empty")) expect(context.rev).toBeUndefined()
}

function replay(events: EditorEvent[]): Snap {
	const actor = createActor(editorMachine).start()
	for(const event of events) actor.send(event)
	return actor.getSnapshot()
}

describe("editorMachine", () => {

	// every state reachable with these events, by its shortest path: each step's state keeps the invariants
	const paths = getShortestPaths(editorMachine, { events: EVENTS })
	it("reaches every state", () => {
		const reached = new Set(paths.map(path => String(path.state.value)))
		for(const name of ["empty", "loading", "failed", "settling", "clean", "dirty", "saving", "conflict"]) {
			expect(reached, name).toContain(name)
		}
	})
	for(const path of paths) {
		it(`keeps its rules: ${path.steps.map(step => step.event.type + ("key" in step.event ? ` ${step.event.key}${step.event.valid ? "" : "!"}` : "")).join(", ") || "start"}`, () => {
			const actor = createActor(editorMachine).start()
			invariants(actor.getSnapshot())
			for(const step of path.steps) {
				actor.send(step.event)
				invariants(actor.getSnapshot())
			}
		})
	}

	it("takes a new revision without touching what is unsaved", () => {
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: true }, { type: "REVISED", rev: "r5" }])
		expect([snap.matches("dirty"), snap.context.rev, snap.context.baseline]).toEqual([true, "r5", "A"])
	})
	it("is clean again when an edit is put back", () => {
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: true }, { type: "VALUES", key: "A", valid: true }])
		expect(snap.matches("clean")).toBe(true)
		expect(snap.hasTag(UNSAVED)).toBe(false)
	})
	it("takes the baseline from the first values after a load, not the document", () => {
		// the form filled in defaults: its first values are what "unchanged" means
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "with-defaults", valid: true }, { type: "VALUES", key: "with-defaults", valid: true }])
		expect(snap.matches("clean")).toBe(true)
		expect(snap.context.baseline).toBe("with-defaults")
	})
	it("saves over their revision after keeping mine in a conflict, so the next save is not refused again", () => {
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: true },
			{ type: "SAVE" }, { type: "CONFLICT", rev: "r9" }, { type: "KEEP" }])
		expect(snap.matches("dirty")).toBe(true)
		expect(snap.context.rev).toBe("r9")
		const saved = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: true },
			{ type: "SAVE" }, { type: "CONFLICT", rev: "r9" }, { type: "KEEP" }, { type: "SAVE" }, { type: "SAVED", rev: "r10" }])
		expect(saved.matches("clean")).toBe(true)
		expect(saved.context.rev).toBe("r10")
		expect(saved.context.baseline).toBe("B")
	})
	it("cannot keep mine when the conflict did not say their revision", () => {
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: true }, { type: "SAVE" }, { type: "CONFLICT" }])
		expect(snap.can({ type: "KEEP" })).toBe(false)
		expect(snap.can({ type: "TAKE_THEIRS" })).toBe(true)
	})
	it("stays dirty when the values changed while saving", () => {
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: true },
			{ type: "SAVE" }, { type: "VALUES", key: "C", valid: true }, { type: "SAVED", rev: "r2" }])
		expect(snap.matches("dirty")).toBe(true)
		expect(snap.context.baseline).toBe("B")
	})
	it("keeps the edits when a save fails", () => {
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: true }, { type: "SAVE" }, { type: "SAVE_FAILED" }])
		expect(snap.matches("dirty")).toBe(true)
		expect(snap.context.rev).toBe("r1")
	})
	it("does not save invalid values", () => {
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "VALUES", key: "B", valid: false }])
		expect(snap.can({ type: "SAVE" })).toBe(false)
	})
	it("lets a document that is not stored be saved as loaded (created from its defaults)", () => {
		const snap = replay([{ type: "LOADED" }, { type: "VALUES", key: "A", valid: true }])
		expect(snap.can({ type: "SAVE" })).toBe(true)
	})
	it("holds an edit it cannot compare until saved or discarded", () => {
		const snap = replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "EDIT" }, { type: "VALUES", key: "A", valid: true }])
		expect(snap.hasTag(UNSAVED)).toBe(true)
		expect(replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "EDIT" }, { type: "DISCARD" }]).matches("loading")).toBe(true)
		// a failed save does not forget it
		expect(replay([{ type: "LOADED", rev: "r1" }, { type: "VALUES", key: "A", valid: true }, { type: "EDIT" }, { type: "SAVE" }, { type: "SAVE_FAILED" },
			{ type: "VALUES", key: "A", valid: true }]).hasTag(UNSAVED)).toBe(true)
	})
})

describe("valuesKey", () => {
	it("reads unset as missing and ignores the document's own keys and key order", () => {
		expect(valuesKey({ a: 1, b: null, c: "", _rev: "x" })).toBe(valuesKey({ a: 1 }))
		expect(valuesKey({ b: 2, a: 1 })).toBe(valuesKey({ a: 1, b: 2 }))
		expect(valuesKey({ a: { y: null, x: 1 } })).toBe(valuesKey({ a: { x: 1 } }))
	})
	it("tells real changes apart", () => {
		expect(valuesKey({ a: 1 })).not.toBe(valuesKey({ a: 2 }))
		expect(valuesKey({ a: 0 })).not.toBe(valuesKey({}))
		expect(valuesKey({ a: false })).not.toBe(valuesKey({}))
		expect(valuesKey({ a: [1, 2] })).not.toBe(valuesKey({ a: [2, 1] }))
	})
})
