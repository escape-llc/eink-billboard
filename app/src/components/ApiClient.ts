/**
 * Calls to the backend API.
 *
 * - every request carries the browser's cookies, which is how the session started by `signIn` is recognised
 * - turns every non-2xx response into an ApiError carrying the server's `message`
 *
 * The browser stores nothing for this (the theme is the only thing kept in local storage): when the server requires
 * an API token, it is sent once to start a session, which the server remembers and the browser holds only as an
 * HttpOnly cookie that scripts cannot read.
 */
export class ApiError extends Error {
	status: number
	body: any
	constructor(status: number, message: string, body: any = undefined) {
		super(message)
		this.name = "ApiError"
		this.status = status
		this.body = body
	}
}

/**
 * Join a base URL and a path with exactly one slash between them, however either is written.
 * `/` + `/api/x` must be `/api/x`, not `//api/x`, which a browser reads as a host called "api".
 */
export function joinUrl(base: string, path: string): string {
	return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`
}

const SESSION_URL = joinUrl(import.meta.env.VITE_API_URL ?? "/", "api/session")

async function toApiError(rx: Response): Promise<ApiError> {
	let body: any = undefined
	try {
		body = await rx.json()
	}
	catch {
		// not JSON
	}
	const message = (body && typeof body.message === "string" && body.message) || `Error ${rx.status}: ${rx.statusText}`
	return new ApiError(rx.status, message, body)
}

/** Ask for the token and start a session with it. False when the prompt is cancelled or the server refuses the token. */
async function signIn(): Promise<boolean> {
	// window.prompt blocks, so the other requests that failed with this one wait behind it
	const token = window.prompt("This device requires an API token:")
	if(!token) {
		return false
	}
	const rx = await fetch(SESSION_URL, {
		method: "POST",
		credentials: "include",
		headers: { Authorization: `Bearer ${token}` }
	})
	return rx.ok
}

// A page loads several things at once, in waves, so many requests can get a 401. Only the first asks;
// the others wait for that sign-in. A request that was sent before a sign-in finished and answered after it
// (the epoch changed) is simply retried.
let signingIn: Promise<boolean> | null = null
let epoch = 0
// The prompt was cancelled or the server refused the token: do not keep asking while this page is open.
// The requests fail with the server's message, and reloading the page asks again.
let declined = false

export async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
	const send = () => fetch(url, { credentials: "include", ...init })
	const sentIn = epoch
	let rx = await send()
	if(rx.status !== 401) {
		return rx
	}
	if(epoch !== sentIn) {
		rx = await send()
		if(rx.status !== 401) {
			return rx
		}
	}
	if(declined) {
		throw await toApiError(rx)
	}
	signingIn ??= signIn().then(ok => {
		if(ok) {
			epoch++
		}
		else {
			declined = true
		}
		return ok
	}).finally(() => { signingIn = null })
	if(!await signingIn) {
		throw await toApiError(rx)
	}
	rx = await send()
	if(rx.status === 401) {
		throw await toApiError(rx)
	}
	return rx
}

/** GET (or the given method) and parse the JSON body; rejects with ApiError when the status is not 2xx. */
export async function apiJson<T = any>(url: string, init?: RequestInit): Promise<T> {
	const rx = await apiFetch(url, init)
	if(!rx.ok) {
		throw await toApiError(rx)
	}
	return await rx.json() as T
}

export function apiPut<T = any>(url: string, data: unknown): Promise<T> {
	return apiJson<T>(url, {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(data)
	})
}

/** End the session on the server and drop the cookie. */
export async function signOut(): Promise<void> {
	await fetch(SESSION_URL, { method: "DELETE", credentials: "include" })
}
