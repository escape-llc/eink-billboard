/**
 * A tab opened before an update runs the old build. Its pages' code is in chunks named by a hash of the build, which the update replaced, so the
 * next page it opens fails to load ("Failed to fetch dynamically imported module"; the server answers 404). The page is then reloaded, once, at the
 * address it was going to: the reload loads the new build (index.html is never kept without asking).
 *
 * The reload is marked in `history.state`, which a reload keeps and which is not storage (the browser keeps nothing but the theme): a second failure
 * soon after is a build that is broken itself, and is left to show its error instead of reloading for ever.
 */
import type { Router } from "vue-router"

const MARK = "reloadedForNewBuild"
const WINDOW_MS = 20000

/** The error of a module (a page's chunk) that could not be loaded, as Chromium, Firefox and Safari word it. */
export function isStaleChunk(error: unknown): boolean {
	const text = String((error as { message?: unknown } | null)?.message ?? error)
	return /dynamically imported module|importing a module script failed|unable to preload css/i.test(text)
}

type Win = Pick<Window, "history" | "location">

/** Reload the page at `hash` (the route it was going to, `#/settings`), unless it was just reloaded for this. True when it reloads. */
export function reloadOnce(hash: string|undefined, win: Win = window, now: number = Date.now()): boolean {
	const state = (win.history.state ?? {}) as Record<string, unknown>
	const last = typeof state[MARK] === "number" ? state[MARK] as number : 0
	if (now - last < WINDOW_MS) {
		return false
	}
	// the same history entry, at the target address: the router does not navigate on replaceState, and the reload keeps the state
	win.history.replaceState({ ...state, [MARK]: now }, "", hash ? `${win.location.pathname}${win.location.search}${hash}` : undefined)
	win.location.reload()
	return true
}

/**
 * Reload once when a page of the old build cannot be loaded: a route's failed import, at the route it was going to. (Not on Vite's own
 * `vite:preloadError`, which comes first and does not know the route: a reload there landed on the page the tab was leaving.)
 */
export function installStaleBuildReload(router: Router, win: Win = window): void {
	router.onError((error, to) => {
		if (isStaleChunk(error)) {
			reloadOnce(`#${to.fullPath}`, win)
		}
	})
}
