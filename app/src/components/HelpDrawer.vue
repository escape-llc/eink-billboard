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
						<dd>How the device is: its parts, the machine, a Raspberry Pi's temperature and power warnings, the disk, what the panel shows now and the activity log. The toolbar has play, stop and next, and Back up, Restore and the device password.</dd>
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
					<p>Downloads are kept for a while (see each data source's <b>Keep</b> settings), so a free plan's quota goes a long way. The System page shows how much each source keeps.</p>
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
