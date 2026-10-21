<template>
	<Drawer :visible="visible" position="right" header="Help" class="help-drawer" style="width:min(30rem, 95vw)" data-testid="help"
		@update:visible="(v: boolean) => emit('update:visible', v)">
		<p class="intro">
			eInk Billboard shows pictures and pages on an e-Ink panel. You say <b>what</b> to show and <b>when</b>; the device does the rest, by itself, all day.
		</p>

		<Accordion :value="['start']" multiple>
			<AccordionPanel value="start">
				<AccordionHeader>First steps</AccordionHeader>
				<AccordionContent>
					<ol>
						<li><b>Settings, System:</b> set the device's <b>Location</b> and time zone. Weather, maps and the clock use them. The <i class="pi pi-wifi" aria-hidden="true"></i> button beside the map finds a rough position from the device's internet address; nothing is saved until you press Save.</li>
						<li><b>Settings, Display:</b> choose the panel you have, and its orientation.</li>
						<li><b>Playlist:</b> make a playlist and add <b>tracks</b>. A track is one page or picture and how long it stays. Save the playlist: nothing reaches the panel until it is saved.</li>
						<li>If a track needs a key (weather, maps, comics, AI pictures), add it under <b>Settings, Data Sources</b>. Each key has a <b>Test</b> button and a link to where you get one.</li>
					</ol>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="pages">
				<AccordionHeader>The pages</AccordionHeader>
				<AccordionContent>
					<dl>
						<dt><i class="pi pi-clock" aria-hidden="true"></i> Schedule</dt>
						<dd>Timer tasks: things that happen at a time of day, such as a priority message for ten minutes at 8:00, or an overlay (the date, the weather) drawn over the picture. Shown as a day, a week or a list.</dd>
						<dt><i class="pi pi-play" aria-hidden="true"></i> Playlist</dt>
						<dd>The tracks that play one after another, round and round. You can keep several playlists.</dd>
						<dt><i class="pi pi-desktop" aria-hidden="true"></i> System</dt>
						<dd>How the device is: whether its parts started and the latest problems, the machine (load, memory, how long it and the app have been up), a Raspberry Pi's temperature and power warnings, the storage by plugin and data source, and the <b>API usage</b> of each service. On the right, live: <b>Now showing</b> (what the panel shows, with the layers it is made of; click for full size), <b>Recently shown</b> and <b>Activity</b> (filter it by source, or show only problems). The toolbar has play, stop and next, and Back up, Restore and the device password.</dd>
						<dt><i class="pi pi-globe" aria-hidden="true"></i> Settings</dt>
						<dd>The device (System, Display, Theme, Devices such as buttons) and the plugins and data sources, each with its own settings and keys.</dd>
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
					<p>Some sources need a key from their service: OpenWeatherMap, Comic Vine, Thunderforest (maps), OpenAI and Google (generated pictures). Most have a free plan; generated pictures are paid by use. Keys are kept on the device, are never shown again (a field shows only stars), and are sent only to their own service.</p>
					<p>Downloads are kept for a while (see each data source's <b>Keep</b> settings), so a free plan's quota goes a long way. The System page shows how much each source keeps, and under <b>API usage</b> how many calls each service has been asked for (today, this week, this month), how many failed, and how much the cache spared. Check it against your plan's quota.</p>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="weather">
				<AccordionHeader>Weather</AccordionHeader>
				<AccordionContent>
					<p>The weather at the device's <b>Location</b> (Settings, System), from OpenWeatherMap: the weather <b>now</b>, the next day in three-hour steps (<b>hours</b>) and the next five <b>days</b>, one page per view chosen.</p>
					<ul>
						<li>The key, the units and how long answers are kept are in <b>Settings, Data Sources, OpenWeatherMap</b>, shared by the Weather pages and the Weather Overlay. A free key will do; a new one can take a couple of hours to start working, and until then the page says the key was refused.</li>
						<li>Units <b>auto</b> means miles and Fahrenheit in US time zones, kilometres and Celsius elsewhere. The clock follows the System settings' time format.</li>
					</ul>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="calendar">
				<AccordionHeader>Calendars</AccordionHeader>
				<AccordionContent>
					<p>The calendars are listed in <b>Settings, Data Sources, Calendar</b>; a track or overlay chooses which to show (none chosen: all that are enabled) and its views: the <b>month</b>, the coming <b>weeks</b> as continuous rows, an <b>agenda</b> of the coming days.</p>
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

			<AccordionPanel value="ai">
				<AccordionHeader>Generated pictures</AccordionHeader>
				<AccordionContent>
					<p>A <b>Generated Image</b> is drawn by an AI model from your prompt, which a text model can rewrite first so no two are alike. Its <b>Image Source</b> draws and its <b>Text Source</b> rewrites; each is OpenAI's or Google's, and they can be mixed. Each part's own fields (model, quality) show under it.</p>
					<ul>
						<li>The keys are under <b>Settings, Data Sources</b>, OpenAI or Google AI; <b>Test</b> says which models the key may use. A Google key is a Google AI Studio key starting with <code>AQ.</code>.</li>
						<li>The newest models draw in the panel's shape; what does not fill the panel gets a blurred margin. Pictures are paid by use: see API usage on the System page.</li>
					</ul>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="safe">
				<AccordionHeader>Keeping it safe</AccordionHeader>
				<AccordionContent>
					<ul>
						<li>A new device asks for a <b>setup code</b> (in its log and on the panel) and then your own password. Change it from the System page's <i class="pi pi-key" aria-hidden="true"></i> button.</li>
						<li><b>Back up</b> from the System page before an update or a move. The file is locked with a passphrase you choose, which is kept nowhere: if you lose it the file cannot be opened.</li>
					</ul>
				</AccordionContent>
			</AccordionPanel>

			<AccordionPanel value="wrong">
				<AccordionHeader>When something is wrong</AccordionHeader>
				<AccordionContent>
					<ul>
						<li>The <b>System</b> page says which part did not start, lists the latest problems, and its <b>Activity</b> panel says what each task is doing, in plain words.</li>
						<li>A track that fails shows an error page on the panel with the reason, and is tried again later. <b>Test</b> buttons on addresses and keys say what is wrong before you save.</li>
						<li>The panel is blank or old? Check the System page's Device card and the Activity panel, then the device's log.</li>
						<li>On a Raspberry Pi, the helper script has <code>update</code> (get the newest version), <code>logs</code> and <code>check</code>. The header shows this page's version and build, <b>{{ version }} ({{ commit }})</b>; the System page says if the device runs a different build (reload the page after an update).</li>
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
		</Accordion>
	</Drawer>
</template>
<script setup lang="ts">
/** The Help drawer: a short guide, opened from the toolbar's help button. It slides out over the page, so the page under it keeps its place. */
import { Accordion, AccordionContent, AccordionHeader, AccordionPanel, Drawer } from "primevue"

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: "update:visible", value: boolean): void }>()
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
