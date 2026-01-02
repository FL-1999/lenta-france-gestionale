(() => {
  const DEFAULT_CENTER = { lat: 46.2276, lng: 2.2137 };
  const DEFAULT_ZOOM = 6;
  const FOCUSED_ZOOM = 15;

  const parseCoordinate = (value) => {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const updateLatLngInputs = (latInput, lngInput, lat, lng) => {
    latInput.value = lat;
    lngInput.value = lng;
  };

  const hideMarker = (marker) => {
    if (marker) {
      marker.setVisible(false);
    }
  };

  const showMarkerAt = (marker, position) => {
    marker.setPosition(position);
    marker.setVisible(true);
  };

  window.initCantiereFormMap = function initCantiereFormMap() {
    const addressInput = document.getElementById("cantiere_address");
    const placeIdInput = document.getElementById("cantiere_place_id");
    const latInput = document.getElementById("cantiere_lat");
    const lngInput = document.getElementById("cantiere_lng");
    const mapElement = document.getElementById("cantiere-pick-map");

    if (!addressInput || !placeIdInput || !latInput || !lngInput || !mapElement) {
      return;
    }

    if (!window.google || !window.google.maps) {
      return;
    }

    const latValue = parseCoordinate(latInput.value);
    const lngValue = parseCoordinate(lngInput.value);
    const hasCoordinates = latValue !== null && lngValue !== null;
    const initialCenter = hasCoordinates
      ? { lat: latValue, lng: lngValue }
      : DEFAULT_CENTER;

    const map = new window.google.maps.Map(mapElement, {
      center: initialCenter,
      zoom: hasCoordinates ? FOCUSED_ZOOM : DEFAULT_ZOOM,
      mapTypeControl: false,
      streetViewControl: false,
    });

    const marker = new window.google.maps.Marker({
      map,
      position: hasCoordinates ? initialCenter : null,
      draggable: true,
      visible: hasCoordinates,
    });

    const setPosition = (lat, lng, shouldCenter = true) => {
      const position = { lat, lng };
      showMarkerAt(marker, position);
      updateLatLngInputs(latInput, lngInput, lat, lng);
      if (shouldCenter) {
        map.setCenter(position);
      }
    };

    map.addListener("click", (event) => {
      if (!event || !event.latLng) {
        return;
      }
      placeIdInput.value = "";
      setPosition(event.latLng.lat(), event.latLng.lng(), false);
    });

    marker.addListener("dragend", (event) => {
      if (!event || !event.latLng) {
        return;
      }
      placeIdInput.value = "";
      setPosition(event.latLng.lat(), event.latLng.lng(), false);
    });

    const autocomplete = new window.google.maps.places.Autocomplete(addressInput, {
      fields: ["place_id", "geometry", "formatted_address"],
    });

    let lastSelectedAddress = addressInput.value || "";
    let ignoreInputEvent = false;

    autocomplete.addListener("place_changed", () => {
      const place = autocomplete.getPlace();
      if (!place || !place.geometry || !place.geometry.location) {
        return;
      }

      const formattedAddress = place.formatted_address || addressInput.value;
      ignoreInputEvent = true;
      addressInput.value = formattedAddress;
      lastSelectedAddress = formattedAddress;
      placeIdInput.value = place.place_id || "";

      setPosition(place.geometry.location.lat(), place.geometry.location.lng(), true);
      map.setZoom(FOCUSED_ZOOM);

      window.setTimeout(() => {
        ignoreInputEvent = false;
      }, 0);
    });

    addressInput.addEventListener("keyup", () => {
      if (ignoreInputEvent) {
        return;
      }
      if (addressInput.value !== lastSelectedAddress) {
        lastSelectedAddress = addressInput.value;
        placeIdInput.value = "";
        latInput.value = "";
        lngInput.value = "";
        hideMarker(marker);
      }
    });
  };
})();
