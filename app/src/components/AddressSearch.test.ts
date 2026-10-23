import { describe, expect, it } from "vitest"
import { addressSearch, KEPT_ANSWERS, MIN_INTERVAL_MS, type Place } from "./AddressSearch"

const PLACE: Place = { label: "Somewhere", latitude: 1, longitude: 2 }

/** A clock that only moves when the search sleeps, and records the sleeps. */
function fakeClock() {
	let now = 0
	const sleeps: number[] = []
	return { sleeps, advance: (ms: number) => { now += ms }, clock: { now: () => now, sleep: async (ms: number) => { sleeps.push(ms); now += ms } } }
}

describe("addressSearch follows Nominatim's usage policy", () => {
	it("asks once for a text, and keeps the answer", async () => {
		const asked: string[] = []
		const search = addressSearch(async q => { asked.push(q); return [PLACE] }, fakeClock().clock)
		expect(await search("  Main   Street ")).toEqual([PLACE])
		expect(await search("main street")).toEqual([PLACE])
		expect(asked).toEqual(["Main Street"])
	})

	it("does not ask for a text too short to be worth it", async () => {
		const asked: string[] = []
		const search = addressSearch(async q => { asked.push(q); return [] }, fakeClock().clock)
		expect(await search(" ab ")).toEqual([])
		expect(await search(undefined)).toEqual([])
		expect(asked).toEqual([])
	})

	it("ignores a search while one is running", async () => {
		let answer: (places: Place[]) => void = () => {}
		let asks = 0
		const search = addressSearch(() => { asks++; return new Promise(resolve => { answer = resolve }) }, fakeClock().clock)
		const first = search("first place")
		expect(await search("second place")).toBeNull()
		answer([PLACE])
		expect(await first).toEqual([PLACE])
		expect(asks).toBe(1)
	})

	it("waits so that requests are at least a second apart", async () => {
		const { clock, sleeps, advance } = fakeClock()
		const search = addressSearch(async () => [PLACE], clock)
		await search("first place")
		advance(300)
		await search("second place")
		expect(sleeps).toEqual([MIN_INTERVAL_MS - 300])
		advance(MIN_INTERVAL_MS)
		await search("third place")
		expect(sleeps).toHaveLength(1)
	})

	it("does not keep a failure, and passes its error on", async () => {
		let fail = true
		const search = addressSearch(async () => { if (fail) throw new Error("offline"); return [PLACE] }, fakeClock().clock)
		await expect(search("some place")).rejects.toThrow("offline")
		fail = false
		expect(await search("some place")).toEqual([PLACE])
	})

	it("keeps a bounded number of answers, dropping the oldest", async () => {
		const asked: string[] = []
		const search = addressSearch(async q => { asked.push(q); return [] }, fakeClock().clock)
		for (let i = 0; i <= KEPT_ANSWERS; i++) await search(`place ${i}`)
		await search("place 0")
		await search(`place ${KEPT_ANSWERS}`)
		expect(asked).toHaveLength(KEPT_ANSWERS + 2)
	})
})
