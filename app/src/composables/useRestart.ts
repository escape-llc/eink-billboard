/**
 * Restarting the app from the page (#839). The server says whether something starts it again (`available`) and what is waiting for a restart
 * (`waiting`: display settings it reads once, when it starts); the cache refreshes the answer when the display settings are saved (`changed_paths`).
 *
 * A restart is one state for the whole page, because the app is gone for a while and nothing the page asks can be answered: `restarting` shows the
 * overlay, which polls the app until it answers again (after it was seen to be gone), then loads the page anew (the app may be a newer build).
 */
import { useQuery } from "@pinia/colada"
import { computed, ref } from "vue"
import { keyOf } from "../api/resources"
import { api } from "../api/client"

const ADDRESS = "/api/system/restart"
/** How often the app is asked while it restarts, and how long before the page gives up and says so. */
export const POLL_MS = 1000
export const GIVE_UP_MS = 120_000

export const restarting = ref(false)
export const restartFailed = ref("")

export interface RestartDeps {
	ask?: () => Promise<unknown>
	reload?: () => void
	sleep?: (ms: number) => Promise<void>
	now?: () => number
}

/** Ask for the restart and wait for the app: it must be seen to stop answering, then to answer again. Resolves when the page is about to load again, or when it gave up. */
export async function restartApp(deps: RestartDeps = {}): Promise<void> {
	const ask = deps.ask ?? (() => api.get("/api/status"))
	const reload = deps.reload ?? (() => window.location.reload())
	const sleep = deps.sleep ?? ((ms: number) => new Promise<void>(done => setTimeout(done, ms)))
	const now = deps.now ?? Date.now
	restartFailed.value = ""
	try {
		await api.post(ADDRESS, {}, undefined)
	}
	catch (e) {
		// refused (not claimed, nothing would start the app again): it is still running, and the server's words say why
		restartFailed.value = e instanceof Error ? e.message : "The restart could not be started."
		return
	}
	restarting.value = true
	const started = now()
	let gone = false
	while (now() - started < GIVE_UP_MS) {
		await sleep(POLL_MS)
		try {
			await ask()
			if (gone) {
				reload()
				return
			}
		}
		catch {
			gone = true
		}
	}
	restarting.value = false
	restartFailed.value = "The app did not come back. Check the device."
}

export function useRestart() {
	const state = useQuery({ key: keyOf(ADDRESS), query: () => api.get(ADDRESS) })
	const waiting = computed(() => state.data.value?.waiting ?? [])
	const available = computed(() => state.data.value?.available ?? false)
	return { waiting, available, restart: () => restartApp() }
}
