import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "../api/client"
import { inApp } from "../api/inApp"
import { settle } from "../api/fakeLink"
import { Transport } from "../components/Transport"
import { PLAYLIST_LIST, usePlaylistPanel } from "./usePlaylistPanel"

// the panel without the page: the API is a stand-in, the transport a real one that is told where the layer is
vi.mock("../api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }))
const mocked = api as unknown as Record<"get", ReturnType<typeof vi.fn>>

const track = (id: string) => ({ id, title: `Track ${id}`, plugin_name: "slide-show", type: "PlaylistSchedule", content: {} })
const playlist = (id: string, ...ids: string[]) => ({ id, name: `List ${id}`, _rev: "r1", _schema: "playlist-1", items: ids.map(track) })
function serve(...playlists: object[]) {
	mocked.get.mockImplementation(async (path: string) => {
		if (path === PLAYLIST_LIST) return { success: true, playlists }
		throw new Error(`no route ${path}`)
	})
}
function panel() {
	const transport = new Transport()
	const p = inApp(() => usePlaylistPanel({ transport }))
	p.start()
	return { p, transport }
}

beforeEach(() => { mocked.get.mockReset() })

describe("the playlist panel", () => {
	it("shows the playlist the layer is on, with the track it is playing", async () => {
		serve(playlist("a", "t1", "t2"), playlist("b", "t3", "t4", "t5"))
		const { p, transport } = panel()
		await settle()
		Object.assign(transport.state, { playlistId: "b", trackId: "t4" })
		expect([p.playlist.value?.name, p.tracks.value.map(t => t.id), p.playing.value]).toEqual(["List b", ["t3", "t4", "t5"], 1])
		// the next track the layer says
		Object.assign(transport.state, { trackId: "t5" })
		expect(p.playing.value).toBe(2)
	})

	it("before the first track, shows the only playlist with nothing playing, and none when there are several", async () => {
		serve(playlist("a", "t1", "t2"))
		const one = panel()
		await settle()
		expect([one.p.playlist.value?.id, one.p.playing.value]).toEqual(["a", -1])
		serve(playlist("a", "t1"), playlist("b", "t2"))
		const two = panel()
		await settle()
		expect(two.p.playlist.value).toBeNull()
	})

	it("shows nothing playing when the track the layer is on is no longer in the playlist", async () => {
		serve(playlist("a", "t1", "t2"))
		const { p, transport } = panel()
		await settle()
		Object.assign(transport.state, { playlistId: "a", trackId: "gone" })
		expect([p.playlist.value?.id, p.playing.value]).toEqual(["a", -1])
	})
})
