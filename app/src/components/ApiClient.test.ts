import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { joinUrl, type ApiError as ApiFailure } from "./ApiClient"

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}
const REFUSED = { success: false, message: "Missing or invalid API token." }

/** A server that wants a token: `POST /api/session` with the right Bearer token signs the "browser" in, and only then do other requests work. */
function fakeServer(validToken: string) {
	const state = { signedIn: false, signIns: 0, calls: [] as { url: string, init?: RequestInit }[] }
	const handle = async (url: string, init?: RequestInit) => {
		state.calls.push({ url, init })
		if(url.endsWith("/api/session")) {
			const sent = new Headers(init?.headers).get("Authorization")
			if(init?.method === "POST" && sent === `Bearer ${validToken}`) {
				state.signedIn = true
				state.signIns++
				return jsonResponse({ success: true })
			}
			return jsonResponse(REFUSED, 401)
		}
		return state.signedIn ? jsonResponse({ ok: true }) : jsonResponse(REFUSED, 401)
	}
	return { state, handle }
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
	// a fresh copy of the module for every test: it remembers that a sign-in was declined
	let ApiError: typeof import("./ApiClient").ApiError
	let apiFetch: typeof import("./ApiClient").apiFetch
	let apiJson: typeof import("./ApiClient").apiJson
	let apiPut: typeof import("./ApiClient").apiPut
	let signOut: typeof import("./ApiClient").signOut
	beforeEach(async () => {
		vi.resetModules()
		;({ ApiError, apiFetch, apiJson, apiPut, signOut } = await import("./ApiClient"))
		localStorage.clear()
		sessionStorage.clear()
		fetchMock = vi.fn()
		vi.stubGlobal("fetch", fetchMock)
	})
	afterEach(() => {
		vi.unstubAllGlobals()
		vi.restoreAllMocks()
	})
	/** Nothing but the theme may live in browser storage; these flows must not write anything. */
	const expectNothingStored = () => {
		expect(localStorage.length, "localStorage").toBe(0)
		expect(sessionStorage.length, "sessionStorage").toBe(0)
	}

	it("returns the parsed body of a successful request, with the browser's cookies, and no credentials of its own", async () => {
		fetchMock.mockResolvedValue(jsonResponse({ locale: "en-US" }))
		await expect(apiJson("/api/settings/system")).resolves.toEqual({ locale: "en-US" })
		const init = fetchMock.mock.calls[0][1] as RequestInit
		expect(init.credentials).toBe("include")
		expect(new Headers(init.headers).get("Authorization")).toBeNull()
		expectNothingStored()
	})

	it("turns a non-2xx response into an ApiError carrying the server's message, status and body", async () => {
		const body = { success: false, message: "Revision mismatch: the settings changed since they were loaded.", rev: "r2" }
		fetchMock.mockResolvedValue(jsonResponse(body, 409))
		const error = await apiJson("/api/settings/system").catch((e: unknown) => e)
		expect(error).toBeInstanceOf(ApiError)
		expect((error as ApiFailure).status).toBe(409)
		expect((error as ApiFailure).message).toBe(body.message)
		expect((error as ApiFailure).body).toEqual(body)
	})

	it("falls back to the status line when the error body is not JSON", async () => {
		fetchMock.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" }))
		const error = await apiJson("/api/x").catch((e: unknown) => e)
		expect(error).toBeInstanceOf(ApiError)
		expect((error as ApiFailure).status).toBe(502)
		expect((error as ApiFailure).message).toBe("Error 502: Bad Gateway")
	})

	it("apiPut sends the document as a JSON PUT", async () => {
		fetchMock.mockResolvedValue(jsonResponse({ success: true, rev: "r3" }))
		const result = await apiPut("/api/settings/system", { locale: "fr-FR", _rev: "r2" })
		expect(result).toEqual({ success: true, rev: "r3" })
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
		expect(url).toBe("/api/settings/system")
		expect(init.method).toBe("PUT")
		expect(new Headers(init.headers).get("Content-Type")).toBe("application/json")
		expect(JSON.parse(init.body as string)).toEqual({ _rev: "r2", locale: "fr-FR" })
	})

	describe("when the server answers 401 (an API token is required)", () => {
		it("asks for the token, signs in once, and retries; nothing is stored in the browser", async () => {
			const server = fakeServer("s3cret")
			fetchMock.mockImplementation(server.handle)
			const prompt = vi.spyOn(window, "prompt").mockReturnValue("s3cret")
			await expect(apiJson("/api/settings/system")).resolves.toEqual({ ok: true })
			expect(prompt).toHaveBeenCalledTimes(1)
			expect(server.state.signIns).toBe(1)
			const signIn = server.state.calls.find(c => c.url.endsWith("/api/session"))!
			expect(signIn.init?.method).toBe("POST")
			expect(signIn.init?.credentials).toBe("include")
			expect(new Headers(signIn.init?.headers).get("Authorization")).toBe("Bearer s3cret")
			// the page's own requests never carry the token: the server's cookie does the work
			for (const call of server.state.calls.filter(c => !c.url.endsWith("/api/session"))) {
				expect(new Headers(call.init?.headers).get("Authorization"), call.url).toBeNull()
			}
			expectNothingStored()
		})

		it("does not ask again once signed in", async () => {
			const server = fakeServer("s3cret")
			fetchMock.mockImplementation(server.handle)
			const prompt = vi.spyOn(window, "prompt").mockReturnValue("s3cret")
			await apiJson("/api/a")
			await apiJson("/api/b")
			await apiJson("/api/c")
			expect(prompt).toHaveBeenCalledTimes(1)
		})

		it("asks only once when several requests fail together, and retries them all", async () => {
			const server = fakeServer("s3cret")
			fetchMock.mockImplementation(server.handle)
			const prompt = vi.spyOn(window, "prompt").mockReturnValue("s3cret")
			const results = await Promise.all(["/api/a", "/api/b", "/api/c", "/api/d"].map(u => apiJson(u)))
			expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }, { ok: true }])
			expect(prompt).toHaveBeenCalledTimes(1)
			expect(server.state.signIns).toBe(1)
			expectNothingStored()
		})

		it("gives up with the server's message when the prompt is cancelled, asking only once for requests that failed together", async () => {
			const server = fakeServer("s3cret")
			fetchMock.mockImplementation(server.handle)
			const prompt = vi.spyOn(window, "prompt").mockReturnValue(null)
			const results = await Promise.allSettled(["/api/a", "/api/b", "/api/c"].map(u => apiJson(u)))
			expect(results.map(r => r.status)).toEqual(["rejected", "rejected", "rejected"])
			for (const r of results) {
				expect((r as PromiseRejectedResult).reason).toMatchObject({ status: 401, message: "Missing or invalid API token." })
			}
			expect(prompt).toHaveBeenCalledTimes(1)
			expect(server.state.calls.some(c => c.url.endsWith("/api/session"))).toBe(false)
			expectNothingStored()
		})

		it("refuses a wrong token with the server's message and stores nothing", async () => {
			const server = fakeServer("s3cret")
			fetchMock.mockImplementation(server.handle)
			vi.spyOn(window, "prompt").mockReturnValue("wrong")
			await expect(apiJson("/api/x")).rejects.toMatchObject({ status: 401, message: "Missing or invalid API token." })
			expect(server.state.signedIn).toBe(false)
			expectNothingStored()
		})

		// a page loads in waves of requests: a cancelled prompt must not come back with every wave
		it("does not ask again, wave after wave, after a cancelled prompt", async () => {
			const server = fakeServer("s3cret")
			fetchMock.mockImplementation(server.handle)
			const prompt = vi.spyOn(window, "prompt").mockReturnValue(null)
			for (const wave of [["/api/a", "/api/b"], ["/api/c", "/api/d", "/api/e"], ["/api/f"]]) {
				const results = await Promise.allSettled(wave.map(u => apiJson(u)))
				for (const r of results) expect((r as PromiseRejectedResult).reason).toMatchObject({ status: 401, message: "Missing or invalid API token." })
			}
			expect(prompt).toHaveBeenCalledTimes(1)
		})

		it("does not ask again, wave after wave, after the server refused the token", async () => {
			const server = fakeServer("s3cret")
			fetchMock.mockImplementation(server.handle)
			const prompt = vi.spyOn(window, "prompt").mockReturnValue("wrong")
			await expect(apiJson("/api/a")).rejects.toMatchObject({ status: 401 })
			await expect(apiJson("/api/b")).rejects.toMatchObject({ status: 401 })
			expect(prompt).toHaveBeenCalledTimes(1)
			expect(server.state.signIns).toBe(0)
		})

		it("retries, without asking, a request that was answered 401 only after the sign-in finished", async () => {
			const server = fakeServer("s3cret")
			let answerLate!: (rx: Response) => void
			const late = new Promise<Response>(resolve => { answerLate = resolve })
			let first = true
			fetchMock.mockImplementation((url: string, init?: RequestInit) => {
				if(url === "/api/late" && first) {
					first = false
					return late
				}
				return server.handle(url, init)
			})
			const prompt = vi.spyOn(window, "prompt").mockReturnValue("s3cret")
			const slow = apiJson("/api/late")
			await apiJson("/api/a")
			answerLate(jsonResponse(REFUSED, 401))
			await expect(slow).resolves.toEqual({ ok: true })
			expect(prompt).toHaveBeenCalledTimes(1)
		})

		it("apiFetch hands back the response of a successful retry untouched", async () => {
			fetchMock
				.mockResolvedValueOnce(new Response("", { status: 401 }))
				.mockResolvedValueOnce(new Response("", { status: 200 }))   // the sign-in
				.mockResolvedValueOnce(new Response("plain", { status: 200 }))
			vi.spyOn(window, "prompt").mockReturnValue("t")
			const rx = await apiFetch("/api/x")
			expect(rx.status).toBe(200)
			expect(await rx.text()).toBe("plain")
		})
	})

	it("signOut asks the server to end the session", async () => {
		fetchMock.mockResolvedValue(jsonResponse({ success: true }))
		await signOut()
		const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
		expect(url.endsWith("/api/session")).toBe(true)
		expect(init.method).toBe("DELETE")
		expect(init.credentials).toBe("include")
	})
})
