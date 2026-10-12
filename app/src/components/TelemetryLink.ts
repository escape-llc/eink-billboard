/**
 * The telemetry link: a WebSocket that follows what the device does (python/web/routers/telemetry.py), for the gutter.
 * This is the one place the app opens it, as ApiClient is the one place for HTTP: the link reconnects on its own (1 s doubling to 30 s),
 * resumes after the last event it has (`since`), and when the server asks for a sign-in (close code 4401) it signs in through ApiClient.
 * Nothing is stored in the browser: the events live as long as the page.
 */
import { reactive } from "vue"
import { apiJson, joinUrl } from "./ApiClient"

export type TelemetryEvent = {
	seq?: number
	/** with the device's offset */
	ts?: string
	source: string
	kind: string
	message?: string
	/** the exception in full: sent only when this page is opened on the device itself */
	detail?: string
	values?: Record<string, any>
	missed?: number
}
export type LinkStatus = "connecting" | "live" | "offline" | "signed-out"

/** What the link needs of a WebSocket (a fake in the tests). */
export interface SocketLike {
	onopen: ((ev: any) => void) | null
	onmessage: ((ev: { data: any }) => void) | null
	onclose: ((ev: { code: number }) => void) | null
	close(): void
}
export type SocketFactory = (url: string) => SocketLike

export const MAX_EVENTS = 200
const FIRST_RETRY_MS = 1000
const LAST_RETRY_MS = 30000
const SIGN_IN = 4401

/** The socket's address: the API's, with `ws:` or `wss:` for `http:` or `https:`. */
export function socketUrl(base: string, since: number, page: { href: string } = window.location): string {
	const url = new URL(joinUrl(base || "/", "api/telemetry/ws"), page.href)
	url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
	url.searchParams.set("since", String(since))
	return url.toString()
}

/** The time of day of an event as the device saw it: read from the string, whose offset is the device's (not converted to the browser's zone). */
export function clockOf(ts: string | undefined): string {
	const found = /T(\d{2}):(\d{2}):(\d{2})/.exec(ts ?? "")
	return found ? `${found[1]}:${found[2]}:${found[3]}` : ""
}

/** Who made an image (python/task/source_router.py): a playlist track or a timer task. */
export type Origin = { kind: string; title: string; plugin: string; name?: string }
export type OriginLine = { layer: string; text: string; kind: string }

/** The words for an origin: `Main › Morning Joe (Slide Show)` for a track of the playlist `Main`, `Clock (Overlay)` for a timer task. */
export function originText(o: Origin): string {
	return `${o.kind === "playlist" && o.name ? `${o.name} › ` : ""}${o.title} (${o.plugin})`
}

/** Which track or task made each layer of what the panel shows (a `shown` event's layers), back to front; a layer nobody marked has no line. */
export function originsOf(e: TelemetryEvent | null | undefined): OriginLine[] {
	const lines: OriginLine[] = []
	for (const layer of (e?.values?.layers ?? []) as any[]) {
		if (layer?.origin) lines.push({ layer: String(layer.layer), text: originText(layer.origin), kind: String(layer.origin.kind) })
		for (const o of (layer?.origins ?? []) as Origin[]) lines.push({ layer: "overlay", text: originText(o), kind: String(o.kind) })
	}
	return lines
}

/** An event that says something went wrong. */
export function isProblem(e: TelemetryEvent): boolean {
	return ["track-failed", "task-failed", "error", "faulted", "configure-failed", "gap"].includes(e.kind)
}

export class TelemetryLink {
	readonly state = reactive({ status: "offline" as LinkStatus, events: [] as TelemetryEvent[], current: null as TelemetryEvent | null })
	private socket: SocketLike | null = null
	private last = 0
	private retry = FIRST_RETRY_MS
	private timer: ReturnType<typeof setTimeout> | undefined
	private running = false

	private base: string
	private open: SocketFactory
	private max: number

	constructor(base: string, open: SocketFactory = (url) => new WebSocket(url) as unknown as SocketLike, max = MAX_EVENTS) {
		this.base = base
		this.open = open
		this.max = max
	}

	start(): void {
		if (this.running) return
		this.running = true
		// what the panel shows now, even when it was drawn before the kept history
		apiJson<TelemetryEvent | null>(joinUrl(this.base || "/", "api/display/current")).then(e => { if (e && !this.state.current) this.state.current = e }).catch(() => {})
		this.connect()
	}

	stop(): void {
		this.running = false
		if (this.timer) clearTimeout(this.timer)
		this.timer = undefined
		const socket = this.socket
		this.socket = null
		socket?.close()
		this.state.status = "offline"
	}

	private connect(): void {
		if (!this.running) return
		this.state.status = "connecting"
		const socket = this.open(socketUrl(this.base, this.last))
		this.socket = socket
		socket.onopen = () => {
			if (socket !== this.socket) return
			this.state.status = "live"
			this.retry = FIRST_RETRY_MS
		}
		socket.onmessage = (ev) => {
			if (socket !== this.socket) return
			try { this.receive(JSON.parse(String(ev.data))) } catch { /* not an event */ }
		}
		socket.onclose = (ev) => {
			if (socket !== this.socket) return
			this.socket = null
			if (!this.running) return
			if (ev.code === SIGN_IN) {
				this.state.status = "signed-out"
				// an HTTP call through ApiClient asks for the token; once signed in, the session cookie lets the socket in
				apiJson(joinUrl(this.base || "/", `api/telemetry?since=${this.last}`)).then(() => this.later(0)).catch(() => {})
				return
			}
			this.state.status = "offline"
			this.later(this.retry)
			this.retry = Math.min(this.retry * 2, LAST_RETRY_MS)
		}
	}

	private later(ms: number): void {
		if (this.timer) clearTimeout(this.timer)
		this.timer = setTimeout(() => { this.timer = undefined; this.connect() }, ms)
	}

	/** One event from the link: newest first, at most `max`; `shown` is also what the panel shows now. */
	receive(e: TelemetryEvent): void {
		if (!e || typeof e.kind !== "string" || e.kind === "ping") return
		if (typeof e.seq === "number") {
			if (e.seq <= this.last) return
			this.last = e.seq
		}
		this.state.events.unshift(e)
		if (this.state.events.length > this.max) this.state.events.length = this.max
		if (e.kind === "shown") this.state.current = e
	}

	/** The address of a shown image (by its digest), thumbnail or full size. */
	imageUrl(digest: string, size: "thumb" | "full" = "thumb"): string {
		return joinUrl(this.base || "/", `api/display/images/${encodeURIComponent(digest)}?size=${size}`)
	}
}

let shared: TelemetryLink | null = null
/** The page's one link (the gutter and anything else that wants to follow the device share it). */
export function useTelemetry(base: string = import.meta.env.VITE_API_URL ?? "/"): TelemetryLink {
	shared ??= new TelemetryLink(base)
	return shared
}
