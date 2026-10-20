/**
 * Play, stop and next for the playlist (python/web/routers/transport.py). The server accepts a command and the layer does it on its own thread, so the
 * button follows what the layer reports: its `transport` events (`state` `halted` after a stop, `playing` after a play or a next from a stop), and
 * `GET /api/transport` for the state when the page opens or the link comes back. A click shows its result at once; the next event corrects it.
 */
import { reactive } from "vue"
import { apiJson, apiPost, joinUrl } from "./ApiClient"
import type { TelemetryEvent } from "./TelemetryLink"

export type TransportCommand = "play" | "stop" | "next"

/** What the newest `transport` event says: stopped, or playing. undefined when no event is about it. Events are newest first, as the link keeps them. */
export function stoppedBy(events: readonly TelemetryEvent[]): boolean | undefined {
	const latest = events.find(e => e.kind === "transport")
	if (!latest) return undefined
	return latest.values?.state === "halted"
}

export class Transport {
	readonly state = reactive({ stopped: false, busy: false })
	private base: string

	constructor(base: string) {
		this.base = base
	}

	private url(): string {
		return joinUrl(this.base || "/", "api/transport")
	}

	/** Ask the device whether playback is stopped. A failure leaves what is known (the link shows the device is not answering). */
	async load(): Promise<void> {
		try {
			const answer = await apiJson<{ stopped: boolean }>(this.url())
			this.state.stopped = answer.stopped === true
		} catch { /* the System page's link status says so */ }
	}

	/** Follow the link's events. */
	follow(events: readonly TelemetryEvent[]): void {
		const stopped = stoppedBy(events)
		if (stopped !== undefined) this.state.stopped = stopped
	}

	/** Send a command; throws what ApiClient throws (the server's own message). One at a time: a second click while one is on its way is dropped. */
	async send(command: TransportCommand): Promise<void> {
		if (this.state.busy) return
		this.state.busy = true
		try {
			await apiPost(this.url(), { command })
			if (command === "stop") this.state.stopped = true
			else this.state.stopped = false
		} finally {
			this.state.busy = false
		}
	}
}

let shared: Transport | null = null
/** The page's one transport (the System page's buttons). */
export function useTransport(base: string = import.meta.env.VITE_API_URL ?? "/"): Transport {
	shared ??= new Transport(base)
	return shared
}
