<template>
	<div class="flex flex-column" style="width:100%;height:100%;overflow:visible">
		<InputGroup class="mb-1">
			<InputGroupAddon>
				<span class="pi pi-globe"></span>
			</InputGroupAddon>
			<InputGroupAddon v-if="markerPosition">
				<div>{{ latString(markerPosition[0]) }}, {{ lngString(markerPosition[1]) }}</div>
			</InputGroupAddon>
			 <AutoComplete
					v-model="searchQuery"
					:suggestions="suggestions"
					optionLabel="label"
					placeholder="Search for an address..."
					name="searchquery-location"
					size="small"
					@complete="handleSearch"
					@item-select="onSelectLocation"
				/>
			<Button 
				icon="pi pi-map-marker" 
				class="locate-btn" 
				size="small"
				:loading="loadingLocation"
				@click="locateUser"
				aria-label="Locate Me"
				/>
		</InputGroup>
		<l-map 
			style="flex-grow:1"
			v-model:zoom="zoom"
			@click="onMapClick"
			@ready="onMapReady"
			:use-global-leaflet="false"
		>
			<l-tile-layer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" layer-type="base" name="OpenStreetMap"></l-tile-layer>
			<l-marker :lat-lng="markerPosition" draggable @dragend="onMarkerDrag" />
		</l-map>
	</div>
</template>
<script setup lang="ts">
import "leaflet/dist/leaflet.css";
import { ref, watch, nextTick, inject } from 'vue';
import { LMap, LTileLayer, LMarker } from "@vue-leaflet/vue-leaflet";
import { OpenStreetMapProvider } from 'leaflet-geosearch';
import Button from 'primevue/button';
import InputGroup from 'primevue/inputgroup';
import InputGroupAddon from 'primevue/inputgroupaddon';
import AutoComplete from 'primevue/autocomplete';

const formField = inject('pcFormField', null);

type LatLng = { latitude: number; longitude: number; };
interface Props {
  modelValue?: LatLng;
  zoom?: number;
	name?: string;
}
type Coords = [number, number]
const props = withDefaults(defineProps<Props>(), {
  zoom: 13
});
const emit = defineEmits<{
	(e: 'update:modelValue', coordinates: LatLng): void;
	(e: 'change', event: { value: LatLng }): void;
}>();
const leafletMap = ref<any>(null);
const zoom = ref<number>(props.zoom);
const center = ref<Coords|null>(null);
const markerPosition = ref<Coords|null>(null);
const loadingLocation = ref(false);
const searchQuery = ref<string|undefined>(undefined);
const suggestions = ref<any[]>([]);

function latString(lat: number): string {
	return (lat >= 0 ? lat.toFixed(4) + "N" : (-lat).toFixed(4) + "S");
}
function lngString(lng: number): string {
	return (lng >= 0 ? lng.toFixed(4) + "E" : (-lng).toFixed(4) + "W");
}

watch(() => props.modelValue, (newLocation) => {
	if (newLocation) {
		const newCoords: Coords = [newLocation.latitude, newLocation.longitude];
		center.value = newCoords;
		markerPosition.value = newCoords;
	}
}, { immediate: true });

const provider = new OpenStreetMapProvider();

const handleSearch = async (event: { query: string }) => {
  if (event.query.length < 3) return;
  // Use the provider manually to get results
  const results = await provider.search({ query: event.query });
	console.log("Search results:", event.query, results);
  suggestions.value = results;
};

const onSelectLocation = (event: any) => {
	console.log('Selected location:', event);
  const { y: lat, x: lng } = event.value;
  updateLocation(lat, lng, true);
};

const onMapReady = (mapInstance: any) => {
	leafletMap.value = mapInstance; // Store the map instance for programmatic moves


	mapInstance.setView(center.value, zoom.value);
	if (leafletMap.value && markerPosition.value) {
		leafletMap.value.flyTo(markerPosition.value, zoom.value);
	}
	mapInstance.on('geosearch/showlocation', (result: any) => {
	const { y: lat, x: lng } = result.location;
		updateLocation(lat, lng, true); // Move map to search result
	});
	nextTick(() => {
		setTimeout(() => mapInstance.invalidateSize(), 100);
	});
};

const updateLocation = (lat: number, lng: number, shouldMoveMap: boolean = false) => {
  const newCoords: Coords = [lat, lng];
  markerPosition.value = newCoords;
	if (shouldMoveMap && leafletMap.value) {
		leafletMap.value.flyTo(newCoords, zoom.value);
	}
	const mv = { latitude: lat, longitude: lng }
  emit('update:modelValue', mv);
  emit('change', { value: mv });
	nextTick(() => {
		formField?.onFieldChange(mv);
	});
};

const onMapClick = (event: any) => {
	// Leaflet events provide latlng in an object
	console.log("onMapClick", event);
	const { lat, lng } = event.latlng;
	updateLocation(lat, lng);
};

const onMarkerDrag = (event: any) => {
	const { lat, lng } = event.target.getLatLng();
	updateLocation(lat, lng);
};
const locateUser = () => {
	if (!navigator.geolocation) return;

	loadingLocation.value = true;
	navigator.geolocation.getCurrentPosition(
		(position) => {
			const { latitude, longitude } = position.coords;
			updateLocation(latitude, longitude, true);
//			center.value = [latitude, longitude];
			zoom.value = 16;
			loadingLocation.value = false;
		},
		(error) => {
			console.error("Geolocation error:", error);
			loadingLocation.value = false;
		},
		{ enableHighAccuracy: true }
	);
};
</script>
<style scoped>
</style>