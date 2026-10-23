// ESLint for the web app: the basic rule sets only (#510 A7). JavaScript's recommended rules, typescript-eslint's recommended rules and Vue's
// "essential" set, which catches mistakes and leaves formatting alone (the code is indented with tabs on purpose). `npm run lint`; CI runs it in the web job.
import js from "@eslint/js"
import tseslint from "typescript-eslint"
import vue from "eslint-plugin-vue"
import globals from "globals"

export default tseslint.config(
	{ ignores: ["dist/", "node_modules/", "playwright-report/", "test-results/", "public/"] },
	js.configs.recommended,
	...tseslint.configs.recommended,
	...vue.configs["flat/essential"],
	{
		files: ["**/*.vue"],
		languageOptions: { parserOptions: { parser: tseslint.parser } },
	},
	{
		languageOptions: { globals: { ...globals.browser }, ecmaVersion: "latest", sourceType: "module" },
		rules: {
			// the type checker (vue-tsc) already knows every name, Vite's defines (__APP_VERSION__) included: typescript-eslint's own advice
			"no-undef": "off",
			// a name that starts with _ is unused on purpose (an ignored argument, a key left out of a copy)
			"@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", destructuredArrayIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" }],
			// off until the form engine is typed (#510 A3): it is nearly all of BasicForm, BasicFormField and ArrayField
			"@typescript-eslint/no-explicit-any": "off",
		},
	},
	{
		// a page is named after what it shows (Settings, System)
		files: ["src/views/**/*.vue"],
		rules: { "vue/multi-word-component-names": "off" },
	},
	{
		// the tools' own configuration runs in Node
		files: ["*.config.{js,ts}", "e2e/**/*.ts", "scripts/**/*.{js,ts}"],
		languageOptions: { globals: { ...globals.node } },
	},
)
