/**
 * The fields of a prompt: `{name}` in the text stands for a value the data behind it supplies. The same expression as `TOKEN` in python/utils/prompt_tokens.py,
 * so the form and the server read a text the same way: `{{` and `}}` are a literal brace, any other brace is plain text.
 */
export type TokenDef = { name: string, description: string }

const TOKEN = /\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}/g

/** The field names a text uses, in order, once each. */
export function tokenNames(text: string): string[] {
	const found: string[] = []
	for (const match of text.matchAll(TOKEN)) {
		const name = match[1]
		if (name !== undefined && !found.includes(name)) found.push(name)
	}
	return found
}

/** The first field in the text that is not one of `known`, or undefined. */
export function unknownToken(text: string, known: readonly string[]): string|undefined {
	return tokenNames(text).find(name => !known.includes(name))
}
