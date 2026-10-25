/** A telemetry link for tests: it tells its listeners what a test sends (an event, replayed or not; the link coming back). */
import type { LinkListener, TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"

export function fakeLink() {
	const listeners = new Set<LinkListener>()
	const link = { listen: (l: LinkListener) => { listeners.add(l); return () => { listeners.delete(l) } } } as unknown as TelemetryLink
	return {
		link,
		listeners,
		send: (e: TelemetryEvent, replayed = false) => { for(const l of listeners) l.event?.(e, replayed) },
		resume: () => { for(const l of listeners) l.resumed?.() },
	}
}
/** The server's event for a change of the storage that names these paths. */
export const changedEvent = (...paths: unknown[]): TelemetryEvent => ({ seq: 1, source: "application", kind: "config-changed", values: { area: "settings", changed: paths } })
/** Let promises and watchers run. */
export const settle = () => new Promise(resolve => setTimeout(resolve, 0))
