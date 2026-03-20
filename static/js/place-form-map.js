(() => {
  const DEFAULT_CENTER = { lat: 43.7, lng: 7.27 };
  const DEFAULT_ZOOM = 12;
  const FOCUSED_ZOOM = 16;

  const parseCoordinate = (value) => {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const findAddressComponent = (components, types) => {
    if (!Array.isArray(components)) {
      return null;
    }
    const typeList = Array.isArray(types) ? types : [types];
    return components.find((component) =>
      typeList.every((type) => component.types?.includes(type)),
    ) || null;
  };

  const composeStreetAddress = (components, fallback) => {
    const route = findAddressComponent(components, "route")?.long_name || "";
    const streetNumber = findAddressComponent(components, "street_number")?.long_name || "";
    const value = [route, streetNumber].filter(Boolean).join(" ").trim();
    return value || fallback || "";
  };

  const buildLocationPayloadFromPlace = (place) => {
    if (!place?.geometry?.location) {
      return null;
    }
    const components = place.address_components || [];
    return {
      address: composeStreetAddress(components, place.formatted_address || place.name || ""),
      city:
        findAddressComponent(components, ["locality", "political"])?.long_name
        || findAddressComponent(components, ["postal_town", "political"])?.long_name
        || findAddressComponent(components, ["administrative_area_level_3", "political"])?.long_name
        || "",
      postalCode: findAddressComponent(components, "postal_code")?.long_name || "",
      province:
        findAddressComponent(components, ["administrative_area_level_2", "political"])?.short_name
        || findAddressComponent(components, ["administrative_area_level_1", "political"])?.short_name
        || "",
      country: findAddressComponent(components, "country")?.long_name || "",
      lat: place.geometry.location.lat(),
      lng: place.geometry.location.lng(),
      placeId: place.place_id || "",
      verified: true,
    };
  };

  const applyFieldValue = (element, value) => {
    if (element) {
      element.value = value ?? "";
    }
  };

  const updateStatusUI = (elements, hasCoordinates, shouldWarnMissingCoordinates) => {
    const label = hasCoordinates ? "Verificato ✅" : "Non verificato ⚠️";
    const statusClass = hasCoordinates ? "badge-success" : "badge-danger";

    if (elements.statusBadge) {
      elements.statusBadge.textContent = label;
      elements.statusBadge.classList.remove("badge-success", "badge-danger");
      elements.statusBadge.classList.add(statusClass);
    }

    if (elements.statusText) {
      elements.statusText.textContent = hasCoordinates
        ? "Posizione verificata sulla mappa."
        : "Seleziona un indirizzo dai suggerimenti o clicca sulla mappa.";
    }

    if (elements.alert) {
      elements.alert.style.display = shouldWarnMissingCoordinates ? "block" : "none";
    }

    if (elements.confirmWrapper) {
      elements.confirmWrapper.style.display = shouldWarnMissingCoordinates ? "flex" : "none";
    }
  };

  const collectElements = (root) => {
    const get = (name) => root.querySelector(`[data-map-field="${name}"]`);
    return {
      addressInput: get("address"),
      cityInput: get("city"),
      postalCodeInput: get("postal_code"),
      provinceInput: get("province"),
      countryInput: get("country"),
      latInput: get("lat"),
      lngInput: get("lng"),
      placeIdInput: get("place_id"),
      statusBadge: root.querySelector("[data-map-status-badge]"),
      statusText: root.querySelector("[data-map-status-text]"),
      alert: root.querySelector("[data-map-alert]"),
      confirmWrapper: root.querySelector("[data-map-confirm-wrapper]"),
      mapElement: root.querySelector("[data-place-picker-map]"),
    };
  };

  const initPicker = (root) => {
    if (!root || root.dataset.mapInitialized === "true") {
      return;
    }

    const elements = collectElements(root);
    if (!elements.mapElement || !elements.latInput || !elements.lngInput) {
      return;
    }

    if (!window.google?.maps) {
      updateStatusUI(elements, false, false);
      return;
    }

    const geocoder = new window.google.maps.Geocoder();
    const latValue = parseCoordinate(elements.latInput.value);
    const lngValue = parseCoordinate(elements.lngInput.value);
    const hasCoordinates = latValue !== null && lngValue !== null;
    const initialCenter = hasCoordinates ? { lat: latValue, lng: lngValue } : DEFAULT_CENTER;

    const state = {
      map: new window.google.maps.Map(elements.mapElement, {
        center: initialCenter,
        zoom: hasCoordinates ? FOCUSED_ZOOM : DEFAULT_ZOOM,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
      }),
      marker: new window.google.maps.Marker({
        map: null,
        draggable: true,
      }),
      geocoder,
      elements,
      lastCenter: initialCenter,
    };

    const syncCoordinates = (lat, lng) => {
      applyFieldValue(elements.latInput, lat);
      applyFieldValue(elements.lngInput, lng);
    };

    const hasAddressContent = () => Boolean(elements.addressInput?.value?.trim());

    const syncStatus = () => {
      const hasLatLng = parseCoordinate(elements.latInput.value) !== null && parseCoordinate(elements.lngInput.value) !== null;
      updateStatusUI(elements, hasLatLng, Boolean(hasAddressContent() && !hasLatLng));
    };

    const setMarkerPosition = (lat, lng, shouldCenter = true) => {
      const position = { lat, lng };
      state.marker.setMap(state.map);
      state.marker.setPosition(position);
      if (shouldCenter) {
        state.map.setCenter(position);
      }
      state.lastCenter = position;
      syncCoordinates(lat, lng);
      syncStatus();
    };

    const applyPayload = (payload, { shouldCenter = true } = {}) => {
      if (!payload) {
        return;
      }
      applyFieldValue(elements.addressInput, payload.address);
      applyFieldValue(elements.cityInput, payload.city);
      applyFieldValue(elements.postalCodeInput, payload.postalCode);
      applyFieldValue(elements.provinceInput, payload.province);
      applyFieldValue(elements.countryInput, payload.country);
      applyFieldValue(elements.placeIdInput, payload.placeId);
      setMarkerPosition(payload.lat, payload.lng, shouldCenter);
      state.map.setZoom(FOCUSED_ZOOM);
    };

    const reverseGeocode = (lat, lng) => {
      geocoder.geocode({ location: { lat, lng } }, (results, status) => {
        if (status !== "OK" || !results?.length) {
          applyFieldValue(elements.placeIdInput, "");
          syncStatus();
          return;
        }
        const payload = buildLocationPayloadFromPlace(results[0]);
        if (payload) {
          applyPayload(payload, { shouldCenter: false });
        }
      });
    };

    if (hasCoordinates) {
      setMarkerPosition(latValue, lngValue, true);
    } else {
      syncStatus();
    }

    state.map.addListener("click", (event) => {
      if (!event?.latLng) {
        return;
      }
      const lat = event.latLng.lat();
      const lng = event.latLng.lng();
      setMarkerPosition(lat, lng, false);
      reverseGeocode(lat, lng);
    });

    state.marker.addListener("dragend", (event) => {
      if (!event?.latLng) {
        return;
      }
      const lat = event.latLng.lat();
      const lng = event.latLng.lng();
      setMarkerPosition(lat, lng, false);
      reverseGeocode(lat, lng);
    });

    state.map.addListener("idle", () => {
      const currentCenter = state.map.getCenter();
      if (currentCenter) {
        state.lastCenter = { lat: currentCenter.lat(), lng: currentCenter.lng() };
      }
    });

    if (elements.addressInput) {
      elements.addressInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
        }
      });
      elements.addressInput.addEventListener("input", () => {
        applyFieldValue(elements.placeIdInput, "");
        syncStatus();
      });
    }

    [elements.latInput, elements.lngInput].forEach((input) => {
      if (!input) {
        return;
      }
      input.addEventListener("change", () => {
        const lat = parseCoordinate(elements.latInput.value);
        const lng = parseCoordinate(elements.lngInput.value);
        if (lat === null || lng === null) {
          syncStatus();
          return;
        }
        setMarkerPosition(lat, lng, true);
        reverseGeocode(lat, lng);
      });
    });

    if (elements.addressInput && window.google.maps.places) {
      const autocomplete = new window.google.maps.places.Autocomplete(elements.addressInput, {
        fields: ["address_components", "formatted_address", "geometry", "name", "place_id"],
        types: ["geocode"],
      });

      autocomplete.addListener("place_changed", () => {
        const payload = buildLocationPayloadFromPlace(autocomplete.getPlace());
        if (payload) {
          applyPayload(payload, { shouldCenter: true });
        }
      });
    }

    root.__placePickerState = state;
    root.dataset.mapInitialized = "true";
  };

  window.initPlaceFormMaps = () => {
    document.querySelectorAll("[data-place-picker]").forEach((root) => initPicker(root));
  };

  window.refreshPlaceFormMaps = () => {
    document.querySelectorAll("[data-place-picker]").forEach((root) => {
      const state = root.__placePickerState;
      if (!state || !window.google?.maps) {
        return;
      }
      window.google.maps.event.trigger(state.map, "resize");
      const markerPosition = state.marker.getPosition();
      if (markerPosition) {
        state.map.setCenter(markerPosition);
      } else if (state.lastCenter) {
        state.map.setCenter(state.lastCenter);
      }
    });
  };
})();
