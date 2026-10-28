import { describe, expect, it } from "vitest"
import { authPrompt, cancelAuth, claimCodeOf, modeOf, promptForAuth, setupProblem, submitAuth, takeClaimCode, type Sender } from "./AuthPrompt"

const info = { required: true, setupRequired: false, passwordSet: false, localOnly: false }

describe("which question the sign-in asks", () => {
	it("is setup for a new device, the password when one is set, and the token otherwise", () => {
		expect(modeOf({ ...info, setupRequired: true })).toBe("setup")
		expect(modeOf({ ...info, passwordSet: true })).toBe("password")
		expect(modeOf(info)).toBe("token")
	})
	it("asks for the token when the server did not say", () => {
		expect(modeOf(null)).toBe("token")
		expect(modeOf(undefined)).toBe("token")
	})
})

describe("the setup form", () => {
	it("needs the code, a long enough password, and the same one twice", () => {
		expect(setupProblem("", "long enough", "long enough")).toMatch(/code/)
		expect(setupProblem("1234 5678", "short", "short")).toMatch(/at least 8/)
		expect(setupProblem("1234 5678", "long enough", "different")).toMatch(/not the same/)
		expect(setupProblem("1234 5678", "long enough", "long enough")).toBeNull()
	})
})

describe("the dialog's steps", () => {
	it("stays open with the server's words when refused, and closes when accepted", async () => {
		const sent: string[] = []
		const sender: Sender = async (mode, values) => {
			sent.push(`${mode}:${values.secret}`)
			return values.secret === "right password" ? { ok: true } : { ok: false, message: "Wrong password." }
		}
		const result = promptForAuth({ ...info, passwordSet: true }, sender)
		expect(authPrompt.open).toBe(true)
		expect(authPrompt.mode).toBe("password")
		await submitAuth({ secret: "nope" })
		expect(authPrompt.open).toBe(true)
		expect(authPrompt.error).toBe("Wrong password.")
		await submitAuth({ secret: "right password" })
		expect(authPrompt.open).toBe(false)
		expect(await result).toBe(true)
		expect(sent).toEqual(["password:nope", "password:right password"])
	})

	it("sends nothing for an empty field or an invalid setup, and says why", async () => {
		const sent: string[] = []
		const result = promptForAuth({ ...info, setupRequired: true }, async mode => { sent.push(mode); return { ok: true } })
		await submitAuth({ secret: "", code: "1234 5678", again: "" })
		expect(authPrompt.error).toMatch(/at least 8/)
		await submitAuth({ secret: "long enough", code: "1234 5678", again: "long enough" })
		expect(sent).toEqual(["setup"])
		expect(await result).toBe(true)
	})

	it("resolves false when it is closed, and a device that cannot be reached says so", async () => {
		const result = promptForAuth(info, async () => { throw new Error("offline") })
		await submitAuth({ secret: "token" })
		expect(authPrompt.error).toBe("The device could not be reached.")
		expect(authPrompt.busy).toBe(false)
		cancelAuth()
		expect(await result).toBe(false)
		expect(authPrompt.open).toBe(false)
	})
})

describe("the setup code from the claim address (#491)", () => {
	it("is the digits, and nothing that is not one to eight of them", () => {
		expect(claimCodeOf("12345678")).toBe("12345678")
		expect(claimCodeOf("1234 5678")).toBe("12345678")
		expect(claimCodeOf(["12345678", "x"])).toBe("12345678")
		for (const bad of ["", "abcd", "123456789", "1234-5678", "<script>", undefined, null, 12345678]) expect(claimCodeOf(bad), String(bad)).toBe("")
	})
	it("is taken once, and only by a setup dialog", async () => {
		const send: Sender = async () => ({ ok: true })
		authPrompt.claim = "12345678"
		void promptForAuth({ setupRequired: true }, send)
		expect(takeClaimCode()).toBe("12345678")
		expect(takeClaimCode()).toBe("")
		cancelAuth()
		// a claimed device asks for its password: the code is dropped, not kept for a later setup
		authPrompt.claim = "12345678"
		void promptForAuth({ passwordSet: true }, send)
		expect(authPrompt.claim).toBe("")
		cancelAuth()
	})
})
