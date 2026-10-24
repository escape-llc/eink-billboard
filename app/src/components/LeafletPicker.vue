<template>
	<div class="flex flex-column" style="width:100%;height:100%;overflow:visible">
		<InputGroup class="mb-1">
			<InputGroupAddon>
				<span class="mi mi-public"></span>
			</InputGroupAddon>
			<InputGroupAddon v-if="markerPosition">
				<div>{{ latString(markerPosition[0]) }}, {{ lngString(markerPosition[1]) }}</div>
			</InputGroupAddon>
			<!-- searched on request only: Nominatim's usage policy forbids searching as you type -->
			<InputText
				v-model="searchQuery"
				placeholder="Search for an address..."
				name="searchquery-location"
				aria-label="Address"
				size="small"
				@keydown.enter.prevent="search"
				/>
			<Button
				icon="mi mi-search"
				size="small"
				:loading="searching"
				:disabled="normalQuery(searchQuery).length < MIN_QUERY_LENGTH"
				@click="search"
				aria-label="Search"
				title="Search for the address with OpenStreetMap's Nominatim"
				/>
			<Button
				icon="mi mi-my-location" 
				class="locate-btn" 
				size="small"
				:loading="loadingLocation"
				@click="locateUser"
				aria-label="Locate Me"
				/>
			<Button
				icon="mi mi-wifi"
				size="small"
				:loading="locatingByIp"
				@click="locateByIp"
				aria-label="Locate by IP"
				title="A rough position (about the city) from this device's public IP address. It is looked up with an online service, which sees that address. Nothing is saved until you save the settings."
				/>
		</InputGroup>
		<div v-if="places !== null" class="address-results mb-1" data-testid="address-results">
			<div v-if="places.length === 0" class="address-none">No place found for that address.</div>
			<Button v-for="(place, ix) in places" :key="ix" :label="place.label" text size="small" class="address-place" @click="pick(place)" />
			<!-- the search policy asks for the attribution beside the results -->
			<div class="address-credit">Search by <a href="https://nominatim.org/" target="_blank" rel="noopener">Nominatim</a>, data &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors</div>
		</div>
		<!-- the map is Leaflet's own (made in onMounted, removed before unmount); the tile policy asks for the attribution on the map itself, which the
			tile layer puts there, and the Help drawer's Credits list it too -->
		<div ref="mapElement" class="map" style="flex-grow:1"></div>
	</div>
</template>
<script setup lang="ts">
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import iconRetinaUrl from "leaflet/dist/images/marker-icon-2x.png";
import iconUrl from "leaflet/dist/images/marker-icon.png";
import shadowUrl from "leaflet/dist/images/marker-shadow.png";
import { ref, watch, provide, onMounted, onBeforeUnmount } from 'vue';
import { searchAddress, normalQuery, MIN_QUERY_LENGTH, type Place } from './AddressSearch';
import Button from 'primevue/button';
import { useToast } from 'primevue/usetoast';
import { api } from '../api/client';
import InputGroup from 'primevue/inputgroup';
import InputGroupAddon from 'primevue/inputgroupaddon';
import InputText from 'primevue/inputtext';

// turns off all the form field context stuff since this component doesn't want it.
// This allows it to be used inside forms without interfering with the form context.
// The parent component can still pass the v-slot="$form" to this component and it will work as expected,
// but this component won't provide any form context to its children.
provide("$pcFormField", undefined)

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
// Leaflet finds its marker images by a path a bundler does not keep: name the bundled files
L.Marker.prototype.options.icon = L.icon({ ...L.Icon.Default.prototype.options, iconUrl, iconRetinaUrl, shadowUrl });
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const mapElement = ref<HTMLElement|null>(null);
// Leaflet's objects are not reactive: plain variables, never refs (a proxy around a map breaks it)
let leafletMap: L.Map | null = null;
let marker: L.Marker | null = null;
const zoom = ref<number>(props.zoom);
const markerPosition = ref<Coords|null>(null);
const loadingLocation = ref(false);
const locatingByIp = ref(false);
const toast = useToast();
const searchQuery = ref<string|undefined>(undefined);
/** The places the last search found; null: no search shown. */
const places = ref<Place[]|null>(null);
const searching = ref(false);

function latString(lat: number): string {
	return (lat >= 0 ? lat.toFixed(4) + "N" : (-lat).toFixed(4) + "S");
}
function lngString(lng: number): string {
	return (lng >= 0 ? lng.toFixed(4) + "E" : (-lng).toFixed(4) + "W");
}

