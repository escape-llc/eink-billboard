import { beforeEach, describe, expect, it, vi } from "vitest"
import { useQueryCache } from "@pinia/colada"
import { apiJson } from "../components/ApiClient"
import { changedEvent as changed, fakeLink, settle } from "./fakeLink"
import { api } from "./client"
import { inApp } from "./inApp"
import { EVERYTHING, REPLAY_SETTLE_MS, changedHere, changedPaths, covers, followResource, invalidatePaths, keyOf, readResource, syncWithLink, useCatalog, type ResourceState } from "./resources"

vi.mock("../components/ApiClient", () => ({ apiJson: vi.fn(), joinUrl: (base: string, path: string) => `${base.replace(/\/$/, "")}/${path.replace(/^\//, "")}` }))
vi.mock("./client", () => ({ api: { get: vi.fn() } }))
const fetched = apiJson as unknown as ReturnType<typeof vi.fn>
const listed = api.get as unknown as ReturnType<typeof vi.fn>


beforeEach(() => {
	fetched.mockReset()
	listed.mockReset()
})

describe("keys", () => {
	it("a path's key is its segments, the query one last segment", () => {
		expect(keyOf("/api/plugins/list")).toEqual(["api", "plugins", "list"])
		expect(keyOf("/api/datasource/openai-api/lookups/qualities?imageModel=gpt-image-2")).toEqual(["api", "datasource", "openai-api", "lookups", "qualities", "?imageModel=gpt-image-2"])
		expect(keyOf("/api/x?")).toEqual(["api", "x"])
		expect(keyOf("api//x/")).toEqual(["api", "x"])
	})
	it("a path covers the keys it starts, by whole segments", () => {
		expect(covers("/api/schedule", keyOf("/api/schedule/playlist/list"))).toBe(true)
		expect(covers(EVERYTHING, keyOf("/api/lookups/providers/data-weather"))).toBe(true)
		expect(covers("/api/datasources/rss", keyOf("/api/datasources/rss/lookups/feed"))).toBe(true)
		// a segment is whole: the data sources' routes are not a data source's own router's, nor another source whose id starts the same
		expect(covers("/api/datasources", keyOf("/api/datasource/openai-api/models"))).toBe(false)
		expect(covers("/api/datasources/rss", keyOf("/api/datasources/rss2/settings"))).toBe(false)
		expect(covers("/api/schedule/tasks/render", keyOf("/api/schedule"))).toBe(false)
	})
	it("an event's changed paths are the API paths it names, nothing else", () => {
		expect(changedPaths(changed("/api/settings/theme", "/api"))).toEqual(["/api/settings/theme", "/api"])
		expect(changedPaths(changed(3, null, "/elsewhere", "/apix/y"))).toEqual([])
		expect(changedPaths({ source: "application", kind: "config-changed", values: { area: "settings" } })).toEqual([])
	})
})

