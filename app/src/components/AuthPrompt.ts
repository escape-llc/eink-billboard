/**
 * The sign-in the web app shows when the server answers 401 (see ApiClient.ts): a dialog, not a browser prompt.
 *
 * What it asks depends on the device (`GET /api/access`):
 * - `setup`: a new device nobody has claimed. The setup code (from its log or its panel) and the password to choose;
 * - `password`: the device password;
 * - `token`: a device that has only an API token (no password was ever set).
 *
 * This module holds the state and the steps; `AuthDialog.vue` draws it and ApiClient.ts sends the credentials.
 * Nothing typed here is kept: the server answers with an HttpOnly session cookie.
 */
import { reactive } from "vue"

import type { components } from "../api/schema"

/** What `GET /api/access` answers: the server's own model (`AccessState`), through the generated types (#590). */
export type AccessInfo = components["schemas"]["AccessState"]
export type AuthMode = "setup" | "password" | "token"
export type Values = { secret: string, code?: string }
export type SendResult = { ok: boolean, message?: string }
export type Sender = (mode: AuthMode, values: Values) => Promise<SendResult>

export const MIN_PASSWORD = 8

/** Which question to ask. A server that did not answer `/api/access` gets the token question, as before. */
export function modeOf(info: Partial<AccessInfo> | null | undefined): AuthMode {
	if (info?.setupRequired) return "setup"
	if (info?.passwordSet) return "password"
	return "token"
}

/** What is wrong with the setup form before it is sent (the server checks again); null when it is fine. */
export function setupProblem(code: string, password: string, again: string): string | null {
	if (!code.trim()) return "Enter the setup code."
	if (password.length < MIN_PASSWORD) return `The password needs at least ${MIN_PASSWORD} characters.`
	if (password !== again) return "The two passwords are not the same."
	return null
}

export const authPrompt = reactive({ open: false, mode: "password" as AuthMode, error: "", busy: false,
	/** the setup code the claim route (`#/claim/12345678`, the panel's QR code) brought: the setup dialog starts with it filled in, once */
	claim: "" })

/** The digits of a setup code from an address: spaces and the rest are dropped, and nothing but 1 to 8 digits counts ("" otherwise). */
export function claimCodeOf(text: unknown): string {
	const digits = (Array.isArray(text) ? text[0] : text)
	if (typeof digits !== "string") return ""
	const plain = digits.replace(/\s/g, "")
	return /^\d{1,8}$/.test(plain) ? plain : ""
}

/** The code the dialog opens with (and forgets): only a setup dialog takes it. */
export function takeClaimCode(): string {
	const code = authPrompt.mode === "setup" ? authPrompt.claim : ""
	authPrompt.claim = ""
	return code
}

let resolve: ((ok: boolean) => void) | null = null
let send: Sender | null = null

function finish(ok: boolean) {
	authPrompt.open = false
	authPrompt.busy = false
	const done = resolve
	resolve = null
	send = null
	done?.(ok)
}

/** Open the dialog and wait for it: true once the server accepted the credentials, false when the user closes it. */
export function promptForAuth(info: Partial<AccessInfo> | null | undefined, sender: Sender): Promise<boolean> {
	authPrompt.mode = modeOf(info)
	// a claim code is for a device that wants one: a claimed device is asked for its password and the code is dropped
	if (authPrompt.mode !== "setup") authPrompt.claim = ""
	authPrompt.error = ""
	authPrompt.busy = false
	authPrompt.open = true
	send = sender
	return new Promise<boolean>(r => { resolve = r })
}

/** Send what was typed; the dialog stays open with the server's words when it is refused. */
export async function submitAuth(values: Values & { again?: string }): Promise<void> {
	if (!send || authPrompt.busy) return
	if (authPrompt.mode === "setup") {
		const problem = setupProblem(values.code ?? "", values.secret, values.again ?? "")
		if (problem) {
			authPrompt.error = problem
			return
		}
	}
	else if (!values.secret) {
		authPrompt.error = authPrompt.mode === "token" ? "Enter the API token." : "Enter the password."
		return
	}
	authPrompt.busy = true
	authPrompt.error = ""
	let answer: SendResult
	try {
		answer = await send(authPrompt.mode, { secret: values.secret, code: values.code })
	}
	catch {
		answer = { ok: false, message: "The device could not be reached." }
	}
	if (answer.ok) {
		finish(true)
		return
	}
	authPrompt.busy = false
	authPrompt.error = answer.message || "That did not work."
}

export function cancelAuth(): void {
	finish(false)
}
