import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError, apiFetch, apiJson, apiPut, joinUrl } from "./ApiClient"

const TOKEN_KEY = "eink-billboard.api-token"

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}
/** The Authorization header of the n-th fetch call, or null. */
function authorizationOf(fetchMock: ReturnType<typeof vi.fn>, call: number): string | null {
	const init = fetchMock.mock.calls[call]?.[1] as RequestInit | undefined
	return new Headers(init?.headers).get("Authorization")
}

describe("joinUrl", () => {
	it.each([
		// the production base and a schema path: must not become "//api/...", which a browser reads as a host
		["/", "/api/lookups/timezone", "/api/lookups/timezone"],
		["/", "api/lookups/timezone", "/api/lookups/timezone"],
		["http://localhost:8080/", "/api/x", "http://localhost:8080/api/x"],
		["http://localhost:8080", "/api/x", "http://localhost:8080/api/x"],
		["http://localhost:8080", "api/x", "http://localhost:8080/api/x"],
		["", "/api/x", "/api/x"],
		["http://h//", "//api/x", "http://h/api/x"],
	])("joins %j and %j as %j", (base, path, expected) => {
		expect(joinUrl(base, path)).toBe(expected)
	})
})

describe("ApiClient requests", () => {
	let fetchMock: ReturnType<typeof vi.fn>
	beforeEach(() => {
		localStorage.clear()
		fetchMock = vi.fn()
		vi.stubGlobal("fetch", fetchMock)
	})
	afterEach(() => {
		vi.unstubAllGlobals()
		vi.restoreAllMocks()
	})

	it("returns the parsed body of a successful request", async () => {
		fetchMock.mockResolvedValue(jsonResponse({ locale: "en-US" }))
		await expect(apiJson("/api/settings/system")).resolves.toEqual({ locale: "en-US" })
	})

	it("sends no Authorization header when no token is stored, and the stored token when there is one", async () => {
		fetchMock.mockImplementation(async () => jsonResponse({}))
		await apiJson("/api/a")
		expect(authorizationOf(fetchMock, 0)).toBeNull()
		localStorage.setItem(TOKEN_KEY, "abc")
		await apiJson("/api/b")
		expect(authorizationOf(fetchMock, 1)).toBe("Bearer abc")
	})

	it("turns a non-2xx response into an ApiError carrying the server's message, status and body", async () => {
		const body = { success: false, message: "Revision mismatch: the settings changed since they were loaded.", rev: "r2" }
		fetchMock.mockResolvedValue(jsonResponse(body, 409))
		const error = await apiJson("/api/settings/system").catch((e: unknown) => e)
		expect(error).toBeInstanceOf(ApiError)
		expect((error as ApiError).status).toBe(409)
		expect((error as ApiError).message).toBe(body.message)
		expect((error as ApiError).body).toEqual(body)
	})

	it("falls back to the status line when the error body is not JSON", async () => {
		fetchMock.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" }))
		const error = await apiJson("/api/x").catch((e: unknown) => e)
		expect(error).toBeInstanceOf(ApiError)
		expect((error as ApiError).status).toBe(502)
		expect((error as ApiError).message).toBe("Error 502: Bad Gateway")
	})

	it("apiPut sends the document as a JSON PUT", async () => {
		fetchMock.mockResolvedValue(jsonResponse({ success: true, rev: "r3" }))
		const result = await apiPut("/api/settings/system", { locale: "fr-FR", _rev: "r2" })
		expect(result).toEqual({ success: true, rev: "r3" })
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
		expect(url).toBe("/api/settings/system")
		expect(init.method).toBe("PUT")
		expect(new Headers(init.headers).get("Content-Type")).toBe("application/json")
		expect(JSON.parse(init.body as string)).toEqual({ locale: "fr-FR", _rev: "r2" })
	})

	describe("when the server answers 401", () => {
		it("asks for the token, retries with it, and remembers it", async () => {
			fetchMock
				.mockResolvedValueOnce(jsonResponse({ success: false, message: "Missing or invalid API token." }, 401))
				.mockResolvedValueOnce(jsonResponse({ ok: true }))
			const prompt = vi.spyOn(window, "prompt").mockReturnValue("s3cret")
			await expect(apiJson("/api/settings/system")).resolves.toEqual({ ok: true })
			expect(prompt).toHaveBeenCalledTimes(1)
			expect(fetchMock).toHaveBeenCalledTimes(2)
			expect(authorizationOf(fetchMock, 0)).toBeNull()
			expect(authorizationOf(fetchMock, 1)).toBe("Bearer s3cret")
			expect(localStorage.getItem(TOKEN_KEY)).toBe("s3cret")
		})

		it("gives up with the server's message when the prompt is cancelled", async () => {
			fetchMock.mockResolvedValue(jsonResponse({ success: false, message: "Missing or invalid API token." }, 401))
			vi.spyOn(window, "prompt").mockReturnValue(null)
			const error = await apiJson("/api/x").catch((e: unknown) => e)
			expect(error).toBeInstanceOf(ApiError)
			expect((error as ApiError).status).toBe(401)
			expect((error as ApiError).message).toBe("Missing or invalid API token.")
			expect(fetchMock).toHaveBeenCalledTimes(1)
			expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
		})

		it("forgets a wrong token instead of storing it", async () => {
			fetchMock.mockImplementation(async () => jsonResponse({ success: false, message: "Missing or invalid API token." }, 401))
			vi.spyOn(window, "prompt").mockReturnValue("wrong")
			localStorage.setItem(TOKEN_KEY, "stale")
			await expect(apiJson("/api/x")).rejects.toMatchObject({ status: 401 })
			expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
			// the stale stored token, then the one just typed
			expect(authorizationOf(fetchMock, 0)).toBe("Bearer stale")
			expect(authorizationOf(fetchMock, 1)).toBe("Bearer wrong")
		})

		it("apiFetch hands back the response of a successful retry untouched", async () => {
			fetchMock
				.mockResolvedValueOnce(new Response("", { status: 401 }))
				.mockResolvedValueOnce(new Response("plain", { status: 200 }))
			vi.spyOn(window, "prompt").mockReturnValue("t")
			const rx = await apiFetch("/api/x")
			expect(rx.status).toBe(200)
			expect(await rx.text()).toBe("plain")
		})
	})
})
