/** The data sources a chosen one uses (`uses` in its descriptor) that the device does not have (a disabled source is not loaded): the form says so. */
export function missingUses(uses: string[]|undefined, available: { id: string }[]): string[] {
	return (uses ?? []).filter(id => !available.some(d => d.id === id))
}
