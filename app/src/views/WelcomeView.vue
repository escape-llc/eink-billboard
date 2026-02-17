<script setup lang="ts">
import xxx from '../assets/logo.svg'
import yyy from '../assets/btn_donateCC_LG.gif'
import Versions from '../components/Versions.vue'
</script>
<template>
	<div class="welcome-view">
		<h3 class="text-3xl mb-0">Welcome to eInk Billboard!</h3>
		<img class="logo" :src="xxx"/>
		<a class="text-3xl mb-1" href="https://escape-technology-llc.visualstudio.com/Media%20Lab/_wiki/wikis/Media-Lab.wiki/1/Home">Online Help</a>
		<a class="text-3xl mb-1" href="https://escape-technology-llc.com/mobile/index.php/category/medialab/" >Blog</a>
		<a class="mt-2" href="https://www.paypal.com/donate/?hosted_button_id=G8P9TW4QT6C3U">
			<img class="pp" :src="yyy"/>
		</a>
		<Versions class="mt-2" />
	</div>
</template>
<style scoped>
.welcome-view {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-items: center;
}
.logo {
	max-height: 20rem;
}
.pp {
	max-width: 50rem;
}
</style>