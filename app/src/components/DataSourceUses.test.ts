import { describe, expect, it } from "vitest"
import { missingProviders, missingUses } from "./DataSourceUses"

describe("the data sources a source uses", () => {
	const available = [{ id: "weather" }, { id: "calendar" }]
	it("names the ones the device does not have", () => {
		expect(missingUses(["weather"], available)).toEqual([])
		expect(missingUses(["weather", "reminders", "ai"], available)).toEqual(["reminders", "ai"])
	})
	it("has none to miss when the source uses nothing", () => {
		expect(missingUses(undefined, available)).toEqual([])
		expect(missingUses([], [])).toEqual([])
	})
})

describe("the capabilities a source requires", () => {
	const available = [{ id: "openweathermap-api", features: ["internet", "api", "data-weather"] }, { id: "weather", features: ["api-client", "layer-foreground", "media-list"] }]
	it("is met by a provider of each", () => {
		expect(missingProviders(["data-weather"], available)).toEqual([])
		expect(missingProviders(undefined, available)).toEqual([])
	})
	it("names a capability no provider supplies, in words", () => {
		expect(missingProviders(["data-weather", "data-ai-text", "data-tides"], available)).toEqual(["AI text", "data-tides"])
		expect(missingProviders(["data-weather"], [])).toEqual(["weather"])
	})
	it("counts only a provider: a page with the feature word supplies nothing", () => {
		expect(missingProviders(["data-weather"], [{ features: ["layer-foreground", "data-weather"] }])).toEqual(["weather"])
	})
})
