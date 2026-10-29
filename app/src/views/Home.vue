<template>
	<!-- the panel at a glance (#824): what the device did last, then what the panel shows and plays, as on the System page without its Activity -->
	<div class="home">
		<div class="home-body">
			<LatestActivity />
			<PanelNow :activity="false" />
		</div>
	</div>
</template>
<script setup lang="ts">
/** Home: what is on the panel and what to do about it. How the device is, and everything it reported, is on the System page. */
import LatestActivity from "../components/LatestActivity.vue"
import PanelNow from "../components/PanelNow.vue"
</script>
<style scoped>
/* the page fills the frame; its cards keep a readable width in the middle */
.home-body {
	display: flex;
	flex-direction: column;
	gap: .75rem;
	padding: .5rem;
	width: 100%;
	max-width: 48rem;
	margin: 0 auto;
	box-sizing: border-box;
}
</style>
