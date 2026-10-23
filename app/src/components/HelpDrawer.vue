<template>
	<Drawer :visible="visible" position="right" header="Help" class="help-drawer" style="width:min(30rem, 95vw)" data-testid="help"
		@update:visible="(v: boolean) => emit('update:visible', v)">
		<p class="intro">
			eInk Billboard shows pictures and pages on an e-Ink panel. You say <b>what</b> to show and <b>when</b>; the device does the rest, by itself, all day.
		</p>

		<Accordion v-model:value="open" multiple>
			<AccordionPanel value="start">
				<AccordionHeader>First steps</AccordionHeader>
				<AccordionContent>
					<ol>
						<li><b>Settings, System:</b> set the device's <b>Location</b> and time zone. Weather, maps and the clock use them. <b>Weather Provider</b> says where the weather comes from; left empty, it is the one that is set up (Open-Meteo, which needs no key; with OpenWeatherMap's key set too, choose one). <b>Units</b> are the weather's: Automatic means miles and Fahrenheit in US time zones, kilometres and Celsius elsewhere, and the temperature and the wind speed can each be given a unit of their own (Celsius with miles per hour, say). To find a place, type its address and press <i class="mi mi-search" aria-hidden="true"></i> Search (or Enter), then choose it from the list; or click the map. The <i class="mi mi-wifi" aria-hidden="true"></i> button beside the map finds a rough position from the device's internet address; nothing is saved until you press Save.</li>
						<li><b>Settings, Display:</b> choose the panel you have, and its orientation.</li>
						<li><b>Playlist:</b> make a playlist and add <b>tracks</b>. A track is one page or picture and how long it stays. Save the playlist: nothing reaches the panel until it is saved.</li>
						<li>The weather works without a key (from Open-Meteo). If a track needs a key (maps, comics, AI pictures, or OpenWeatherMap's weather), add it under <b>Settings, Providers</b>. Each key has a <b>Test</b> button and a link to where you get one.</li>
					</ol>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="pages">
				<AccordionHeader>The pages</AccordionHeader>
				<AccordionContent>
					<dl>
						<dt><i class="mi mi-schedule" aria-hidden="true"></i> Schedule</dt>
						<dd>Timer tasks: things that happen at a time of day, such as a priority message for ten minutes at 8:00, or an overlay (the date, the weather) drawn over the picture. Shown as a day, a week or a list.</dd>
						<dt><i class="mi mi-play-arrow" aria-hidden="true"></i> Playlist</dt>
						<dd>The tracks that play one after another, round and round. You can keep several playlists.</dd>
						<dt><i class="mi mi-desktop-windows" aria-hidden="true"></i> System</dt>
						<dd>How the device is: whether its parts started and the latest problems, the machine (load, memory, how long it and the app have been up), a Raspberry Pi's temperature and power warnings, the storage by plugin and data source, and the <b>API usage</b> of each service. On the right, live: <b>Now showing</b> (what the panel shows, with the layers it is made of; click for full size), <b>Recently shown</b> and <b>Activity</b> (filter it by source, or show only problems). The toolbar has play, stop and next, and Back up, Restore and the device password.</dd>
						<dt><i class="mi mi-settings" aria-hidden="true"></i> Settings</dt>
						<dd>The device (System, Display, Theme, Devices such as buttons), the plugins, the data sources (what makes a page or an overlay) and the providers (where their data comes from, with the keys), each with its own settings.</dd>
					</dl>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="layers">
				<AccordionHeader>How a picture gets on the panel</AccordionHeader>
				<AccordionContent>
					<p>A <b>data source</b> makes the content (a comic, the weather, a map, your own pictures, a web address). A <b>plugin</b> decides how it is shown (a slide show, a priority message, an overlay). A page is drawn on a <b>layer</b>, back to front:</p>
					<ol>
						<li><b>Background</b>: the playlist's pictures. <b>Overlays</b> (clock, weather, reminders) are drawn only over a background page.</li>
						<li><b>Foreground</b>: pages with text that must not be covered (a comic, a calendar, a map). They hide the overlays while they show.</li>
						<li><b>Priority</b>: a timer task's message, which takes the panel for its minutes and then gives it back.</li>
					</ol>
					<p>An e-Ink panel is slow: it rests after each refresh, so a change can take a little while to appear.</p>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="play">
				<AccordionHeader>Play, stop and next</AccordionHeader>
				<AccordionContent>
					<p>On the System page's toolbar, <b>Stop</b> holds the panel as it is (timer tasks keep running) and <b>Play</b> carries on. <b>Next</b> skips to the following track. A button wired to the device can do the same.</p>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="keys">
				<AccordionHeader>API keys and costs</AccordionHeader>
				<AccordionContent>
					<p>Some providers need a key from their service (<b>Settings, Providers</b>): OpenWeatherMap, Comic Vine, Thunderforest (maps), OpenAI and Google AI (generated pictures). Most have a free plan; generated pictures are paid by use. Keys are kept on the device, are never shown again (a field shows only stars), and are sent only to their own service.</p>
					<p>Downloads are kept for a while (see each data source's <b>Keep</b> settings), so a free plan's quota goes a long way. The System page shows how much each source keeps, and under <b>API usage</b> how many calls each service has been asked for (today, this week, this month), how many failed, and how much the cache spared. Check it against your plan's quota.</p>
					<p>Under each source, the calls by the service's answer: <code>200</code> is fine, <code>401</code> a key refused, <code>429</code> too many requests (and when it last said so); <code>timeout</code>, <code>connect</code> or <code>tls</code> means the service was not reached. Only counts are kept, never an address or a key.</p>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="providers">
				<AccordionHeader>Providers: where the data comes from</AccordionHeader>
				<AccordionContent>
					<p>A provider fetches data and draws nothing; the data sources that make pages and overlays ask it. Each is in <b>Settings, Providers</b> with its key and how long its answers are kept, shared by every page and overlay that uses it. A data source that needs a kind of data (the weather, calendar events) takes it from the device's provider of that kind: <b>Weather Provider</b> and <b>Calendar Provider</b> in <b>Settings, System</b>, or, left empty, the one that is set up. A provider that is not set up yet says so there.</p>
					<dl>
						<dt>Open-Meteo</dt>
						<dd>The weather, with no key: free for non-commercial use such as this, and set up as installed, so a new device has weather at once. Its credit is on the Weather pages and under Credits, below. No place name: the page's heading is its title, or "Weather".</dd>
						<dt>OpenWeatherMap</dt>
						<dd>The weather too, with a key: when both are set up, choose one as <b>Weather Provider</b> in <b>Settings, System</b>. A free key will do; a new one can take a couple of hours to start working, and until then the pages say it was refused.</dd>
						<dt>Calendar Sources</dt>
						<dd>Calendar events, for the Calendar pages and the Reminder Overlay: iCal links, CalDAV servers, Google and Microsoft accounts, and holidays (see Calendars).</dd>
						<dt>OpenAI, Google AI</dt>
						<dd>Text and pictures for the Generated Image and the Weather Visualizer: each holds its key and the models it may use, and its text and image parts are chosen in a task.</dd>
						<dt>Comic Vine, Thunderforest</dt>
						<dd>The comic covers and the maps, each for its own data source, with a free key.</dd>
					</dl>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="plugins">
				<AccordionHeader>Plugins: how a source is shown</AccordionHeader>
				<AccordionContent>
					<dl>
						<dt>Slide Show (a playlist track)</dt>
						<dd>Shows its data source's pages, each for <b>Slide Duration Minutes</b>, up to <b>Max Slides</b> for a source with several. A feed or folder is a list: with <b>continue</b> each visit goes on where the last stopped, and the list is fetched again when used up or after <b>Fetch Again After</b> hours; <b>restart</b> takes a new list every visit. <b>Show As</b>: <b>auto</b> (a text page covers everything, a picture is a background), <b>background</b> (overlays are drawn on it), <b>blend</b> (washes over the page before it) or <b>override</b>.</dd>
						<dt>Priority Update (a timer task)</dt>
						<dd>Takes the panel for its minutes, then gives it back; the playlist keeps running underneath. <b>Show As</b> <b>priority</b> covers the whole screen, <b>blend</b> washes over what the playlist shows. Several queue up. A clock on the hour for a minute is one.</dd>
						<dt>Overlay (a timer task)</dt>
						<dd>Draws an overlay source in one of six <b>zones</b> (three across the top, three across the bottom) until its next run replaces it; when the source has nothing to show, the overlay is taken down. <b>Outline</b> (0 to 1) sets how wide the outline around the text is. Overlays are not kept across a restart, so trigger the task on startup too: the date in <code>top-right</code>, on startup and every day at 0:00, is a good first one.</dd>
					</dl>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="pictures">
				<AccordionHeader>Sources: pictures</AccordionHeader>
				<AccordionContent>
					<p>A picture is a background page: overlays may be drawn on it. One whose shape is not the panel's is shown whole on a blurred margin of itself.</p>
					<dl>
						<dt>Image Folder</dt>
						<dd>Your own pictures. List folders (a name and a path on the device) in its settings; a track picks one by name and shows it picture by picture.</dd>
						<dt>Image from a Web Address</dt>
						<dd>One picture fetched every time it is shown: a camera snapshot, a chart, a weather map. <b>Test</b> fetches it and says its size and format. PNG, JPEG, GIF or WEBP, at most 10 MB; <b>Shrink to Fit</b> shows it whole. Addresses on the device itself are refused.</dd>
						<dt>Wikipedia Picture of the Day</dt>
						<dd>Today's, a day you choose, or a random day.</dd>
						<dt>NASA Picture of the Day</dt>
						<dd>NASA's Astronomy Picture of the Day: today's (or the latest picture when today's is a video), a day you choose, or a random day since 1995. No key needed.</dd>
						<dt>Generated Image</dt>
						<dd>Drawn by an AI model from your prompt, which a text model can rewrite first so no two are alike. Its <b>Image Source</b> draws and its <b>Text Source</b> rewrites; each is OpenAI's or Google's, and they can be mixed, each with its own fields (model, quality). The keys are under <b>Settings, Providers</b>, OpenAI or Google AI (<b>Test</b> says which models the key may use; a Google key is an AI Studio key starting with <code>AQ.</code>). The newest models draw in the panel's shape. Paid by use: see API usage on the System page.</dd>
						<dt>Weather Visualizer</dt>
						<dd>A Generated Image whose prompt talks about the weather where the device is: fields such as <code>{temp}</code>, <code>{condition}</code>, <code>{daypart}</code> or <code>{season}</code> are filled from the device's weather provider, and the form lists the ones it knows. Needs a weather provider and an AI provider. A field that is not known drops out and the picture is still drawn; write the prompt so it reads without any one of them.</dd>
						<dt>Master Prompts</dt>
						<dd>Settings, Master Prompts: the instructions the Generated Image gives its text model and the picture instructions it adds for the panel. <b>Restore default</b> puts one back in the form, <b>Restore defaults</b> all of them; nothing is saved until you save. <code v-pre>{{</code> and <code v-pre>}}</code> write a brace.</dd>
					</dl>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="source-pages">
				<AccordionHeader>Sources: pages</AccordionHeader>
				<AccordionContent>
					<p>A page with text covers the overlays while it shows.</p>
					<dl>
						<dt>Weather</dt>
						<dd>The weather at the device's <b>Location</b> (Settings, System), from the device's weather provider: <b>now</b>, the next day in three-hour steps (<b>hours</b>), the next five <b>days</b>, a page per view. Needs a weather provider (see Providers); the units are in <b>Settings, System</b>.</dd>
						<dt>Calendar</dt>
						<dd>The <b>month</b>, the coming <b>weeks</b> as continuous rows, or an <b>agenda</b> of the coming days, from the device's calendar provider, the Calendar Sources (see Calendars). Whether weeks start on Monday or Sunday, and the week numbers, are its own settings (<b>Settings, Data Sources, Calendar</b>).</dd>
						<dt>RSS Feed</dt>
						<dd>A feed's stories, one page each, newest first. List feeds (a name and an address) in its settings and pick one by name; <b>Include Images</b> adds a story's picture.</dd>
						<dt>Comic</dt>
						<dd>The latest strips of a web comic (XKCD, SMBC, Dinosaur Comics, ...), with the title and caption when <b>Show Caption</b> is on.</dd>
						<dt>Comic Vine Covers</dt>
						<dd>The covers of a comic series, in a random order. The free key is in <b>Settings, Providers, Comic Vine</b>; <b>Test</b> on the series says which one the search matches (the first match is used). Comic Vine limits requests an hour.</dd>
						<dt>Newspaper Picture of the Day</dt>
						<dd>Today's front page of the newspaper you choose.</dd>
						<dt>Thunderforest Map</dt>
						<dd>A map of a place (kept in its settings, chosen on the map picker) or of the device's location, in a <b>style</b> (<b>transport</b> shows the bus and rail lines; not live transit) and a <b>zoom</b>. The free key is in <b>Settings, Providers, Thunderforest</b>; a map is kept for a week, since the free plan has a monthly quota.</dd>
						<dt>Clock, Countdown, Year Progress</dt>
						<dd>A clock face, the days to a date you choose, and how far through the year it is. Also usable as a Priority Update.</dd>
					</dl>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="overlays">
				<AccordionHeader>Sources: overlays</AccordionHeader>
				<AccordionContent>
					<p>Overlay text is outlined in the theme's outline color and uses the theme's overlay font. Overlays show only over a background page with nothing above it.</p>
					<dl>
						<dt>Today</dt>
						<dd>The date (<b>long</b>, <b>full</b>, <b>short</b>, <b>numeric</b>, or a pattern of your own), the weekday highlighted.</dd>
						<dt>Weather Overlay</dt>
						<dd><b>now</b> (the temperature and the sky), <b>today</b> (the high, the low, the chance of rain) or <b>outlook</b> (the next three days). Needs a weather provider (see Providers).</dd>
						<dt>Reminder Overlay</dt>
						<dd>The events on now or starting within the task's window, nearest first, from the device's calendar provider (the Calendar Sources). Nothing in the window takes it down. A calendar edit shows once the kept answer expires (15 minutes by default).</dd>
					</dl>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="calendar">
				<AccordionHeader>Calendars</AccordionHeader>
				<AccordionContent>
					<p>The calendars are listed in <b>Settings, Providers, Calendar Sources</b>, which every calendar page and Reminder Overlay reads (<b>Calendar Provider</b> in Settings, System says which, when there is more than one); a track or overlay chooses which to show (none chosen: all that are enabled) and its views: the <b>month</b>, the coming <b>weeks</b> as continuous rows, an <b>agenda</b> of the coming days.</p>
					<ul>
						<li><b>An iCal link</b> (<code>https</code> or <code>webcal</code>): most calendar apps publish one. Google's "Secret address in iCal format" is a password: treat it as one. A link that needs a sign-in can use a user name and password, or a token.</li>
						<li><b>A CalDAV server</b> (Nextcloud, Fastmail, iCloud with an app password).</li>
						<li><b>Holidays</b> by country, state or province; no internet needed.</li>
						<li>The <b>Test</b> button says how many events are coming, and warns when a calendar <b>runs out</b> (nothing repeats after its last event, as with a season's fixtures).</li>
					</ul>
					<p><b>Google and Microsoft accounts</b> sign in with an app registration of your own (once per account), entered in an Accounts row; save, then press <b>Connect</b>, which also lists the account's calendars and their IDs (an empty ID is the main calendar).</p>
					<ul>
						<li><b>Google:</b> in the Google Cloud console, make a project, enable the <b>Google Calendar API</b>, and create an <b>OAuth client ID</b> of type <b>Desktop app</b>; copy its ID and secret into the row. <b>Publish</b> the app on the consent screen (one left in "Testing" is signed out after 7 days; Google warns once that it is unverified). After the sign-in your browser lands on a <code>http://localhost/...</code> address that does not load: copy that whole address back into the settings page.</li>
						<li><b>Microsoft:</b> in the Microsoft Entra admin center, register an app, allow <b>public client flows</b>, and add the delegated permissions <b>Calendars.Read</b> and <b>offline_access</b>; copy its application (client) ID into the row (tenant <code>common</code> for a personal or any work account). Connect shows a code: enter it at microsoft.com/devicelogin on any device.</li>
					</ul>
					<p>Delete an account or change its client ID, and it must be connected again.</p>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="display">
				<AccordionHeader>The panel</AccordionHeader>
				<AccordionContent>
					<p><b>Settings, Display</b>: the <b>Display Type</b> and the orientation; each type's own settings appear once it is chosen. Restart after changing the type.</p>
					<dl>
						<dt>Inky</dt>
						<dd>A Pimoroni Inky says which board it is. <b>Inky Palette Saturation</b> (0.5 suits most pictures) is for a 7-color Impression. <b>Border Color</b> is the thin frame the picture does not cover; a color the board has no ink for leaves the board's own.</dd>
						<dt>Waveshare</dt>
						<dd>A Waveshare cannot say what it is: choose its <b>Waveshare Model</b>, as Waveshare names its driver (the label on the panel or its box; <code>epd7in3e</code> is the 7.3 inch 7-color one).</dd>
						<dt>Mock and Tk</dt>
						<dd>No panel: the pages are saved as pictures in a folder (Mock) or shown in a window (Tk), at the width and height you give.</dd>
					</dl>
					<p><b>Rest After a Refresh</b> (60 seconds) is how long the panel rests after each refresh before it is sent another picture; what changes meanwhile is shown together at the next one. A panel that does not answer is not replaced by the mock display: the System page's Device card says why.</p>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="buttons">
				<AccordionHeader>Buttons</AccordionHeader>
				<AccordionContent>
					<p><b>Settings, Devices</b>: the GPIO (BCM) number of each push button, wired between that pin and ground; leave it empty when there is none. <b>Play / Stop</b> toggles playback, <b>Next</b> shows the next page, <b>Stop</b> only stops. A change applies within seconds, no restart.</p>
					<p>The panel's own pins are refused (Waveshare 8, 10, 11, 17, 18, 24, 25; Inky 8, 10, 11, 17, 22, 27, and 16 and 26 on the 13.3 inch one), as are pins outside 2 to 27 and two buttons on one pin.</p>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="kept">
				<AccordionHeader>Kept downloads and answers</AccordionHeader>
				<AccordionContent>
					<p>Sources keep what they download, shared by every task that uses them, so a picture or a feed is not fetched again for each one and a free plan's quota goes a long way. The settings are each data source's:</p>
					<ul>
						<li><b>Keep Downloads (hours)</b> and <b>Keep Feeds (hours)</b>: the longest a picture or feed is kept before it is asked for again (0 keeps nothing). A site can ask for less, never for more. Asking again sends what was kept, so an unchanged picture is not downloaded twice; when the site does not answer, the old one is shown.</li>
						<li><b>Downloads Pool Size (MB)</b>: the most disk it may use; the download used longest ago goes first. <b>Forget Unused Downloads After (days)</b> removes what nobody uses (0: never).</li>
						<li>Answers are kept the same way: OpenWeatherMap's current weather and forecast, each calendar (15 minutes), Comic Vine's searches and issues, Thunderforest's maps.</li>
						<li>A Slide Show keeps its list of a feed or folder between visits; <b>Forget Unused Lists After (days)</b> in its settings removes the list of a track you deleted.</li>
					</ul>
					<p>The System page's Storage card shows how much each source keeps; none of it is in a backup.</p>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="safe">
				<AccordionHeader>Keeping it safe</AccordionHeader>
				<AccordionContent>
					<ul>
						<li>A new device asks for a <b>setup code</b> (in its log and on the panel) and then your own password. Change it from the System page's <i class="mi mi-key" aria-hidden="true"></i> button.</li>
						<li><b>Back up</b> from the System page before an update or a move. The file holds the settings (with their keys), playlists, timer tasks and calendar sign-ins, never the device password, and is locked with a passphrase of its own (12 characters or more, not the device password), which is kept nowhere: if you lose it the file cannot be opened.</li>
						<li><b>Restore</b> first shows what would change, file by file; nothing is written until you apply it, and nothing is ever deleted. A backup from an older version is brought up to date; one from a newer version is refused.</li>
					</ul>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="wrong">
				<AccordionHeader>When something is wrong</AccordionHeader>
				<AccordionContent>
					<ul>
						<li>The <b>System</b> page says which part did not start, lists the latest problems, and its <b>Activity</b> panel says what each task is doing, in plain words.</li>
						<li>A track that fails shows an error page on the panel with the reason. After <b>Failures Before a Track Stops Running</b> (Settings, System; 3 by default) it is struck out: its slot shows the error page and it is tried again after <b>First Retry of a Struck-Out Track</b> (60 seconds), the wait doubling up to <b>Longest Wait Between Retries</b>. A missing key or a wrong setting strikes it out at once; changing the playlist tries it again. <b>Test</b> buttons on addresses and keys say what is wrong before you save.</li>
						<li>The panel is blank or old? Check the System page's Device card and the Activity panel, then the device's log.</li>
						<li>On a Raspberry Pi, the helper script has <code>update</code> (get the newest version, downloaded: nothing is built on the Pi, and an image GitHub did not sign for that version is not used; on a board with less than 1 GB of memory the app is stopped meanwhile, and the panel keeps its picture), <code>logs</code> and <code>check</code>. An update that is much slower and fills much more of the disk than it should may be Podman keeping images the slow way: <code>check</code> says so, and <code>storage</code> changes it (it asks first, and keeps your data). A Pi follows the <b>stable</b> releases; <code>update --insider</code> follows every change instead, a few minutes after it is made, and <code>update --stable</code> goes back to the releases (it asks first when that is an older version). The header shows this page's version and build, <b>{{ version }} ({{ commit }})</b>; the System page says if the device runs a different build (reload the page after an update).</li>
					</ul>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="more">
				<AccordionHeader>More</AccordionHeader>
				<AccordionContent>
					<ul class="links">
						<li><a href="https://github.com/escape-llc/eink-billboard#readme" target="_blank" rel="noopener noreferrer">Documentation (the readme)</a></li>
						<li><a href="https://github.com/escape-llc/eink-billboard/issues" target="_blank" rel="noopener noreferrer">Report a problem or ask for something</a></li>
						<li><a href="https://github.com/escape-llc/eink-billboard/discussions" target="_blank" rel="noopener noreferrer">Discussions</a></li>
					</ul>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="credits">
				<AccordionHeader>Credits</AccordionHeader>
				<AccordionContent>
					<CreditsList :active="open.includes('credits')" />
				</AccordionContent>
			</AccordionPanel>
		</Accordion>
	</Drawer>
</template>
<script setup lang="ts">
/** The Help drawer: a short guide, opened from the toolbar's help button. It slides out over the page, so the page under it keeps its place. */
import { ref } from "vue"
import { Accordion, AccordionContent, AccordionHeader, AccordionPanel, Drawer } from "primevue"
import CreditsList from "./CreditsList.vue"

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: "update:visible", value: boolean): void }>()
/** the open sections: the credits are asked for when theirs is first opened */
const open = ref<string[]>(["start"])
const version = `v${__APP_VERSION__}`
const commit = __APP_COMMIT__
</script>
<style scoped>
.intro {
	margin: 0 0 .75rem 0;
}
ol, ul {
	margin: 0;
	padding-left: 1.25rem;
	display: flex;
	flex-direction: column;
	gap: .4rem;
}
p {
	margin: 0 0 .5rem 0;
}
dl {
	margin: 0;
	display: flex;
	flex-direction: column;
	gap: .25rem;
}
dt {
	font-weight: bold;
	margin-top: .35rem;
}
dd {
	margin: 0;
	color: var(--p-text-muted-color);
}
code {
	background: var(--p-content-hover-background);
	padding: 0 .25rem;
	border-radius: .25rem;
}
.links a {
	color: var(--p-primary-color);
}
</style>
