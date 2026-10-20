/**
 * The width of a form's label column that fits its longest label, so no label wraps (`fieldNameWidth="adaptive"` of BasicForm). The font is not measured (a test has no canvas, and the
 * page may use any of the theme's fonts): a label is counted at a generous 0.6rem a character, plus the padding of the label's box, and the result is kept between a floor and a ceiling
 * (a very long label wraps at the ceiling, as it did before, rather than leaving no room for the field).
 */
export const LABEL_MIN_REM = 10
export const LABEL_MAX_REM = 24
const REM_PER_CHARACTER = 0.6
const PADDING_REM = 2

type Titled = { title?: unknown, type?: unknown, children?: Titled[] }

/** Every label a form shows: the titles of its fields and of the fields its choices bring (a header has no label column). */
export function labelsOf(fields: Titled[] | undefined | null): string[] {
	const found: string[] = []
	for (const field of fields ?? []) {
		if (field.type !== "header" && typeof field.title === "string") found.push(field.title)
		found.push(...labelsOf(field.children))
	}
	return found
}

/** `12.5rem`: wide enough for the longest of `labels`, between the floor and the ceiling. */
export function adaptiveLabelWidth(labels: string[]): string {
	const longest = labels.reduce((most, label) => Math.max(most, label.length), 0)
	const rem = Math.min(LABEL_MAX_REM, Math.max(LABEL_MIN_REM, Math.ceil((longest * REM_PER_CHARACTER + PADDING_REM) * 2) / 2))
	return `${rem}rem`
}
