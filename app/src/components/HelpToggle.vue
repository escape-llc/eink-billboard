<template>
	<!-- the help under a form's fields is long for some forms: this hides it once it is known (BasicForm's `showHelp`); it goes in the header's group, before apply and reset -->
	<Button size="small" icon="pi pi-question-circle" severity="secondary" :variant="model ? undefined : 'outlined'" :aria-pressed="model"
		aria-label="Help text" :title="model ? 'Hide the help under the fields' : 'Show the help under the fields'" @click="model = !model" />
</template>
<script setup lang="ts">
import { Button } from "primevue"
// for the page's life only: the browser stores nothing but the theme
const model = defineModel<boolean>({ default: true })
</script>
