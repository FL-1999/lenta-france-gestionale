(() => {
  const parsePoints = (element) => {
    const raw = element?.dataset?.tripPoints || "[]";
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  };

  const buildMarkerLabel = (index) => String.fromCharCode(65 + index);

  const initTripMap = () => {
    const container = document.querySelector("[data-trip-map]");
    if (!container || container.dataset.mapInitialized === "true") {
      return;
    }

    if (!window.google?.maps) {
      return;
    }

    const canvas = container.querySelector("[data-trip-map-canvas]");
    const notice = container.querySelector("[data-trip-map-notice]");
    if (!canvas) {
      return;
    }

    const points = parsePoints(container).filter((point) => typeof point.lat === "number" && typeof point.lng === "number");
    if (points.length === 0) {
      if (notice) {
        notice.hidden = false;
      }
      return;
    }

    const map = new window.google.maps.Map(canvas, {
      center: { lat: points[0].lat, lng: points[0].lng },
      zoom: 7,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: false,
    });
    const bounds = new window.google.maps.LatLngBounds();
    const infoWindow = new window.google.maps.InfoWindow();
    const markers = points.map((point, index) => {
      const marker = new window.google.maps.Marker({
        map,
        position: { lat: point.lat, lng: point.lng },
        label: buildMarkerLabel(index),
        title: point.name,
      });
      bounds.extend(marker.getPosition());
      marker.addListener("click", () => {
        infoWindow.setContent(`
          <div style="min-width: 180px; color: #111;">
            <strong>${point.name}</strong><br>
            <span>${point.role_label || point.role || "Tappa"}</span><br>
            <small>${point.type_label || point.type || "Luogo"}</small>
          </div>
        `);
        infoWindow.open({ anchor: marker, map });
      });
      return marker;
    });

    const fallbackPolyline = () => {
      new window.google.maps.Polyline({
        path: points.map((point) => ({ lat: point.lat, lng: point.lng })),
        geodesic: true,
        strokeColor: "#68d5ff",
        strokeOpacity: 0.9,
        strokeWeight: 4,
        map,
      });
      map.fitBounds(bounds, 48);
    };

    if (points.length >= 2 && window.google.maps.DirectionsService && window.google.maps.DirectionsRenderer) {
      const directionsService = new window.google.maps.DirectionsService();
      const directionsRenderer = new window.google.maps.DirectionsRenderer({
        map,
        suppressMarkers: true,
        polylineOptions: {
          strokeColor: "#68d5ff",
          strokeOpacity: 0.95,
          strokeWeight: 5,
        },
      });

      directionsService.route(
        {
          origin: { lat: points[0].lat, lng: points[0].lng },
          destination: { lat: points[points.length - 1].lat, lng: points[points.length - 1].lng },
          waypoints: points.slice(1, -1).map((point) => ({
            location: { lat: point.lat, lng: point.lng },
            stopover: true,
          })),
          optimizeWaypoints: false,
          travelMode: window.google.maps.TravelMode.DRIVING,
        },
        (response, status) => {
          if (status === "OK" && response) {
            directionsRenderer.setDirections(response);
            map.fitBounds(bounds, 48);
            return;
          }
          fallbackPolyline();
        },
      );
    } else {
      fallbackPolyline();
    }

    if (notice) {
      notice.hidden = true;
    }

    container.dataset.mapInitialized = "true";
    container.__tripMapMarkers = markers;
  };

  const boot = () => {
    if (typeof window.loadGoogleMapsScriptOnce === "function") {
      window.loadGoogleMapsScriptOnce("initTripMap", ["places"]);
      return;
    }
    initTripMap();
  };

  window.initTripMap = initTripMap;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
