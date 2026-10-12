/**
 * Glyphs from Google's Material Symbols (Apache-2.0, the `@material-symbols/svg-400` package, outlined) as CSS classes, used like PrimeIcons:
 * `<i class="mi mi-stop">`, or anywhere PrimeVue takes an icon class (`<Button icon="mi mi-stop" />`). PrimeIcons stays for what it has; this is for the
 * rest. `.mi` is built like `.pi` (an inline-block 1em square, `line-height: 1`, in the text color), with the glyph as a mask over `currentColor`, so it
 * follows the text color, size and hover states of whatever holds it. A glyph is a class `mi-<name>` with the underscores written as hyphens (`mi-skip-next`).
 *
 * Each icon is its own SVG file, imported below by name, so only the ones listed are in the bundle (the package has ~7,800). To add a glyph: look its name up
 * at https://fonts.google.com/icons, import it, and add it to the table. No font file and no CDN: the device may have no internet.
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

/** The class of a glyph: `skip_next` is `mi-skip-next`. */
export const iconClass = (name: MaterialIconName): string => `mi-${name.replaceAll("_", "-")}`

// Material draws inside a margin (a 24 dp icon has 2 dp around its 20 dp live area, and many glyphs are smaller still), so at the same font size
// it looks smaller than a PrimeIcons glyph, which fills its em box: the mask is drawn larger to match.
const SCALE = "120%"

/** The style sheet: `.mi` and one `.mi-<name>` per glyph. */
export function materialIconCss(): string {
	const base = `.mi{display:inline-block;width:1em;height:1em;line-height:1;vertical-align:-.15em;background-color:currentColor;-webkit-mask:var(--mi-image) no-repeat center/${SCALE};mask:var(--mi-image) no-repeat center/${SCALE}}`
	const glyphs = (Object.keys(MATERIAL_ICONS) as MaterialIconName[]).map(name => `.${iconClass(name)}{--mi-image:url("data:image/svg+xml,${encodeURIComponent(MATERIAL_ICONS[name])}")}`)
	return [base, ...glyphs].join("\n")
}

/** Put the style sheet in the page (once). Called by main.ts. */
export function installMaterialIcons(doc: Document = document): void {
	if (doc.getElementById("material-icons")) return
	const style = doc.createElement("style")
	style.id = "material-icons"
	style.textContent = materialIconCss()
	doc.head.appendChild(style)
}
