import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "../components/ApiClient"
import { api } from "../api/client"
import { inApp } from "../api/inApp"
import { changedEvent, fakeLink, settle } from "../api/fakeLink"
import { documentBody, splitServerErrors, usePlaylists } from "./usePlaylists"
import type { PlaylistItem } from "../components/ScheduleDefs"

// the playlist page's data without the page: the API is a stand-in, and what the page would show as a toast is collected
vi.mock("../api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
const mocked = api as unknown as Record<"get" | "post" | "put" | "patch" | "delete", ReturnType<typeof vi.fn>>

const SLIDES = { id: "slide-show", name: "Slide Show", features: ["layer-background"], instanceSettings: {} }
const OVERLAY = { id: "overlay", name: "Overlay", features: ["layer-overlay"], instanceSettings: {} }
const track = (id: string, title = id): PlaylistItem => ({ id, title, plugin_name: "slide-show", type: "PlaylistSchedule", content: { n: 1 } }) as PlaylistItem
const doc = (id: string, items: PlaylistItem[], rev = "r1") => ({ id, name: `Playlist ${id}`, _rev: rev, items })

function serve(playlists: object[]) {
	mocked.get.mockImplementation(async (path: string) => {
		if(path === "/api/plugins/list") return [SLIDES, OVERLAY]
		if(path === "/api/datasources/list") return []
		if(path === "/api/schedule/playlist/list") return { playlists }
		throw new Error(`no route ${path}`)
	})
}
async function started(playlists: object[] = [doc("a", [track("t1"), track("t2"), track("t3")]), doc("b", [])]) {
	serve(playlists)
	const notices: string[] = []
	const pl = inApp(() => usePlaylists((severity, detail) => notices.push(`${severity}: ${detail}`)))
	await pl.start()
	return { pl, notices }
}

beforeEach(() => { for(const fn of Object.values(mocked)) fn.mockReset() })

describe("loading", () => {
	it("loads the plugins, the data sources and the playlists, and edits the first", async () => {
		const { pl, notices } = await started()
		expect(pl.loading.value).toBe(false)
		expect(pl.playlists.value).toEqual([{ id: "a", name: "Playlist a" }, { id: "b", name: "Playlist b" }])
		expect([pl.currentId.value, pl.docRev.value]).toEqual(["a", "r1"])
		expect(pl.tracks.value.map(t => t.id)).toEqual(["t1", "t2", "t3"])
		expect(pl.dirty.value).toBe(false)
		// only the plugins of the playlist's layers are offered for a new track
		expect(pl.pluginOptions.value).toEqual([{ id: "slide-show", name: "Slide Show" }])
		expect(notices).toEqual([])
	})

	it("a device with no playlist is an empty page, not an error", async () => {
		const { pl, notices } = await started([])
		expect(pl.currentId.value).toBeUndefined()
		expect(pl.tracks.value).toEqual([])
		expect(notices).toEqual([])
	})

	it("a part that fails to load is a notice, and the page still loads", async () => {
		serve([doc("a", [])])
		const base = mocked.get.getMockImplementation() as (path: string) => Promise<unknown>
		mocked.get.mockImplementation(async (path: string) => path === "/api/plugins/list" ? Promise.reject(new Error("down")) : base(path))
		const notices: string[] = []
		const pl = inApp(() => usePlaylists((s, d) => notices.push(`${s}: ${d}`)))
		await pl.start()
		expect(notices).toEqual(["error: Failed to load the plugins: down"])
		expect(pl.plugins.value).toEqual([])
		expect(pl.currentId.value).toBe("a")
		expect(pl.loading.value).toBe(false)
	})
})

describe("the working copy", () => {
	it("a new track is a draft: no change until it is applied, and cancel leaves nothing behind", async () => {
		const { pl } = await started()
		pl.addTrack()
		expect(pl.draft.value?.title).toBe("Untitled")
		expect(pl.selectedTrack.value).toBe(pl.draft.value)
		expect([pl.dirty.value, pl.tracks.value.length]).toEqual([false, 3])
		pl.cancelEdit()
		expect(pl.draft.value).toBeNull()
		expect(pl.dirty.value).toBe(false)

		pl.addTrack()
		pl.editModel.title = "Fresh"
		pl.applyEdit({ n: 2 })
		expect(pl.tracks.value.map(t => t.title)).toEqual(["t1", "t2", "t3", "Fresh"])
		expect(pl.tracks.value[3]?.content).toEqual({ n: 2 })
		expect(pl.selectedIndex.value).toBe(3)
		expect(pl.dirty.value).toBe(true)
	})

	it("applying an edit changes the track; the editor held a copy until then", async () => {
		const { pl } = await started()
		pl.selectTrack(1)
		pl.editModel.title = "Renamed"
		pl.editModel.content.n = 9
		expect(pl.tracks.value[1]?.title).toBe("t2")
		expect(pl.tracks.value[1]?.content).toEqual({ n: 1 })
		pl.applyEdit({ n: 9 })
		expect(pl.tracks.value[1]).toMatchObject({ id: "t2", title: "Renamed", content: { n: 9 } })
		expect(pl.dirty.value).toBe(true)
	})

	it("choosing another track drops a draft", async () => {
		const { pl } = await started()
		pl.addTrack()
		pl.selectTrack(0)
		expect(pl.draft.value).toBeNull()
		expect(pl.editModel.id).toBe("t1")
	})

	it("moving and removing keep the selection on the same track", async () => {
		const { pl } = await started()
		pl.selectTrack(2)
		pl.moveTrack(2, -1)
		expect(pl.tracks.value.map(t => t.id)).toEqual(["t1", "t3", "t2"])
		expect(pl.selectedIndex.value).toBe(1)
		pl.removeTrack(0)
		expect(pl.selectedIndex.value).toBe(0)
		expect(pl.tracks.value[0]?.id).toBe("t3")
		pl.removeTrack(0)
		expect(pl.selectedIndex.value).toBeNull()
		// a move past either end does nothing
		pl.moveTrack(0, -1)
		expect(pl.tracks.value.map(t => t.id)).toEqual(["t2"])
		expect(pl.dirty.value).toBe(true)
	})
})

describe("unsaved is a comparison", () => {
	it("a track moved and moved back, or added and removed, is no change", async () => {
		const { pl } = await started()
		pl.moveTrack(0, 1)
		expect(pl.dirty.value).toBe(true)
		pl.moveTrack(1, -1)
		expect(pl.dirty.value).toBe(false)
		pl.addTrack()
		pl.applyEdit({})
		expect(pl.dirty.value).toBe(true)
		pl.removeTrack(3)
		expect(pl.dirty.value).toBe(false)
	})

	it("discarding puts the playlist back as it was loaded, without asking the server", async () => {
		const { pl } = await started()
		pl.removeTrack(0)
		const calls = mocked.get.mock.calls.length
		pl.discardChanges()
		expect(pl.tracks.value.map(t => t.id)).toEqual(["t1", "t2", "t3"])
		expect(pl.dirty.value).toBe(false)
		expect(mocked.get.mock.calls.length).toBe(calls)
	})
})

describe("saving", () => {
	it("sends the whole playlist at the loaded revision, and keeps the track in the editor", async () => {
		const { pl, notices } = await started()
		pl.addTrack()
		pl.applyEdit({})
		pl.selectTrack(1)
		mocked.put.mockResolvedValue({ schedule: doc("a", [track("t1"), track("t2"), track("t3"), track("t4", "Untitled")], "r2"), rev: "r2" })
		await pl.savePlaylist(() => 0)
		const [path, options, body] = mocked.put.mock.calls[0]!
		expect([path, options]).toEqual(["/api/schedule/playlist/{doc_id}", { path: { doc_id: "a" } }])
		expect(body._rev).toBe("r1")
		// the new track goes without the id of ours; the server gives it one
		expect(body.items[3]).not.toHaveProperty("id")
		expect(pl.docRev.value).toBe("r2")
		expect(pl.dirty.value).toBe(false)
		expect(pl.selectedIndex.value).toBe(1)
		expect(notices).toEqual(["success: Playlist saved"])
	})

	it("a stale revision is a conflict that carries the server's", async () => {
		const { pl } = await started()
		mocked.put.mockRejectedValue(new ApiError(409, "Revision mismatch", { rev: "r9" }))
		await pl.savePlaylist(() => 0)
		expect(pl.conflict.value).toEqual({ message: "Revision mismatch", rev: "r9" })
		expect(pl.saving.value).toBe(false)
	})

	it("overwrite saves the working copy over the server's revision, and is then saved", async () => {
		const { pl } = await started()
		pl.removeTrack(0)
		mocked.put.mockRejectedValueOnce(new ApiError(409, "Revision mismatch", { rev: "r9" }))
		await pl.savePlaylist(() => 0)
		expect(pl.dirty.value).toBe(true)
		mocked.put.mockResolvedValueOnce({ schedule: doc("a", [track("t2"), track("t3")], "r10"), rev: "r10" })
		await pl.overwritePlaylist(() => 0)
		expect(mocked.put.mock.calls[1]![2]._rev).toBe("r9")
		expect([pl.conflict.value, pl.dirty.value, pl.docRev.value]).toEqual([null, false, "r10"])
	})

	it("a conflict the server did not give a revision for can only be reloaded", async () => {
		const { pl } = await started()
		pl.removeTrack(0)
		mocked.put.mockRejectedValueOnce(new ApiError(409, "Revision mismatch"))
		await pl.savePlaylist(() => 0)
		expect(pl.conflict.value).toEqual({ message: "Revision mismatch", rev: undefined })
		await pl.overwritePlaylist(() => 0)
		expect(mocked.put).toHaveBeenCalledTimes(1)
		await pl.reloadPlaylist()
		expect([pl.conflict.value, pl.dirty.value, pl.tracks.value.length]).toEqual([null, false, 3])
	})

	it("a save that fails otherwise keeps the edits", async () => {
		const { pl, notices } = await started()
		pl.removeTrack(0)
		mocked.put.mockRejectedValueOnce(new Error("offline"))
		await pl.savePlaylist(() => 0)
		expect([pl.dirty.value, pl.tracks.value.length]).toEqual([true, 2])
		expect(notices).toEqual(["error: Failed to save the playlist: offline"])
	})

	it("a 422 shows on the selected track's fields, and lists the rest with their track", async () => {
		const { pl } = await started()
		pl.selectTrack(0)
		mocked.put.mockRejectedValue(new ApiError(422, "Invalid", { errors: [
			{ path: ["items", "0", "content", "slideMinutes"], message: "Minimum 1" },
			{ path: ["items", "2", "content", "folder"], message: "Required" },
		] }))
		const shown: unknown[] = []
		await pl.savePlaylist((errors: unknown[]) => { shown.push(...errors); return errors.length })
		expect(shown).toEqual([{ path: ["slideMinutes"], message: "Minimum 1" }])
		expect(pl.serverProblems.value).toEqual(['Track "t3": content / folder: Required'])
	})

	it("a field the form could not show is listed instead of lost", async () => {
		const { pl } = await started()
		pl.selectTrack(0)
		mocked.put.mockRejectedValue(new ApiError(422, "Invalid", { errors: [{ path: ["items", "0", "content", "gone"], message: "Required" }] }))
		await pl.savePlaylist(() => 0)
		expect(pl.serverProblems.value).toEqual(["Invalid"])
	})
})

describe("the playlists", () => {
	it("a rename changes the name and the revision, and keeps the unsaved edits", async () => {
		const { pl } = await started()
		pl.removeTrack(0)
		mocked.patch.mockResolvedValue({ schedule: { name: "New name" }, rev: "r5" })
		expect(await pl.renamePlaylist("New name")).toBe("done")
		expect(mocked.patch.mock.calls[0]![2]).toEqual({ name: "New name", _rev: "r1" })
		expect([pl.playlistName.value, pl.docRev.value]).toEqual(["New name", "r5"])
		expect(pl.playlists.value[0]).toEqual({ id: "a", name: "New name" })
		expect(pl.dirty.value).toBe(true)
		expect(pl.tracks.value.length).toBe(2)
		// the next save is made over the rename's revision
		mocked.put.mockResolvedValueOnce({ schedule: doc("a", [track("t2"), track("t3")], "r6"), rev: "r6" })
		await pl.savePlaylist(() => 0)
		expect(mocked.put.mock.calls[0]![2]._rev).toBe("r5")
	})

	it("a new playlist is created and opened; a conflict and a failure say which", async () => {
		const { pl, notices } = await started()
		mocked.post.mockResolvedValueOnce({ id: "b" })
		expect(await pl.createPlaylist("Second")).toBe("done")
		expect(pl.currentId.value).toBe("b")

		mocked.patch.mockRejectedValueOnce(new ApiError(409, "Revision mismatch"))
		expect(await pl.renamePlaylist("x")).toBe("conflict")
		expect(pl.conflict.value?.message).toBe("The playlist changed since it was loaded.")

		mocked.post.mockRejectedValueOnce(new Error("offline"))
		expect(await pl.createPlaylist("Third")).toBe("failed")
		expect(notices).toEqual(["error: Failed: offline"])
	})

	it("deleting opens the next playlist; a stale revision is a conflict", async () => {
		const { pl, notices } = await started()
		mocked.delete.mockResolvedValueOnce({})
		serve([doc("b", [])])
		await pl.deletePlaylist()
		expect(mocked.delete.mock.calls[0]).toEqual(["/api/schedule/playlist/{doc_id}", { path: { doc_id: "a" }, query: { rev: "r1" } }])
		expect(pl.currentId.value).toBe("b")
		expect(notices).toEqual(["success: Playlist deleted"])

		mocked.delete.mockRejectedValueOnce(new ApiError(409, "Revision mismatch"))
		await pl.deletePlaylist()
		expect(pl.conflict.value?.message).toMatch(/reload it before deleting/)
	})
})

describe("changes made elsewhere", () => {
	/** The page on the stored playlists `stored` (changed by the test), following a fake link. */
	async function following() {
		const stored = { list: [doc("a", [track("t1"), track("t2"), track("t3")]), doc("b", [])] }
		mocked.get.mockImplementation(async (path: string, init?: { path?: { doc_id?: string } }) => {
			if(path === "/api/plugins/list") return [SLIDES, OVERLAY]
			if(path === "/api/datasources/list") return []
			if(path === "/api/schedule/playlist/list") return { playlists: stored.list }
			if(path === "/api/schedule/playlist/{doc_id}") return { success: true, schedule: stored.list.find(p => p.id === init?.path?.doc_id) }
			throw new Error(`no route ${path}`)
		})
		const fake = fakeLink()
		const pl = inApp(() => usePlaylists(() => {}, { link: fake.link }))
		await pl.start()
		const elsewhere = (items: PlaylistItem[], rev = "r2") => {
			stored.list = [doc("a", items, rev), ...stored.list.slice(1)]
			fake.send(changedEvent("/api/schedule"))
			return settle().then(settle)
		}
		return { pl, fake, stored, elsewhere }
	}

	it("with nothing unsaved the playlist is loaded again, and the selected track stays selected where it moved", async () => {
		const { pl, elsewhere } = await following()
		pl.selectTrack(1)
		await elsewhere([track("t2", "Moved first"), track("t1"), track("t3")])
		expect(pl.tracks.value.map(t => t.title)).toEqual(["Moved first", "t1", "t3"])
		expect([pl.selectedIndex.value, pl.editModel.title, pl.docRev.value, pl.dirty.value, pl.isStale.value]).toEqual([0, "Moved first", "r2", false, false])
	})
	it("with unsaved changes it is stale: they stay until Reload, or Keep editing", async () => {
		const { pl, elsewhere } = await following()
		pl.moveTrack(0, 1)
		await elsewhere([track("t1", "Theirs")])
		expect([pl.isStale.value, pl.dirty.value, pl.tracks.value.map(t => t.id)]).toEqual([true, true, ["t2", "t1", "t3"]])
		pl.keepEditing()
		expect([pl.isStale.value, pl.dirty.value, pl.docRev.value]).toEqual([false, true, "r1"])
	})
	it("Reload shows theirs", async () => {
		const { pl, elsewhere } = await following()
		pl.moveTrack(0, 1)
		await elsewhere([track("t1", "Theirs")])
		await pl.reloadPlaylist()
		expect([pl.isStale.value, pl.dirty.value, pl.tracks.value.map(t => t.title)]).toEqual([false, false, ["Theirs"]])
	})
	it("a track edited and not applied, or a draft, is not loaded over: it is stale", async () => {
		const { pl, elsewhere } = await following()
		pl.selectTrack(0)
		pl.trackPending.value = true
		await elsewhere([track("t1", "Theirs")])
		expect([pl.isStale.value, pl.tracks.value.length]).toEqual([true, 3])

		const other = await following()
		other.pl.addTrack()
		await other.elsewhere([track("t1", "Theirs")])
		expect([other.pl.isStale.value, other.pl.draft.value?.title]).toEqual([true, "Untitled"])
	})
	it("its own save is no change", async () => {
		const { pl, stored, fake } = await following()
		pl.moveTrack(0, 1)
		mocked.put.mockImplementation(async (_path: string, _init: unknown, body: { items: PlaylistItem[] }) => {
			stored.list = [doc("a", JSON.parse(JSON.stringify(body.items)), "r2")]
			return { success: true, rev: "r2", schedule: stored.list[0] }
		})
		await pl.savePlaylist(() => 0)
		const asked = mocked.get.mock.calls.length
		fake.send(changedEvent("/api/schedule"))
		await settle()
		expect([pl.isStale.value, pl.dirty.value, pl.docRev.value]).toEqual([false, false, "r2"])
		// the revision was asked for, and nothing loaded
		expect(mocked.get.mock.calls.slice(asked).map(c => c[0])).toEqual(["/api/schedule/playlist/{doc_id}"])
	})
})

describe("helpers", () => {
	it("the stored form drops the ids of new tracks and any revision of a track", () => {
		const items = [{ ...track("t1"), _rev: "x" }, track("new-abc")] as PlaylistItem[]
		expect(documentBody("P", items, "r1")).toEqual({ name: "P", _rev: "r1", items: [track("t1"), (({ id: _, ...rest }) => rest)(track("new-abc"))] })
	})

	it("a problem that names no track is listed as it is", () => {
		expect(splitServerErrors([{ path: ["name"], message: "Required" }], [], null, "Invalid")).toEqual({ onField: [], listed: ["Required"] })
		expect(splitServerErrors([{}], [], null, "Invalid")).toEqual({ onField: [], listed: ["Invalid"] })
	})
})
