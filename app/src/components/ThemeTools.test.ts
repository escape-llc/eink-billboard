import { beforeEach, describe, expect, it } from "vitest"
import { getTheme, saveTheme } from "./ThemeTools"

// vite.config.ts defines __APP_PACKAGE__ from package.json's name, which is the default storage key's suffix
const DEFAULT_KEY = `theme-${__APP_PACKAGE__}`

describe("theme storage", () => {
	beforeEach(() => localStorage.clear())

	it("finds nothing before a theme was saved", () => {
		expect(getTheme()).toBeNull()
		expect(getTheme("another-key")).toBeNull()
	})

	it("saves a complete theme with defaults for what was not given, and reads it back", () => {
		const saved = saveTheme()
		expect(Object.keys(saved).sort()).toEqual(["mode", "name", "primary", "surface"])
		expect(Object.values(saved).every(v => typeof v === "string" && v.length > 0)).toBe(true)
		expect(getTheme()).toEqual(saved)
		expect(JSON.parse(localStorage.getItem(DEFAULT_KEY) as string)).toEqual(saved)
	})

	it("keeps the values it is given and fills in only the missing ones", () => {
		const defaults = saveTheme()
		const custom = saveTheme(undefined, "Aura", "dark", "teal", undefined)
		expect(custom).toEqual({ name: "Aura", mode: "dark", primary: "teal", surface: defaults.surface })
		expect(getTheme()).toEqual(custom)
	})

	it("keeps themes saved under different keys apart", () => {
		saveTheme("one", "Lara", "light", "rose", "slate")
		saveTheme("two", "Nora", "dark", "lime", "zinc")
		expect(getTheme("one")).toMatchObject({ name: "Lara", primary: "rose" })
		expect(getTheme("two")).toMatchObject({ name: "Nora", primary: "lime" })
		expect(getTheme()).toBeNull()
	})
})
