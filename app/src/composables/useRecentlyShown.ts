/**
 * What the panel shows and showed lately (#517): read from the telemetry link's own state, not asked for, so the System page and the Gallery page's
 * Recently shown tab show the same pictures. The device keeps the last few pictures it sent (`/api/display/images/<digest>`), by the digest the
 * `shown` events carry.
 */
import { computed } from "vue"
import type { TelemetryEvent, TelemetryLink } from "../components/TelemetryLink"

/** How many pictures are listed (the device keeps 8). */
export const RECENT_COUNT = 7

export function useRecentlyShown(link: TelemetryLink) {
	const current = computed(() => link.state.current?.values?.digest ? link.state.current : null)
	/** What the panel showed lately, newest first, each picture once (the current one first). */
	const recent = computed(() => {
		const seen = new Set<string>()
		return [current.value, ...link.state.events.filter(e => e.kind === "shown")]
			.filter((e): e is TelemetryEvent => !!e && !!e.values?.digest && !seen.has(e.values.digest) && !!seen.add(e.values.digest))
			.slice(0, RECENT_COUNT)
	})
	return { current, recent }
}

/** A shown picture's title (the page or track it was). */
export const shownTitle = (e: TelemetryEvent): string => String(e.values?.title ?? "")
