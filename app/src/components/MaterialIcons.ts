/**
 * The app's one set of glyphs (#544): Google's Material Symbols (Apache-2.0, the `@material-symbols/svg-400` package, outlined) as CSS classes:
 * `<i class="mi mi-stop">`, or anywhere PrimeVue takes an icon class (`<Button icon="mi mi-stop" />`). PrimeIcons is not installed; PrimeVue's widgets draw
 * their own SVG icons. `.mi` is an inline-block square of `--mi-size` (1rem unless set, `line-height: 1`, in the text color), with the glyph as a mask over `currentColor`, so it
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
// the layers of the panel (TelemetryLink.ts LAYERS)
import wallpaper from "@material-symbols/svg-400/outlined/wallpaper.svg?raw"
import flip_to_front from "@material-symbols/svg-400/outlined/flip_to_front.svg?raw"
import opacity from "@material-symbols/svg-400/outlined/opacity.svg?raw"
import priority_high from "@material-symbols/svg-400/outlined/priority_high.svg?raw"
import picture_in_picture from "@material-symbols/svg-400/outlined/picture_in_picture.svg?raw"
// the Scheduler's views (SchedulerView.ts MODES)
import calendar_view_day from "@material-symbols/svg-400/outlined/calendar_view_day.svg?raw"
import calendar_view_week from "@material-symbols/svg-400/outlined/calendar_view_week.svg?raw"
import view_list from "@material-symbols/svg-400/outlined/view_list.svg?raw"
// the app's commands and states (every glyph the app shows is one of these: #544)
import add from "@material-symbols/svg-400/outlined/add.svg?raw"
import arrow_downward from "@material-symbols/svg-400/outlined/arrow_downward.svg?raw"
import arrow_upward from "@material-symbols/svg-400/outlined/arrow_upward.svg?raw"
import bolt from "@material-symbols/svg-400/outlined/bolt.svg?raw"
import cancel from "@material-symbols/svg-400/outlined/cancel.svg?raw"
import check from "@material-symbols/svg-400/outlined/check.svg?raw"
import check_circle from "@material-symbols/svg-400/outlined/check_circle.svg?raw"
import chevron_left from "@material-symbols/svg-400/outlined/chevron_left.svg?raw"
import chevron_right from "@material-symbols/svg-400/outlined/chevron_right.svg?raw"
import circle from "@material-symbols/svg-400/outlined/circle.svg?raw"
import close from "@material-symbols/svg-400/outlined/close.svg?raw"
import database from "@material-symbols/svg-400/outlined/database.svg?raw"
// `delete` and `public` are reserved words: imported under other names, listed by their own
import deleteGlyph from "@material-symbols/svg-400/outlined/delete.svg?raw"
import desktop_windows from "@material-symbols/svg-400/outlined/desktop_windows.svg?raw"
import download from "@material-symbols/svg-400/outlined/download.svg?raw"
import edit from "@material-symbols/svg-400/outlined/edit.svg?raw"
import help from "@material-symbols/svg-400/outlined/help.svg?raw"
import history from "@material-symbols/svg-400/outlined/history.svg?raw"
import key from "@material-symbols/svg-400/outlined/key.svg?raw"
import link from "@material-symbols/svg-400/outlined/link.svg?raw"
import menu from "@material-symbols/svg-400/outlined/menu.svg?raw"
import my_location from "@material-symbols/svg-400/outlined/my_location.svg?raw"
import open_in_new from "@material-symbols/svg-400/outlined/open_in_new.svg?raw"
import palette from "@material-symbols/svg-400/outlined/palette.svg?raw"
import play_circle from "@material-symbols/svg-400/outlined/play_circle.svg?raw"
import playlist_add from "@material-symbols/svg-400/outlined/playlist_add.svg?raw"
import publicGlyph from "@material-symbols/svg-400/outlined/public.svg?raw"
import refresh from "@material-symbols/svg-400/outlined/refresh.svg?raw"
import save from "@material-symbols/svg-400/outlined/save.svg?raw"
import search from "@material-symbols/svg-400/outlined/search.svg?raw"
import settings from "@material-symbols/svg-400/outlined/settings.svg?raw"
import settings_backup_restore from "@material-symbols/svg-400/outlined/settings_backup_restore.svg?raw"
import stop_circle from "@material-symbols/svg-400/outlined/stop_circle.svg?raw"
import upload from "@material-symbols/svg-400/outlined/upload.svg?raw"
import videocam from "@material-symbols/svg-400/outlined/videocam.svg?raw"
import wifi from "@material-symbols/svg-400/outlined/wifi.svg?raw"
// the Gallery (#517)
import photo_library from "@material-symbols/svg-400/outlined/photo_library.svg?raw"
import add_photo_alternate from "@material-symbols/svg-400/outlined/add_photo_alternate.svg?raw"
import keep from "@material-symbols/svg-400/outlined/keep.svg?raw"
import keep_off from "@material-symbols/svg-400/outlined/keep_off.svg?raw"

export const MATERIAL_ICONS = { playlist_play, schedule, layers, warning, error, play_arrow, skip_next, stop, image, cloud_off, wb_sunny, screenshot_monitor, wallpaper, flip_to_front, opacity, priority_high, picture_in_picture, calendar_view_day, calendar_view_week, view_list,
	add, arrow_downward, arrow_upward, bolt, cancel, check, check_circle, chevron_left, chevron_right, circle, close, database, delete: deleteGlyph, desktop_windows, download, edit, help, history, key, link, menu, my_location, open_in_new, palette, play_circle, playlist_add, public: publicGlyph, refresh, save, search, settings, settings_backup_restore, stop_circle, upload, videocam, wifi,
	photo_library, add_photo_alternate, keep, keep_off } as const
export type MaterialIconName = keyof typeof MATERIAL_ICONS

/** The class of a glyph: `skip_next` is `mi-skip-next`. */
export const iconClass = (name: MaterialIconName): string => `mi-${name.replaceAll("_", "-")}`

// Material draws inside a margin (a 24 dp icon has 2 dp around its 20 dp live area, and many glyphs are smaller still), so at the same font size
// it looks smaller than a glyph that fills its box (as PrimeVue's own SVG icons do): the mask is drawn larger to match.
const SCALE = "120%"

/** The style sheet: `.mi` and one `.mi-<name>` per glyph. `flex: none` keeps a glyph its size in a flex row (a long text beside it would squeeze it). */
export function materialIconCss(): string {
	const base = `.mi{display:inline-block;flex:none;width:var(--mi-size,1rem);height:var(--mi-size,1rem);line-height:1;vertical-align:-.15rem;background-color:currentColor;-webkit-mask:var(--mi-image) no-repeat center/${SCALE};mask:var(--mi-image) no-repeat center/${SCALE}}`
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