watch(() => props.modelValue, (newLocation) => {
	if (newLocation) {
		const newCoords: Coords = [newLocation.latitude, newLocation.longitude];
		markerPosition.value = newCoords;
		if (leafletMap) {
			leafletMap.setView(newCoords, zoom.value);
		}
	}
}, { immediate: true });

/** Search for the typed address (the Search button, or Enter); a press while a search runs is ignored. */
const search = async () => {
	if (searching.value || normalQuery(searchQuery.value).length < MIN_QUERY_LENGTH) return;
	searching.value = true;
	try {
		const found = await searchAddress(searchQuery.value);
		if (found !== null) places.value = found;
	}
	catch (ex: any) {
		console.warn("Address search failed", ex);
		toast.add({ severity: "warn", summary: "Location", detail: "The address search did not answer. Try again, or click the map.", life: 8000 });
	}
	finally {
		searching.value = false;
	}
};

const pick = (place: Place) => {
	places.value = null;
	updateLocation(place.latitude, place.longitude, true);
};

onMounted(() => {
	if (!mapElement.value) return;
	const map = L.map(mapElement.value, { zoomControl: true });
	L.tileLayer(TILES, { attribution: ATTRIBUTION }).addTo(map);
	map.setView(markerPosition.value || [45, 80], zoom.value);
	map.on("click", onMapClick);
	map.on("zoomend", () => { zoom.value = map.getZoom(); });
	leafletMap = map;
	showMarker();
});
onBeforeUnmount(() => {
	leafletMap?.remove();
	leafletMap = null;
	marker = null;
});
/** The marker where the position is (draggable), none while there is no position. */
function showMarker() {
	const map = leafletMap;
	if (!map) return;
	const at = markerPosition.value;
	if (!at) {
		marker?.remove();
		marker = null;
		return;
	}
	if (marker) {
		marker.setLatLng(at);
		return;
	}
	marker = L.marker(at, { draggable: true }).addTo(map);
	marker.on("dragend", onMarkerDrag);
}
watch(markerPosition, showMarker);

const updateLocation = (lat: number, lng: number, shouldMoveMap: boolean = false) => {
  const newCoords: Coords = [lat, lng];
  markerPosition.value = newCoords;
	if (shouldMoveMap && leafletMap) {
		leafletMap.flyTo(newCoords, zoom.value);
	}
	const mv = { latitude: lat, longitude: lng }
  emit('update:modelValue', mv);
  emit('change', { value: mv });
};

function onMapClick(event: L.LeafletMouseEvent) {
	const { lat, lng } = event.latlng;
	updateLocation(lat, lng);
}

function onMarkerDrag(event: L.DragEndEvent) {
	const { lat, lng } = (event.target as L.Marker).getLatLng();
	updateLocation(lat, lng);
}
const locateUser = () => {
	if (!navigator.geolocation) return;

	loadingLocation.value = true;
	navigator.geolocation.getCurrentPosition(
		(position) => {
			const { latitude, longitude } = position.coords;
			zoom.value = 16;
			updateLocation(latitude, longitude, true);
			loadingLocation.value = false;
		},
		(error) => {
			console.error("Geolocation error:", error);
			loadingLocation.value = false;
		},
		{ enableHighAccuracy: true }
	);
};

/** A rough position from the device's public IP (POST /api/system/locate): it fills the field and moves the map, and saves nothing; the person keeps it or not. */
const locateByIp = async () => {
	locatingByIp.value = true;
	try {
		const answer = await api.post("/api/system/locate", {}, undefined);
		if (answer.ok && answer.latitude != null && answer.longitude != null) {
			zoom.value = 10;
			updateLocation(answer.latitude, answer.longitude, true);
			toast.add({ severity: "info", summary: "Location", detail: answer.message, life: 8000 });
		}
		else {
			toast.add({ severity: "warn", summary: "Location", detail: answer.message, life: 8000 });
		}
	}
	catch (ex: any) {
		toast.add({ severity: "error", summary: "Location", detail: ex?.message || "The location could not be looked up.", life: 8000 });
	}
	finally {
		locatingByIp.value = false;
	}
};
</script>
<style scoped>
.map {
	min-height: 0;
}
.address-results {
	display: flex;
	flex-direction: column;
	align-items: flex-start;
	max-height: 12rem;
	overflow-y: auto;
	border: 1px solid var(--p-content-border-color);
	border-radius: var(--p-content-border-radius);
	background: var(--p-content-background);
	padding: 0.25rem;
}
.address-place {
	text-align: left;
	justify-content: flex-start;
}
.address-none, .address-credit {
	color: var(--p-text-muted-color);
	font-size: 0.75rem;
	padding: 0.25rem 0.5rem;
}
</style>