describe("the cache follows the server's changes", () => {
	/** Follow an address; each answer is the next of `answers`. */
	function follow(address: string, answers: unknown[]) {
		for (const a of answers) fetched.mockResolvedValueOnce(a)
		const states: ResourceState<unknown>[] = []
		const { cache, stop, link } = inApp(() => {
			const cache = useQueryCache()
			const link = fakeLink()
			syncWithLink(cache, link.link)
			return { cache, link, stop: followResource(cache, address, s => states.push(s)) }
		})
		return { cache, stop, link, states, data: () => states.filter(s => s.status === "success").map(s => s.data) }
	}

	it("a change of a path that covers what is shown fetches it again; another path does not", async () => {
		const f = follow("/api/lookups/providers/data-weather", [["owm (not set up)"], ["owm"]])
		await settle()
		expect(f.data()).toEqual([["owm (not set up)"]])
		f.link.send(changed("/api/settings/theme"))
		await settle()
		expect(fetched).toHaveBeenCalledTimes(1)
		f.link.send(changed("/api/datasources/openweathermap-api", "/api/lookups/providers/data-weather"))
		await settle()
		expect(f.data()).toEqual([["owm (not set up)"], ["owm"]])
		expect(fetched).toHaveBeenCalledTimes(2)
	})

	it("the history the link opens with is fetched again once for the whole burst: a change in it may be newer than the answer", async () => {
		vi.useFakeTimers()
		try {
			const f = follow("/api/settings/theme", [1, 2, 3])
			await vi.advanceTimersByTimeAsync(0)
			f.link.send(changed("/api/settings/theme"), true)
			f.link.send(changed("/api/settings"), true)
			f.link.send({ source: "telemetry", kind: "gap", missed: 1 }, true)
			await vi.advanceTimersByTimeAsync(REPLAY_SETTLE_MS - 1)
			expect(fetched).toHaveBeenCalledTimes(1)
			await vi.advanceTimersByTimeAsync(1)
			expect(fetched).toHaveBeenCalledTimes(2)
			// a replayed change of something else, or a replayed gap, fetches nothing
			f.link.send(changed("/api/plugins"), true)
			f.link.send({ source: "telemetry", kind: "gap", missed: 1 }, true)
			await vi.advanceTimersByTimeAsync(REPLAY_SETTLE_MS)
			expect(fetched).toHaveBeenCalledTimes(2)
		}
		finally {
			vi.useRealTimers()
		}
	})
	it("what this page changed is stale at once", async () => {
		const f = follow("/api/schedule/playlist/list", [1, 2])
		await settle()
		await changedHere(f.cache, "/api/schedule")
		await settle()
		expect(f.data()).toEqual([1, 2])
	})

	it("a fetch again that fails is the entry's to show, never an unhandled rejection", async () => {
		const f = follow("/api/plugins/list", [["a"]])
		await settle()
		fetched.mockRejectedValueOnce(new Error("down"))
		await expect(invalidatePaths(f.cache, ["/api/plugins"])).resolves.toBeUndefined()
		expect(f.states.at(-1)?.error?.message).toBe("down")
	})

	it("a gap, the link coming back and `/api` are everything", async () => {
		const f = follow("/api/schedule/playlist/list", [1, 2, 3, 4])
		await settle()
		f.link.send({ source: "telemetry", kind: "gap", missed: 4 })
		await settle()
		f.link.resume()
		await settle()
		f.link.send({ seq: 9, source: "application", kind: "restore", values: { changed: [EVERYTHING] } })
		await settle()
		expect(f.data()).toEqual([1, 2, 3, 4])
	})

	it("what nobody shows any more is not fetched when it changes", async () => {
		const f = follow("/api/settings/theme", [1, 2])
		await settle()
		f.stop()
		f.link.send(changed("/api/settings/theme"))
		await settle()
		expect(fetched).toHaveBeenCalledTimes(1)
		// it is fetched again when it is next used, since it is stale
		expect(await readResource(f.cache, "/api/settings/theme")).toBe(2)
	})

	it("a failure is the field's to show; the next change fetches it again", async () => {
		fetched.mockRejectedValueOnce(new Error("down"))
		const f = follow("/api/datasources/rss/lookups/feed", [["a"]])
		await settle()
		expect(f.states.map(s => s.status)).toEqual(["error"])
		expect(f.states[0]!.error?.message).toBe("down")
		f.link.send(changed("/api/datasources/rss"))
		await settle()
		expect(f.data()).toEqual([["a"]])
	})
})

describe("reading", () => {
	it("many readers of one address ask once, and a fresh answer is not asked again", async () => {
		fetched.mockResolvedValue(["x"])
		const cache = inApp(() => useQueryCache())
		const answers = await Promise.all([readResource(cache, "/api/a?q=1"), readResource(cache, "/api/a?q=1")])
		expect(answers).toEqual([["x"], ["x"]])
		expect(await readResource(cache, "/api/a?q=1")).toEqual(["x"])
		expect(fetched).toHaveBeenCalledTimes(1)
		expect(fetched).toHaveBeenCalledWith("/api/a?q=1")
		// another query is another question
		await readResource(cache, "/api/a?q=2")
		expect(fetched).toHaveBeenCalledTimes(2)
	})
	it("a read whose fetch is replaced while under way (a change invalidated it) answers the fetch that replaced it", async () => {
		let release: (value: unknown) => void = () => {}
		fetched.mockImplementationOnce(() => new Promise(resolve => { release = resolve })).mockResolvedValueOnce("second")
		const cache = inApp(() => useQueryCache())
		const stop = followResource(cache, "/api/c", () => {})
		const read = readResource(cache, "/api/c")
		await settle()
		const again = invalidatePaths(cache, ["/api/c"])
		release("first")
		await again
		expect(await read).toBe("second")
		stop()
	})
	it("a failed read rejects with the call's error", async () => {
		fetched.mockRejectedValue(new Error("refused"))
		const cache = inApp(() => useQueryCache())
		await expect(readResource(cache, "/api/b")).rejects.toThrow("refused")
	})
	it("what is installed is read once for every view", async () => {
		listed.mockImplementation(async (path: string) => path === "/api/plugins/list" ? [{ id: "slide-show" }] : [])
		const { first, second } = inApp(() => ({ first: useCatalog(), second: useCatalog() }))
		await Promise.all([first.plugins.refresh(), second.plugins.refresh(), first.dataSources.refresh(), first.displays.refresh()])
		expect(second.plugins.data.value).toEqual([{ id: "slide-show" }])
		expect(listed.mock.calls.map(c => c[0]).sort()).toEqual(["/api/datasources/list", "/api/displays/list", "/api/plugins/list"])
	})
})
