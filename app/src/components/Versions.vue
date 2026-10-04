<script setup lang="ts">
const appversion = __APP_VERSION__;
</script>

<template>
	<ul class="versions">
		<li class="app-version">Web App v{{ appversion }}</li>
		<!--
		<li class="electron-version">Electron v{{ versions.electron }}</li>
		<li class="chrome-version">Chromium v{{ versions.chrome }}</li>
		<li class="node-version">Node v{{ versions.node }}</li>
		-->
	</ul>
</template>
