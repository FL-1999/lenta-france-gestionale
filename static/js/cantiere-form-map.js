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

  const isCoordinateSet = (value) => parseCoordinate(value) !== null;

  const setVerificationStatus = (
    statusElement,
    alertElement,
    confirmWrapper,
    confirmCheckbox,
    isVerified,
    alertMessage = ""
  ) => {
    if (statusElement) {
      statusElement.textContent = isVerified ? "Verificato ✅" : "Non verificato ⚠️";
    }
    if (alertElement) {
      if (alertMessage) {
        alertElement.textContent = alertMessage;
        alertElement.style.display = "block";
      } else {
        alertElement.textContent = "";
        alertElement.style.display = "none";
      }
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
    mapElement.dataset.mapInitialized = "true";
    setVerificationStatus(statusElement, alertElement, confirmWrapper, confirmCheckbox, hasCoordinates);

    const setPosition = (lat, lng, shouldCenter = true) => {
      const position = { lat, lng };
      showMarkerAt(marker, position);
      updateLatLngInputs(latInput, lngInput, lat, lng);
      setVerificationStatus(statusElement, alertElement, confirmWrapper, confirmCheckbox, true);
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
      setVerificationStatus(statusElement, alertElement, confirmWrapper, confirmCheckbox, false);
      if (confirmWrapper) {
        confirmWrapper.style.display = isEditMode && addressInput.value.trim() !== "" ? "flex" : "none";
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

    // --- Validazione submit: coordinate mancanti ---
    if (form) {
      form.addEventListener("submit", (event) => {
        const hasLat = isCoordinateSet(latInput.value);
        const hasLng = isCoordinateSet(lngInput.value);
        const hasCoordinates = hasLat && hasLng;
        const confirmAllowed = confirmCheckbox && confirmCheckbox.checked;

        if (!hasCoordinates) {
          if (isEditMode && confirmAllowed) {
            return;
          }
          event.preventDefault();
          const message = isEditMode
            ? "Coordinate mancanti: se vuoi salvare comunque, conferma la casella."
            : "Per creare il cantiere devi impostare la posizione sulla mappa o selezionare un indirizzo.";
          setVerificationStatus(
            statusElement,
            alertElement,
            confirmWrapper,
            confirmCheckbox,
            false,
            message
          );
          if (confirmWrapper && isEditMode) {
            confirmWrapper.style.display = "flex";
          }
        }
      });
    }

  };

  document.addEventListener("DOMContentLoaded", () => {
    if (!window.google || !window.google.maps) {
      showFallback(document.getElementById("cantiere-pick-map"));
    }
  });
})();
