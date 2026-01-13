(() => {
  const DEFAULT_CENTER = { lat: 43.7, lng: 7.27 };
  const DEFAULT_ZOOM = 12;
  const FOCUSED_ZOOM = 15;

  let mapInstance = null;
  let markerInstance = null;
  let mapCenter = DEFAULT_CENTER;

  const parseCoordinate = (value) => {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const updateLatLngInputs = (latInput, lngInput, lat, lng) => {
    if (latInput) {
      latInput.value = lat;
    }
    if (lngInput) {
      lngInput.value = lng;
    }
  };

  const setMarkerPosition = (marker, position, map, shouldCenter) => {
    marker.setPosition(position);
    if (shouldCenter && map) {
      map.setCenter(position);
    }
  };

  const initMap = () => {
    const mapElement = document.getElementById("cantiere-pick-map");
    if (!mapElement) {
      return;
    }

    const addressInput = document.getElementById("cantiere-address");
    const latInput = document.getElementById("lat");
    const lngInput = document.getElementById("lng");
    if (!latInput || !lngInput) {
      return;
    }

    if (!window.google || !window.google.maps) {
      return;
    }

    if (mapElement.dataset.mapInitialized === "true") {
      return;
    }

    const latValue = parseCoordinate(latInput.value);
    const lngValue = parseCoordinate(lngInput.value);
    const hasCoordinates = latValue !== null && lngValue !== null;

    const center = hasCoordinates
      ? { lat: latValue, lng: lngValue }
      : DEFAULT_CENTER;

    const map = new window.google.maps.Map(mapElement, {
      center,
      zoom: hasCoordinates ? FOCUSED_ZOOM : DEFAULT_ZOOM,
      mapTypeControl: false,
      streetViewControl: false,
    });

    const marker = new window.google.maps.Marker({
      map,
      position: center,
      draggable: true,
    });

    const updatePosition = (lat, lng, shouldCenter = true) => {
      const position = { lat, lng };
      setMarkerPosition(marker, position, map, shouldCenter);
      updateLatLngInputs(latInput, lngInput, lat, lng);
      mapCenter = position;
    };

    map.addListener("click", (event) => {
      if (!event || !event.latLng) {
        return;
      }
      updatePosition(event.latLng.lat(), event.latLng.lng(), false);
    });

    marker.addListener("dragend", (event) => {
      if (!event || !event.latLng) {
        return;
      }
      updatePosition(event.latLng.lat(), event.latLng.lng(), false);
    });

    map.addListener("idle", () => {
      const currentCenter = map.getCenter();
      if (currentCenter) {
        mapCenter = { lat: currentCenter.lat(), lng: currentCenter.lng() };
      }
    });

    if (addressInput) {
      addressInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
        }
      });
    }

    if (addressInput && window.google.maps.places) {
      const autocomplete = new window.google.maps.places.Autocomplete(addressInput, {
        types: ["geocode"],
      });

      autocomplete.addListener("place_changed", () => {
        const place = autocomplete.getPlace();
        if (!place.geometry || !place.geometry.location) {
          return;
        }

        const location = place.geometry.location;
        map.setCenter(location);
        map.setZoom(17);
        marker.setPosition(location);

        updateLatLngInputs(latInput, lngInput, location.lat(), location.lng());
      });
    }

    mapInstance = map;
    markerInstance = marker;
    mapCenter = center;
    mapElement.dataset.mapInitialized = "true";
  };

  window.initMap = initMap;

  window.refreshCantiereFormMap = function refreshCantiereFormMap() {
    if (!mapInstance || !window.google || !window.google.maps) {
      return;
    }
    window.google.maps.event.trigger(mapInstance, "resize");
    if (markerInstance && markerInstance.getPosition()) {
      mapInstance.setCenter(markerInstance.getPosition());
    } else if (mapCenter) {
      mapInstance.setCenter(mapCenter);
    }
  };
})();
