/**
 * For the tests: run a composable as a view's setup would, in an app with Pinia and the cache of the API's answers (api/resources.ts), so a query
 * finds its options. Each call is a new app, so a test never sees another's answers.
 */
import { createPinia } from "pinia"
import { createApp, effectScope } from "vue"
import { installResources } from "./resources"

export function inApp<T>(setup: () => T): T {
	const app = createApp({ render: () => null })
	app.use(createPinia())
	installResources(app)
	return app.runWithContext(() => effectScope(true).run(setup) as T)
}
