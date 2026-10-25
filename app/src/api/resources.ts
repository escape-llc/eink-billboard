/**
 * Server data that refreshes itself (#549): the answers of the API's GET routes, kept once for every view in a cache whose key is the route's path
 * (Pinia Colada). The server says what changed: its `config-changed` and `restore` events carry `changed`, the paths of the routes whose answers may
 * differ now (python/model/changed_paths.py), worked out from the stored file, so a save from another tab, the device's command line, a hand edit or a
 * restore reaches every open page. A path covers every key it starts, by whole segments (`/api/schedule` is every schedule route; `/api` all of them):
 * what is shown is fetched again, the rest when it is next used. A page that missed events (a `gap`, a reconnect, the device started again) cannot know
 * what changed, so everything is stale.
 *
 * Edit state is never the cache's: an editor copies what it loads (#550's machine owns the draft), so a change from elsewhere never overwrites what a
 * person is typing. A 409 is not resolved here either: taking the other version is a load, which the cache answers.
 */
import { PiniaColada, useQuery, useQueryCache, type UseQueryEntry } from "@pinia/colada"
import { effectScope, watch, type App } from "vue"
import { apiJson, joinUrl } from "../components/ApiClient"
import type { TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"
import type { Descriptor } from "../components/FormDefs"
import type { PluginDef } from "../components/ScheduleDefs"
import { api } from "./client"

/** Every route: what a page asks for again when it cannot know what changed. */
export const EVERYTHING = "/api"
const BASE = import.meta.env.VITE_API_URL ?? "/"

/**
 * How long an answer is used without asking: the server's events say when it changed, so this bounds only what a page misses while its link is down.
 * Focus asks nothing (the events do it); a browser that comes back online asks for what is shown.
 */
export const RESOURCE_OPTIONS = { staleTime: 30_000, gcTime: 300_000, refetchOnWindowFocus: false, refetchOnReconnect: true } as const

/** Install the cache (main.ts, and a test's app). */
export function installResources(app: App): void {
	app.use(PiniaColada, { queryOptions: RESOURCE_OPTIONS })
}

/** A path's cache key: its segments, and the query as one last segment (`/api/x/lookups/q?model=a` is `["api", "x", "lookups", "q", "?model=a"]`). */
export function keyOf(address: string): string[] {
	const at = address.indexOf("?")
	const path = at < 0 ? address : address.slice(0, at)
	const segments = path.split("/").filter(s => s !== "")
	return at < 0 || at === address.length - 1 ? segments : [...segments, address.slice(at)]
}

/** Whether a path covers a key: it is the key's start, by whole segments. */
export function covers(path: string, key: readonly unknown[]): boolean {
	const prefix = keyOf(path)
	return prefix.length <= key.length && prefix.every((s, i) => key[i] === s)
}

type QueryCache = ReturnType<typeof useQueryCache>

/** Mark what these paths cover as stale: what is shown is fetched again at once. A fetch that fails is in its entry's state, for whatever shows it. */
export function invalidatePaths(cache: QueryCache, paths: readonly string[]): Promise<unknown> {
	// a path another one covers adds nothing (and would fetch what it covers a second time)
	const widest = [...new Set(paths)].filter((p, _, all) => !all.some(other => other !== p && covers(other, keyOf(p))))
	const asked = widest.includes(EVERYTHING) ? cache.invalidateQueries() : Promise.all(widest.map(p => cache.invalidateQueries({ key: keyOf(p) })))
	return asked.catch(() => undefined)
}

/** The paths an event says changed (only strings that are API paths: anything else in it is ignored). */
export function changedPaths(e: TelemetryEvent): string[] {
	const changed = e.values?.changed
	return Array.isArray(changed) ? changed.filter((p): p is string => typeof p === "string" && (p === EVERYTHING || p.startsWith(`${EVERYTHING}/`))) : []
}

/** How long after the last replayed event the history's changes are fetched again: the hub sends its history in one burst after `hello`. */
export const REPLAY_SETTLE_MS = 200

/**
 * Follow the link for the cache: every event that names changed paths invalidates them; a `gap` (events were dropped) and the link coming up again
 * after it was down (or the device started again: a new `run`) invalidate everything. The history the hub sends when the link opens may hold a change
 * made after the page read an answer (between its load and the link's opening), so the paths it names are invalidated too, once for the whole burst
 * (an older change costs one fetch of what is fresh already); a `gap` in it was before this page. Returns the function that stops following.
 */
export function syncWithLink(cache: QueryCache, link: TelemetryLink): () => void {
	const replayed = new Set<string>()
	let timer: ReturnType<typeof setTimeout> | undefined
	const flush = () => {
		timer = undefined
		const paths = [...replayed]
		replayed.clear()
		if (paths.length > 0) void invalidatePaths(cache, paths.includes(EVERYTHING) ? [EVERYTHING] : paths)
	}
	const unlisten = link.listen({
		event: (e, fromHistory) => {
			if (fromHistory) {
				if (e.kind === "gap") return
				for (const path of changedPaths(e)) replayed.add(path)
				if (timer) clearTimeout(timer)
				timer = setTimeout(flush, REPLAY_SETTLE_MS)
				return
			}
			if (e.kind === "gap") { void invalidatePaths(cache, [EVERYTHING]); return }
			const paths = changedPaths(e)
			if (paths.length > 0) void invalidatePaths(cache, paths)
		},
		resumed: () => { void invalidatePaths(cache, [EVERYTHING]) },
	})
	return () => {
		if (timer) clearTimeout(timer)
		unlisten()
	}
}

/** What this page changed (a save, a delete): marked stale at once, so nothing waits for the server's event to come back. */
export const changedHere = (cache: QueryCache, ...paths: string[]) => invalidatePaths(cache, paths)

/** What an answer is: the data, or the error it failed with. */
export type ResourceState<T> = { data: T | undefined, error: Error | null, status: "pending" | "success" | "error" }

/**
 * Follow an address outside a component's setup (a form's lookups, which it makes when its schema arrives): `cache` is the one the component took in
 * its setup. The entry counts as shown until the returned function is called, so a change fetches it again, and `onState` hears every answer
 * (the first at once when the cache already has it). `query` asks for it (a typed call of the same address); by default the address is fetched.
 */
export function followResource<T>(cache: QueryCache, address: string, onState: (state: ResourceState<T>) => void, query?: () => Promise<T>): () => void {
	const scope = effectScope(true)
	const entry = cache.ensure<T>({ key: keyOf(address), query: query ?? (() => apiJson<T>(joinUrl(BASE, address))) }) as UseQueryEntry<T>
	cache.track(entry, scope)
	scope.run(() => watch(() => entry.state.value, state => onState(state as ResourceState<T>), { immediate: entry.state.value.status !== "pending" }))
	void cache.refresh(entry).catch(() => {})
	return () => {
		cache.untrack(entry, scope)
		scope.stop()
	}
}

/**
 * Read an address once through the cache (asked once for any number of callers, and answered from it while fresh); rejects with the call's error.
 * `query` asks for it (a typed call of the same address); by default the address is fetched.
 */
export async function readResource<T>(cache: QueryCache, address: string, query?: () => Promise<T>): Promise<T> {
	const entry = cache.ensure<T>({ key: keyOf(address), query: query ?? (() => apiJson<T>(joinUrl(BASE, address))) }) as UseQueryEntry<T>
	// a fetch can be replaced while it is under way (a change invalidated it): the answer is the one that replaced it
	for (let tries = 0; ; tries++) {
		const state = await cache.refresh(entry)
		if (state.status === "error") throw state.error
		if (state.status === "success" && state.data !== undefined) return state.data as T
		if (tries >= 3) throw new Error("The answer was replaced while it was asked for.")
	}
}

/** Wait for a query (answered from the cache while fresh, else asked once); `failed` hears of an answer that could not be had. */
export async function settled(query: { refresh: () => Promise<{ error: Error | null }> }, failed: (error: Error) => void): Promise<void> {
	const state = await query.refresh()
	if (state.error) failed(state.error)
}

/**
 * What is installed (a component's setup or a composable it calls): the plugins, the data sources and the displays, read once for every view and form.
 * A descriptor's keys are its own (open in the API): the web app reads them as PluginDef and Descriptor, which DescriptorSchema.test holds to every descriptor.
 */
export function useCatalog() {
	return {
		plugins: useQuery({ key: keyOf("/api/plugins/list"), query: () => api.get("/api/plugins/list") as Promise<unknown> as Promise<PluginDef[]> }),
		dataSources: useQuery({ key: keyOf("/api/datasources/list"), query: () => api.get("/api/datasources/list") as Promise<unknown> as Promise<Descriptor[]> }),
		displays: useQuery({ key: keyOf("/api/displays/list"), query: () => api.get("/api/displays/list") as Promise<unknown> as Promise<Descriptor[]> }),
	}
}
