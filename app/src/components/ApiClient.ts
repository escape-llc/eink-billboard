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

import { ref } from "vue"
import { promptForAuth, type AccessInfo, type AuthMode, type SendResult, type Values } from "./AuthPrompt"

/**
 * Counts the sign-ins of this page. What the page shows was loaded before the sign-in (or not at all), the storage may have changed since (edited by
 * hand, another browser) and the device may run a newer build, so `App.vue` reloads the whole page when it moves (see `SignedIn.ts`).
 * It moves once every request that waited for the sign-in has been answered: a save that asked for it is done before the page goes.
 */
export const signInCount = ref(0)

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

const ACCESS_URL = joinUrl(import.meta.env.VITE_API_URL ?? "/", "api/access")

/** Send what the sign-in dialog collected; the server's own words come back when it is refused. */
async function sendCredentials(mode: AuthMode, values: Values): Promise<SendResult> {
	const json = { "Content-Type": "application/json" }
	const rx = mode === "setup"
		? await fetch(joinUrl(ACCESS_URL, "setup"), { method: "POST", credentials: "include", headers: json, body: JSON.stringify({ code: values.code, password: values.secret }) })
		: mode === "password"
			? await fetch(SESSION_URL, { method: "POST", credentials: "include", headers: json, body: JSON.stringify({ password: values.secret }) })
			: await fetch(SESSION_URL, { method: "POST", credentials: "include", headers: { Authorization: `Bearer ${values.secret}` } })
	if(rx.ok) {
		return { ok: true }
	}
	return { ok: false, message: (await toApiError(rx)).message }
}

/** Ask what the device needs (a setup code and a new password, its password, or an API token) in a dialog and start a session with it. False when the dialog is closed. */
async function signIn(): Promise<boolean> {
	let info: AccessInfo | null = null
	try {
		const rx = await fetch(ACCESS_URL, { credentials: "include" })
		if(rx.ok) {
			info = await rx.json()
		}
	}
	catch {
		// the dialog asks for the token, as it always did
	}
	return promptForAuth(info, sendCredentials)
}

// A page loads several things at once, in waves, so many requests can get a 401. Only the first asks;
// the others wait for that sign-in. A request that was sent before a sign-in finished and answered after it
// (the epoch changed) is simply retried.
let signingIn: Promise<boolean> | null = null
let epoch = 0
// The prompt was cancelled or the server refused the token: do not keep asking while this page is open.
// The requests fail with the server's message, and reloading the page asks again.
let declined = false
// the requests that waited for a sign-in and have not been answered again yet; the last one moves `signInCount`
let waiting = 0
let signedIn = false

function retried(): void {
	if(--waiting === 0 && signedIn) {
		signedIn = false
		signInCount.value++
	}
}

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
			signedIn = true
		}
		else {
			declined = true
		}
		return ok
	}).finally(() => { signingIn = null })
	waiting++
	try {
		if(!await signingIn) {
			throw await toApiError(rx)
		}
		rx = await send()
		if(rx.status === 401) {
			throw await toApiError(rx)
		}
		return rx
	}
	finally {
		retried()
	}
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

function apiSend<T>(method: string, url: string, data?: unknown): Promise<T> {
	return apiJson<T>(url, data === undefined
		? { method }
		: { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
}

export function apiPost<T = any>(url: string, data: unknown): Promise<T> {
	return apiSend<T>("POST", url, data)
}

export function apiPatch<T = any>(url: string, data: unknown): Promise<T> {
	return apiSend<T>("PATCH", url, data)
}

export function apiDelete<T = any>(url: string): Promise<T> {
	return apiSend<T>("DELETE", url)
}

/** End the session on the server and drop the cookie. */
export async function signOut(): Promise<void> {
	await fetch(SESSION_URL, { method: "DELETE", credentials: "include" })
}
