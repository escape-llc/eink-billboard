/**
 * Glyphs from Google's Material Symbols (Apache-2.0, the `@material-symbols/svg-400` package, outlined), as an addition to PrimeIcons, which
 * has far fewer. Each icon is its own SVG file, imported here by name, so only the ones listed are in the bundle (the package has ~7,800).
 * To add a glyph: look its name up at https://fonts.google.com/icons, import it below, and add it to the table; use it as `<MaterialIcon name="..." />`.
 * PrimeVue's own widgets keep using PrimeIcons.
 */
import playlist_play from "@material-symbols/svg-400/outlined/playlist_play.svg?raw"
import schedule from "@material-symbols/svg-400/outlined/schedule.svg?raw"
import layers from "@material-symbols/svg-400/outlined/layers.svg?raw"
import warning from "@material-symbols/svg-400/outlined/warning.svg?raw"
import error from "@material-symbols/svg-400/outlined/error.svg?raw"
import play_arrow from "@material-symbols/svg-400/outlined/play_arrow.svg?raw"
import skip_next from "@material-symbols/svg-400/outlined/skip_next.svg?raw"
import stop from "@material-symbols/svg-400/outlined/stop.svg?raw"
import image from "@material-symbols/svg-400/outlined/image.svg?raw"
import cloud_off from "@material-symbols/svg-400/outlined/cloud_off.svg?raw"
import wb_sunny from "@material-symbols/svg-400/outlined/wb_sunny.svg?raw"
import screenshot_monitor from "@material-symbols/svg-400/outlined/screenshot_monitor.svg?raw"

export const MATERIAL_ICONS = { playlist_play, schedule, layers, warning, error, play_arrow, skip_next, stop, image, cloud_off, wb_sunny, screenshot_monitor } as const
export type MaterialIconName = keyof typeof MATERIAL_ICONS
