import { describe, expect, it, vi } from "vitest"
import { ApiError } from "../components/ApiClient"
import type { LinkListener, TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"
import { useEditor } from "./useEditor"

// the editor's cycle with stand-in loads and saves: what the machine is told by each outcome
function editor(save = vi.fn(async (_payload: unknown, _rev: string | undefined) => "r2"), load = vi.fn(async () => ({ rev: "r1" as string | undefined }))) {
	const ed = useEditor<unknown>({ load, save })
	return { ed, save, load }
}
/** A loaded editor whose form reported `values` first (the baseline) and then `edited`. */
function editing(ed: ReturnType<typeof useEditor<unknown>>, values: unknown = { a: 1 }, edited: unknown = { a: 2 }) {
	ed.loaded("r1")
	ed.values(values, true)
	ed.values(edited, true)
}

describe("useEditor", () => {
	it("is unsaved while the values differ from what was loaded, and not after they are put back", () => {
		const { ed } = editor()
		ed.loaded("r1")
		ed.values({ a: 1, b: null }, true)
		expect(ed.hasUnsaved.value).toBe(false)
		ed.values({ a: 2 }, true)
		expect(ed.hasUnsaved.value).toBe(true)
		ed.values({ a: 1 }, true)
		expect(ed.hasUnsaved.value).toBe(false)
	})
	it("saves over the loaded revision and takes the new one", async () => {
		const { ed, save } = editor()
		editing(ed)
		expect(await ed.save({ a: 2 })).toEqual({ outcome: "saved" })
		expect(save).toHaveBeenCalledWith({ a: 2 }, "r1")
		expect(ed.rev.value).toBe("r2")
		expect(ed.hasUnsaved.value).toBe(false)
	})
	it("does not save invalid values", async () => {
		const { ed, save } = editor()
		ed.loaded("r1")
		ed.values({ a: 1 }, true)
		ed.values({ a: "" }, false)
		expect(ed.canSave.value).toBe(false)
		expect((await ed.save({})).outcome).toBe("refused")
		expect(save).not.toHaveBeenCalled()
	})
	it("turns a 409 into a conflict; keeping mine saves over their revision", async () => {
		const save = vi.fn()
			.mockRejectedValueOnce(new ApiError(409, "Changed elsewhere", { success: false, rev: "r9" }))
			.mockResolvedValueOnce("r10")
		const { ed } = editor(save)
		editing(ed)
		const first = await ed.save({ a: 2 })
		expect(first.outcome).toBe("conflict")
		expect((first.error as ApiError).message).toBe("Changed elsewhere")
		expect(ed.inConflict.value).toBe(true)
		expect(ed.hasUnsaved.value).toBe(true)
		expect(ed.keep()).toBe(true)
		expect((await ed.save({ a: 2 })).outcome).toBe("saved")
		expect(save).toHaveBeenLastCalledWith({ a: 2 }, "r9")
		expect(ed.rev.value).toBe("r10")
	})
	it("cannot keep mine when the 409 did not say their revision, and takes theirs by loading", async () => {
		const { ed, load } = editor(vi.fn().mockRejectedValue(new ApiError(409, "Changed", { success: false })), vi.fn(async () => ({ rev: "r5" })))
		editing(ed)
		await ed.save({ a: 2 })
		expect(ed.canKeep.value).toBe(false)
		expect(ed.keep()).toBe(false)
		expect(await ed.takeTheirs()).toBe(true)
		expect(load).toHaveBeenCalled()
		expect(ed.rev.value).toBe("r5")
		expect(ed.state.value.matches("settling")).toBe(true)
	})
	it("keeps the edits when a save fails otherwise", async () => {
		const { ed } = editor(vi.fn().mockRejectedValue(new ApiError(422, "Problems", { errors: [] })))
		editing(ed)
		const result = await ed.save({ a: 2 })
		expect(result.outcome).toBe("failed")
		expect(ed.hasUnsaved.value).toBe(true)
		expect(ed.rev.value).toBe("r1")
	})
	it("tells the machine a document is loaded before it is shown, so its first values are the baseline", async () => {
		const seen: string[] = []
		const { ed } = editor(undefined, vi.fn(async () => ({ rev: "r3", show: () => { seen.push(String(ed.state.value.value)); ed.values({ a: 9 }, true) } })))
		editing(ed)
		expect(await ed.discard()).toBe(true)
		expect(seen).toEqual(["settling"])
		expect(ed.state.value.matches("clean")).toBe(true)
		expect(ed.rev.value).toBe("r3")
	})
	it("discards by loading again; a load that fails is a state, not an exception", async () => {
		const { ed } = editor(undefined, vi.fn().mockRejectedValue(new Error("offline")))
		editing(ed)
		expect(await ed.discard()).toBe(false)
		expect(ed.state.value.matches("failed")).toBe(true)
		expect(ed.hasUnsaved.value).toBe(false)
	})
})

describe("useEditor follows its document", () => {
	/** A link that tells what a test sends. */
	function fakeLink() {
		const listeners = new Set<LinkListener>()
		const link = { listen: (l: LinkListener) => { listeners.add(l); return () => { listeners.delete(l) } } } as unknown as TelemetryLink
		return {
			link,
			listeners,
			send: (e: TelemetryEvent, replayed = false) => { for (const l of listeners) l.event?.(e, replayed) },
			resume: () => { for (const l of listeners) l.resumed?.() },
		}
	}
	const changed = (...paths: string[]): TelemetryEvent => ({ seq: 1, source: "application", kind: "config-changed", values: { area: "settings", changed: paths } })
	const settle = () => new Promise(resolve => setTimeout(resolve, 0))
	/** An editor of /api/settings/theme whose stored revision is `stored.rev`. */
	function following(save = vi.fn(async () => "r2")) {
		const fake = fakeLink()
		const stored = { rev: "r1" as string | undefined, fails: false }
		const revision = vi.fn(async () => { if(stored.fails) throw new Error("down"); return stored.rev })
		const load = vi.fn(async () => ({ rev: stored.rev }))
		const ed = useEditor<unknown>({ load, save, follow: { address: () => "/api/settings/theme", revision, link: fake.link } })
		return { ed, fake, stored, revision, load, save }
	}

	it("loads a document saved elsewhere again when nothing is unsaved", async () => {
		const { ed, fake, stored, load } = following()
		ed.loaded("r1")
		ed.values({ a: 1 }, true)
		stored.rev = "r3"
		fake.send(changed("/api/settings"))
		await settle()
		expect(load).toHaveBeenCalledTimes(1)
		expect([ed.rev.value, ed.state.value.value]).toEqual(["r3", "settling"])
	})
	it("is stale, with the edits kept, when something is unsaved", async () => {
		const { ed, fake, stored, load } = following()
		editing(ed)
		stored.rev = "r3"
		fake.send(changed("/api/settings/theme"))
		await settle()
		expect([ed.isStale.value, ed.hasUnsaved.value, load.mock.calls.length]).toEqual([true, true, 0])
		// keep editing: unsaved, over the revision that was loaded
		expect(ed.keep()).toBe(true)
		expect([ed.isStale.value, ed.hasUnsaved.value, ed.rev.value]).toEqual([false, true, "r1"])
	})
	it("takes theirs from the stale state by loading", async () => {
		const { ed, fake, stored, load } = following()
		editing(ed)
		stored.rev = "r3"
		fake.send(changed("/api/settings/theme"))
		await settle()
		expect(await ed.takeTheirs()).toBe(true)
		expect([load.mock.calls.length, ed.rev.value, ed.hasUnsaved.value]).toEqual([1, "r3", false])
	})
	it("hears its own save as no change: the stored revision is the editor's", async () => {
		const { ed, fake, stored, load } = following()
		editing(ed)
		await ed.save({ a: 2 })
		ed.values({ a: 2 }, true)
		stored.rev = "r2"
		fake.send(changed("/api/settings/theme"))
		await settle()
		expect([load.mock.calls.length, ed.hasUnsaved.value, ed.isStale.value]).toEqual([0, false, false])
	})
	it("asks nothing for a change of another document", async () => {
		const { ed, fake, revision } = following()
		editing(ed)
		fake.send(changed("/api/settings/system", "/api/plugins"))
		await settle()
		expect(revision).not.toHaveBeenCalled()
	})
	it("checks the history the link opens with: a save after the load is in it, and the revision tells an older one", async () => {
		const { ed, fake, revision, stored } = following()
		editing(ed)
		fake.send(changed("/api/settings/theme"), true)
		await settle()
		expect([revision.mock.calls.length, ed.isStale.value]).toEqual([1, false])
		stored.rev = "r3"
		fake.send(changed("/api/settings/theme"), true)
		await settle()
		expect(ed.isStale.value).toBe(true)
	})
	it("asks after missed events (a gap, the link coming back)", async () => {
		const { ed, fake, revision, stored } = following()
		editing(ed)
		fake.send({ source: "telemetry", kind: "gap", missed: 3 })
		await settle()
		fake.resume()
		await settle()
		expect(revision).toHaveBeenCalledTimes(2)
		expect(ed.isStale.value).toBe(false)
		stored.rev = "r4"
		fake.resume()
		await settle()
		expect(ed.isStale.value).toBe(true)
	})
	it("decides nothing when the revision cannot be had, or the editor moved on while it was asked", async () => {
		const { ed, fake, stored, revision } = following()
		editing(ed)
		stored.fails = true
		fake.send(changed("/api/settings/theme"))
		await settle()
		expect(ed.isStale.value).toBe(false)
		// a load while the revision was asked: the answer is about the revision before it
		stored.fails = false
		stored.rev = "r3"
		revision.mockImplementationOnce(async () => { ed.loaded("r5"); return "r3" })
		fake.send(changed("/api/settings/theme"))
		await settle()
		expect([ed.isStale.value, ed.rev.value]).toEqual([false, "r5"])
	})
	it("stops following when stopped", () => {
		const { ed, fake } = following()
		expect(fake.listeners.size).toBe(1)
		ed.stop()
		expect(fake.listeners.size).toBe(0)
	})
})
