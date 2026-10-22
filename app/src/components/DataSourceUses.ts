/** The data sources a chosen one uses (`uses` in its descriptor) that the device does not have (a disabled source is not loaded): the form says so. */
export function missingUses(uses: string[]|undefined, available: { id: string }[]): string[] {
	return (uses ?? []).filter(id => !available.some(d => d.id === id))
}

/** What a capability (`data-*`) is called in a message; the others read as their feature word. */
const CAPABILITY_NOUNS: Record<string, string> = { "data-weather": "weather", "data-ai-text": "AI text", "data-ai-image": "AI image" }

/**
 * The capabilities a chosen source requires (`requires` in its descriptor) that no provider on the device supplies (a provider is `api` and lists the
 * capability among its features; a disabled one is not loaded), by name: the form says so.
 */
export function missingProviders(requires: string[]|undefined, available: { features?: string[] }[]): string[] {
	return (requires ?? []).filter(c => !available.some(d => d.features?.includes("api") && d.features.includes(c))).map(c => CAPABILITY_NOUNS[c] ?? c)
}
