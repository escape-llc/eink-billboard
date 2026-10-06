/** Every message the form's validation shows, in one place (the server sends the same wording for the same rules: see AGENTS.md). */
export const messages = {
	required: "Required",
	notAllowed: "Not one of the allowed values",
	notAvailable: "Not one of the available choices",
	wholeNumbers: "Whole numbers only",
	minimum: (n: number) => `Minimum ${n}`,
	maximum: (n: number) => `Maximum ${n}`,
	latitude: "Latitude is -90 to 90",
	longitude: "Longitude is -180 to 180",
	date: "Expected a date (YYYY-MM-DD)",
} as const
