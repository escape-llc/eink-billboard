/**
 * Calls to the backend API.
 *
 * - sends the API token (when the server requires one) as a Bearer token; the user is asked for it on the first 401
 * - turns every non-2xx response into an ApiError carrying the server's `message`
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

const TOKEN_KEY = "eink-billboard.api-token"

function readToken(): string | null {
	try {
		return localStorage.getItem(TOKEN_KEY)
	}
	catch {
		return null
	}
}
function writeToken(token: string | null) {
	try {
		if(token) {
			localStorage.setItem(TOKEN_KEY, token)
		}
		else {
			localStorage.removeItem(TOKEN_KEY)
		}
	}
	catch {
		// storage is not available (private window, etc.); the token is asked for again next time
	}
}

function withToken(init: RequestInit | undefined, token: string | null): RequestInit {
	if(!token) return init ?? {}
	const headers = new Headers(init?.headers)
	headers.set("Authorization", `Bearer ${token}`)
	return { ...init, headers }
}

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

export async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
	let rx = await fetch(url, withToken(init, readToken()))
	if(rx.status === 401) {
		const entered = window.prompt("This device requires an API token:")
		if(!entered) {
			throw await toApiError(rx)
		}
		rx = await fetch(url, withToken(init, entered))
		if(rx.status === 401) {
			writeToken(null)
			throw await toApiError(rx)
		}
		writeToken(entered)
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
