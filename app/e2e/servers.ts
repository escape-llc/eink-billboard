// The two servers the browser tests run against; shared by playwright.config.ts and the specs.
import path from "node:path"
import { fileURLToPath } from "node:url"

/** The repository root (this file is app/e2e/servers.ts). */
export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")

export const TOKEN = "e2e-token"

export const OPEN = {
	port: 8099,
	url: "http://127.0.0.1:8099",
	// every run starts from a fresh storage built by scripts/e2e_storage.py
	storage: path.join(ROOT, ".e2e-storage", "open"),
}
/** Requires `Authorization: Bearer e2e-token` on /api. */
export const PROTECTED = {
	port: 8098,
	url: "http://127.0.0.1:8098",
	storage: path.join(ROOT, ".e2e-storage", "protected"),
}
