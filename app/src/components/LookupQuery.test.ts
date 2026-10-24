import { describe, expect, it } from "vitest"
import { lookupAddress, withStored } from "./LookupQuery"

// a lookup that takes parameters (#510 A8): the values it is sent with, and the search text
describe("a lookup's address", () => {
	const values: Record<string, unknown> = { imageModel: "gpt-image-2", count: 3, on: false, days: [1, 2], none: null, empty: "", place: { latitude: 1 } }
	const read = (name: string) => values[name]

	it("is its url when it takes nothing", () => {
		expect(lookupAddress("/api/x", undefined, read)).toEqual({ address: "/api/x" })
	})

	it("sends each named field's value, encoded", () => {
		expect(lookupAddress("/api/x", ["imageModel", "count", "on"], read)).toEqual({ address: "/api/x?imageModel=gpt-image-2&count=3&on=false" })
		expect(lookupAddress("/api/x", ["days"], read)).toEqual({ address: "/api/x?days=1&days=2" })
		expect(lookupAddress("/api/x?kind=a", ["imageModel"], read)).toEqual({ address: "/api/x?kind=a&imageModel=gpt-image-2" })
	})

	it("waits for the first named field that has no value", () => {
		expect(lookupAddress("/api/x", ["imageModel", "none", "empty"], read)).toEqual({ missing: "none" })
		expect(lookupAddress("/api/x", ["empty"], read)).toEqual({ missing: "empty" })
		expect(lookupAddress("/api/x", ["gone"], read)).toEqual({ missing: "gone" })
	})

	it("sends no value it cannot write as text", () => {
		expect(lookupAddress("/api/x", ["place"], read)).toEqual({ address: "/api/x" })
	})

	it("sends the search text as q, an empty one too", () => {
		expect(lookupAddress("/api/x", ["imageModel"], read, "new york")).toEqual({ address: "/api/x?imageModel=gpt-image-2&q=new+york" })
		expect(lookupAddress("/api/x", undefined, read, "")).toEqual({ address: "/api/x?q=" })
	})
})

describe("a list with the stored value", () => {
	const list = [{ name: "High", value: "high" }]
	it("keeps a stored value the list does not offer, so it does not look unset", () => {
		expect(withStored(list, "max")).toEqual([...list, { name: "max", value: "max" }])
		expect(withStored(list, ["high", "low"])).toEqual([...list, { name: "low", value: "low" }])
	})
	it("names a stored value by an earlier answer when it can", () => {
		expect(withStored(list, "co_tg", v => v === "co_tg" ? "The Gazette" : undefined)).toEqual([...list, { name: "The Gazette", value: "co_tg" }])
	})
	it("adds nothing for a value it offers, or for none", () => {
		expect(withStored(list, "high")).toEqual(list)
		expect(withStored(list, null)).toEqual(list)
		expect(withStored(list, "")).toEqual(list)
	})
})
