/**
 * The System page's playlist panel (#520): the playlist the layer is on, its tracks in order, and which one is playing. Where the layer is comes from the
 * transport (`GET /api/transport`, then each `track-started` event); the playlists are the cache's list, the one the playlist page reads, followed while the
 * page is shown, so a playlist edited elsewhere is shown as it is now. The view starts and stops it.
 */
import { computed, ref } from "vue"
import { useQueryCache } from "@pinia/colada"
import { api } from "../api/client"
import type { components } from "../api/schema"
import { followResource } from "../api/resources"
import { useTransport, type Transport } from "../components/Transport"

type PlaylistDocument = components["schemas"]["PlaylistDocument"]
export const PLAYLIST_LIST = "/api/schedule/playlist/list"

export function usePlaylistPanel(options: { transport?: Transport } = {}) {
	const transport = options.transport ?? useTransport()
	const cache = useQueryCache()
	const playlists = ref<PlaylistDocument[]>([])
	const loaded = ref(false)
	let unfollow: (() => void) | undefined

	/** the playlist the layer is on; before its first track, the only one there is (nothing is highlighted then) */
	const playlist = computed(() => {
		const id = transport.state.playlistId
		if (id !== null) return playlists.value.find(p => p.id === id) ?? null
		return playlists.value.length === 1 ? playlists.value[0]! : null
	})
	const tracks = computed(() => playlist.value?.items ?? [])
	/** the index of the track playing, or -1 */
	const playing = computed(() => playlist.value?.id === transport.state.playlistId ? tracks.value.findIndex(t => t.id === transport.state.trackId) : -1)

	function start() {
		unfollow ??= followResource(cache, PLAYLIST_LIST, state => {
			if (state.data) {
				playlists.value = state.data.playlists
				loaded.value = true
			}
		}, () => api.get(PLAYLIST_LIST))
	}
	function stop() {
		unfollow?.()
		unfollow = undefined
	}

	return { transport, playlists, loaded, playlist, tracks, playing, start, stop }
}
