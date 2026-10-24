import { describe, expect, it, vi } from "vitest"
import { ApiError } from "../components/ApiClient"
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
