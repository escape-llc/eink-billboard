import { describe, expect, it } from "vitest"
import { describeItem } from "./Describe"

const comic = { id: "comic", name: "Comic", describe: "Comic {comic}" }
const slideShow = { id: "slide-show", name: "Slide Show", describe: "{dataSource}",
	instanceSettings: { schema: { properties: [{ name: "dataSource", type: "schema" }, { name: "slideMinutes", type: "integer" }] } } }

describe("describing a track", () => {
	it("a plugin over a data source says what the source says, with the track's content", () => {
		expect(describeItem(slideShow, { dataSource: "comic", comic: "XKCD" }, [comic])).toBe("Comic XKCD")
	})
	it("falls back to the name when nothing is set or there is no template", () => {
		expect(describeItem(slideShow, {}, [comic])).toBe("Slide Show")
		expect(describeItem({ id: "x", name: "Plain" }, { a: 1 })).toBe("Plain")
	})
	it("names a data source that is gone by its id", () => {
		expect(describeItem(slideShow, { dataSource: "old" }, [comic])).toBe("old")
	})
	it("lists, unset values and long text", () => {
		const cal = { id: "calendar", name: "Calendar", describe: "Calendar {views} {title}" }
		expect(describeItem(cal, { views: ["month", "agenda"], title: "" })).toBe("Calendar month, agenda")
		expect(describeItem(cal, { title: "x".repeat(80) })).toBe(`Calendar ${"x".repeat(39)}…`)
	})
})
