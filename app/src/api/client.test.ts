import { describe, expect, it } from "vitest"
import { api, apiUrl } from "./client"

describe("apiUrl", () => {
	it("fills the path's parameters, each encoded", () => {
		expect(apiUrl("/api/datasources/{datasource_id}/lookups/{lookup}", { path: { datasource_id: "rss", lookup: "a b/c" } })).toBe("/api/datasources/rss/lookups/a%20b%2Fc")
	})
	it("adds the query, leaving out what is unset", () => {
		expect(apiUrl("/api/schedule/render", { query: { start: "2026-10-23", days: 7, none: undefined } })).toBe("/api/schedule/render?start=2026-10-23&days=7")
	})
	it("refuses a path whose parameter is missing", () => {
		expect(() => apiUrl("/api/fonts/{family}")).toThrow("needs family")
	})
})

// what the types allow (vue-tsc checks this file; nothing here runs: a call would go to the network)
export function typeChecks() {
	return [
		() => api.get("/api/access"),
		() => api.get("/api/fonts/{family}", { path: { family: "Lexend" } }),
		// @ts-expect-error not a route of the server
		() => api.get("/api/no-such-route"),
		// @ts-expect-error the route has path parameters: they are required
		() => api.get("/api/fonts/{family}"),
		// @ts-expect-error a parameter of another name
		() => api.get("/api/fonts/{family}", { path: { font: "Lexend" } }),
		// @ts-expect-error the route has no POST
		() => api.post("/api/system", {}, {}),
	]
}
