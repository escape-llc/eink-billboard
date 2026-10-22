<script setup lang="ts">
import { InputGroup, Toast, TieredMenu, Button, Toolbar, ConfirmDialog } from 'primevue';
import { RouterLink, RouterView } from 'vue-router'
import ThemeSelector from './components/ThemeSelector.vue'
import AuthDialog from './components/AuthDialog.vue'
import HelpDrawer from './components/HelpDrawer.vue'
import { onMounted, ref, watch } from 'vue';
import { useToast } from 'primevue/usetoast';
import { signInCount } from './components/ApiClient'
import { justSignedIn, reloadAfterSignIn } from './components/SignedIn'
const toast = useToast()
// a sign-in loads the whole page again (the newest build, everything read anew): see SignedIn.ts
watch(signInCount, () => reloadAfterSignIn())
onMounted(() => {
	if (justSignedIn()) {
		// it may look the same, so say that it read everything anew
		toast.add({ severity: 'success', summary: 'Signed in', detail: 'The page was reloaded with the latest data.', life: 4000 })
	}
})
const menu = ref<InstanceType<typeof TieredMenu>|null>(null)
const toggleMenu = (event:MouseEvent):void => {
	menu.value?.toggle(event);
}
const version = ref(__APP_VERSION__)
// the commit this bundle was built from: a page that runs an old build says so here (and the System page compares it with the server's)
const commit = __APP_COMMIT__
// the Help drawer slides out from the right
const helpOpen = ref(false)
const items = ref([
		{
			label:"Schedule",
			icon: "pi pi-clock",
			class: "p-0 m-0",
//			disabled: () => appStore.currentStateAppConfig !== "initialized",
			to: "/schedule",
		},
		{
			label:"Playlist",
			icon: "pi pi-play",
			class: "p-0 m-0",
//			disabled: () => appStore.currentStateAppConfig !== "initialized",
			to: "/playlist",
		},
		{
			label:"System",
			icon: "pi pi-desktop",
			class: "p-0 m-0",
			to: "/system",
		},
		{
			label:"Settings",
			icon: "pi pi-globe",
			class: "p-0 m-0",
//			disabled: () => appStore.currentStateAppConfig !== "initialized",
			to: "/settings",
		},
		{
			label:"Credits",
			icon: "pi pi-heart",
			class: "p-0 m-0",
			to: "/credits",
		},
	]
)
</script>
<template>
	<Toolbar
		class="py-1 px-1 flex items-center justify-center"
	>
	<template #start>
		<div class="flex flex-row" style="flex-grow:1;align-items:center">
		<InputGroup>
			<Button
				v-if="items.length !== 0"
				icon="pi pi-bars"
				size="small"
				class="p-button-outlined"
				type="button"
				aria-haspopup="true"
				aria-controls="overlay_tmenu"
				@click="toggleMenu($event)"
				/>
			<TieredMenu
				id="overlay_tmenu"
				ref="menu"
				:model="items"
				:popup="true"
				style="font-weight:bold">
				<template #item="{ item, props, hasSubmenu }">
					<router-link
						v-if="item.to"
						v-slot="{ href, navigate }"
						:to="item.to"
						custom
					>
							<a
								:href="href"
								v-bind="props.action"
								@click="navigate"
							>
									<span :class="item.icon" />
									<span class="ml-2">{{ item.label }}</span>
							</a>
					</router-link>
					<a
						v-else
						:href="item.url"
						:target="item.target"
						v-bind="props.action"
					>
							<span :class="item.icon" />
							<span class="ml-2">{{ item.label }}</span>
							<span v-if="hasSubmenu" class="pi pi-angle-right ml-auto" />
					</a>
				</template>
			</TieredMenu>
			<!--
			<template v-if="appStore.currentProject !== null">
				<InputGroupAddon>
					<div style="font-weight: bold;font-size: 110%">{{ appStore.currentProject.project.name }}</div>
				</InputGroupAddon>
				<template v-if="openMode === 'open'">
					<Button size="small" icon="pi pi-video" @click="handleAnnotate" />
					<Button size="small" icon="pi pi-database" @click="handleDatabase" />
				</template>
			</template>
			-->
		</InputGroup>
		<!-- one line, whatever the width: the name and the build do not wrap or stack -->
		<div class="flex flex-row p-0 m-0 pl-2" style="flex-grow:1;flex-wrap:nowrap;gap:.5rem;white-space:nowrap">
			<h2
			class="m-0"
			style="font-size:100%;align-self:baseline;flex:none">eInk Billboard</h2>
			<span
			class="ml-0"
			style="align-self:baseline;flex:none" :title="`Web app build ${commit}`" data-testid="app-version">v{{version}} ({{commit}})</span>
		</div>
		</div>
	</template>
	<template #center>
		<!--
		<Tag v-if="appStore.currentStateAppConfig !== 'initialized'" class="ml-2" severity="warn" value="Setup Required" title="Setup Required" />
		-->
	</template>
	<template #end>
		<InputGroup>
			<ThemeSelector class="p-button-sm"/>
			<Button size="small"
				icon="pi pi-question-circle"
				class="p-button-sm p-button-outlined"
				type="button"
				aria-label="Help"
				title="Help"
				data-testid="help-button"
				@click="helpOpen = true"
				/>
			</InputGroup>
	</template>
	</Toolbar>
	<div class="main-area">
		<RouterView class="router-view" />
	</div>
	<ConfirmDialog></ConfirmDialog>
	<AuthDialog />
	<HelpDrawer v-model:visible="helpOpen" />
	<Toast position="bottom-left"/>
</template>
<style scoped>
.main-area {
	display: flex;
	/* what is left of the window under the toolbar: the page scrolls inside it, instead of growing past the window (the body does not scroll) */
	flex: 1 1 0;
	gap: .5rem;
	min-height: 0;
}
.router-view {
	flex-grow: 1;
	min-width: 0;
	min-height: 0;
	overflow: auto;
	border-radius: var(--p-toolbar-border-radius);
	border: solid 1px var(--p-toolbar-border-color)
}
@media (max-width: 768px) {
	.main-area {
		flex-direction: column;
	}
}
</style>
<style>
:root {
	--main-toolbar-height: 2.5rem;
}
/* a view is taller than the window when its content is: its parts keep their size and the page area scrolls (they must not shrink to fit, which squeezed the tab strip to nothing) */
.router-view > * {
	flex-shrink: 0;
}
</style>
