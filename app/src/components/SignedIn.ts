/**
 * After a sign-in the whole page is loaded again (`App.vue`, when `signInCount` moves): what it showed was read before the sign-in (or not at all),
 * the storage may have changed since, and the device may run a newer build. A reload starts everything over (the page, the activity gutter, the
 * status button) and loads the newest build.
 *
 * The reload is marked in `history.state` (which a reload keeps, and which is not storage: the browser keeps nothing but the theme), so the
 * reloaded page can say why it reloaded.
 */
const MARK = "signedInAt"
// a mark older than this is not this reload's (the tab was reloaded by hand later)
const WINDOW_MS = 30000

type Win = Pick<Window, "history" | "location">

export function reloadAfterSignIn(win: Win = window, now: number = Date.now()): void {
	win.history.replaceState({ ...(win.history.state ?? {}), [MARK]: now }, "")
	win.location.reload()
}

/** True once, on the page a sign-in reloaded: the mark is taken off, so a later reload by hand says nothing. */
export function justSignedIn(win: Win = window, now: number = Date.now()): boolean {
	const state = (win.history.state ?? {}) as Record<string, unknown>
	const at = state[MARK]
	if (typeof at !== "number") {
		return false
	}
	const { [MARK]: _, ...rest } = state
	win.history.replaceState(rest, "")
	return now - at < WINDOW_MS
}
