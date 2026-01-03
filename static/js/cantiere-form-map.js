(() => {
  const DEFAULT_CENTER = { lat: 46.2276, lng: 2.2137 };
  const DEFAULT_ZOOM = 6;
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
    latInput.value = lat;
    lngInput.value = lng;
  };

  const isCoordinateSet = (value) => parseCoordinate(value) !== null;

  const GUIDE_MESSAGE =
    "Seleziona un indirizzo dai suggerimenti o clicca sulla mappa per impostare la posizione.";

  const setVerificationStatus = (
    statusElement,
    alertElement,
    confirmWrapper,
    confirmCheckbox,
    isVerified,
    alertMessage = "",
    showGuide = true
  ) => {
    if (statusElement) {
      statusElement.textContent = isVerified ? "Verificato ✅" : "Non verificato ⚠️";
      statusElement.classList.toggle("badge-success", isVerified);
      statusElement.classList.toggle("badge-danger", !isVerified);
    }
    if (alertElement) {
      const message =
        showGuide && !isVerified ? alertMessage || GUIDE_MESSAGE : alertMessage || "";
      alertElement.textContent = message;
      alertElement.style.display = message ? "block" : "none";
    }
    if (confirmWrapper && confirmCheckbox) {
      if (isVerified) {
        confirmWrapper.style.display = "none";
        confirmCheckbox.checked = false;
      }
    }
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

  const showFallback = (mapElement) => {
    if (!mapElement || mapElement.dataset.mapInitialized === "true") {
      return;
    }
    mapElement.dataset.mapFallback = "true";
    mapElement.classList.add("map-disabled-message");
    mapElement.textContent =
      "Mappa non disponibile. Inserisci l’indirizzo e salva: potrai completare la posizione più tardi.";
  };

  window.initCantiereFormMap = function initCantiereFormMap() {
    const addressInput = document.getElementById("cantiere_address");
    const placeIdInput = document.getElementById("cantiere_place_id");
    const latInput = document.getElementById("cantiere_lat");
    const lngInput = document.getElementById("cantiere_lng");
    const mapElement = document.getElementById("cantiere-pick-map");
    const geocodeButton = document.getElementById("btn-geocode-address");

    const statusElement = document.getElementById("cantiere-address-status");
    const alertElement = document.getElementById("cantiere-address-alert");
    const confirmWrapper = document.getElementById("cantiere-unverified-confirm-wrapper");
    const confirmCheckbox = document.getElementById("cantiere-unverified-confirm");
    const form = addressInput ? addressInput.closest("form") : null;
    const isEditMode = form && form.dataset.mode === "edit";

    if (!addressInput || !placeIdInput || !latInput || !lngInput || !mapElement) {
      return;
    }

    if (!window.google || !window.google.maps) {
      showFallback(mapElement);
      return;
    }

    if (mapElement.dataset.mapFallback === "true") {
      mapElement.classList.remove("map-disabled-message");
      mapElement.textContent = "";
      delete mapElement.dataset.mapFallback;
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
    mapInstance = map;
    markerInstance = marker;
    mapCenter = initialCenter;
    mapElement.dataset.mapInitialized = "true";
    setVerificationStatus(
      statusElement,
      alertElement,
      confirmWrapper,
      confirmCheckbox,
      hasCoordinates,
      "",
      addressInput.value.trim() !== ""
    );


    const setPosition = (lat, lng, shouldCenter = true) => {
      const position = { lat, lng };
      showMarkerAt(marker, position);
      updateLatLngInputs(latInput, lngInput, lat, lng);
      setVerificationStatus(statusElement, alertElement, confirmWrapper, confirmCheckbox, true);
      if (shouldCenter) {
        map.setCenter(position);
      }
      mapCenter = position;
    };

    map.addListener("click", (event) => {
      if (!event || !event.latLng) {
        return;
      }
      placeIdInput.value = "";
      setPosition(event.latLng.lat(), event.latLng.lng(), false);
      if (confirmWrapper && confirmCheckbox) {
        confirmWrapper.style.display = "none";
        confirmCheckbox.checked = false;
      }
    });

    marker.addListener("dragend", (event) => {
      if (!event || !event.latLng) {
        return;
      }
      placeIdInput.value = "";
      setPosition(event.latLng.lat(), event.latLng.lng(), false);
      if (confirmWrapper && confirmCheckbox) {
        confirmWrapper.style.display = "none";
        confirmCheckbox.checked = false;
      }
    });

    map.addListener("idle", () => {
      const center = map.getCenter();
      if (center) {
        mapCenter = { lat: center.lat(), lng: center.lng() };
      }
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

    const markUnverified = () => {
      placeIdInput.value = "";
      latInput.value = "";
      lngInput.value = "";
      hideMarker(marker);
      setVerificationStatus(
        statusElement,
        alertElement,
        confirmWrapper,
        confirmCheckbox,
        false,
        "",
        addressInput.value.trim() !== ""
      );
      if (confirmWrapper) {
        confirmWrapper.style.display =
          isEditMode && addressInput.value.trim() !== "" ? "flex" : "none";
      }
    };

    addressInput.addEventListener("input", () => {
      if (ignoreInputEvent) {
        return;
      }
      if (addressInput.value !== lastSelectedAddress) {
        lastSelectedAddress = addressInput.value;
        markUnverified();
      }
    });

    // --- Bottone "Centra su indirizzo" ---
    const showGeocodeError = () => {
      window.alert("Impossibile centrare: seleziona dai suggerimenti o usa la mappa.");
    };

    if (geocodeButton) {
      geocodeButton.addEventListener("click", () => {
        if (!window.google?.maps?.Geocoder) {
          showGeocodeError();
          return;
        }
        const address = addressInput.value.trim();
        if (!address) {
          showGeocodeError();
          return;
        }
        const geocoder = new window.google.maps.Geocoder();
        geocoder.geocode({ address }, (results, status) => {
          if (
            status === "OK" &&
            results &&
            results[0] &&
            results[0].geometry &&
            results[0].geometry.location
          ) {
            const location = results[0].geometry.location;
            placeIdInput.value = results[0].place_id || "";
            lastSelectedAddress = addressInput.value;
            setPosition(location.lat(), location.lng(), true);
            map.setZoom(FOCUSED_ZOOM);
            return;
          }
          showGeocodeError();
        });
      });
    }

    // --- Validazione submit: indirizzo senza coordinate ---

    if (form) {
      form.addEventListener("submit", (event) => {
        if (!isEditMode) {
          return;
        }
        const hasLat = isCoordinateSet(latInput.value);
        const hasLng = isCoordinateSet(lngInput.value);
        const hasAddress = addressInput.value.trim() !== "";
        if (!hasAddress || (hasLat && hasLng)) {
          return;
        }

        const confirmAllowed = confirmCheckbox && confirmCheckbox.checked;
        if (confirmAllowed) {
          return;
        }

        event.preventDefault();

        setVerificationStatus(
          statusElement,
          alertElement,
          confirmWrapper,
          confirmCheckbox,
          false,
          "",
          true
        );
        if (confirmWrapper) {
          confirmWrapper.style.display = "flex";
        }
      });
    }

  };

  window.refreshCantiereFormMap = function refreshCantiereFormMap() {
    if (!mapInstance || !window.google || !window.google.maps) {
      return;
    }
    window.google.maps.event.trigger(mapInstance, "resize");
    const markerPosition =
      markerInstance && markerInstance.getVisible() ? markerInstance.getPosition() : null;
    if (markerPosition) {
      mapInstance.setCenter(markerPosition);
    } else if (mapCenter) {
      mapInstance.setCenter(mapCenter);
    }
  };

  document.addEventListener("DOMContentLoaded", () => {
    if (!window.google || !window.google.maps) {
      showFallback(document.getElementById("cantiere-pick-map"));
    }
  });
})();
