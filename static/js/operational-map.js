(() => {
  const VIEW_CONFIG = {
    generale: { sites: true, depots: true, trips: true, tripMode: "transport" },
    trasporti: { trips: true, tripMode: "transport" },
    cantieri_attivi: { sites: true, onlyActiveSites: true },
    cantieri_chiusi: { sites: true, onlyClosedSites: true },
    depositi: { depots: true },
    mezzi: { trips: true, tripMode: "vehicle" },
    autisti: { trips: true, tripMode: "driver" },
  };

  const COLORS = {
    site_active: "#22c55e",
    site_closed: "#f97316",
    depot: "#3b82f6",
    trip: "#eab308",
    vehicle: "#a855f7",
    driver: "#14b8a6",
    gps_real: "#22c55e",
    gps_fallback: "#f97316",
    estimated: "#eab308",
  };

  const parsePayload = (container) => {
    try {
      return JSON.parse(container.dataset.mapPayload || "{}");
    } catch (_error) {
      return {};
    }
  };

  const markerGlyph = (label, color) => new window.google.maps.Marker({
    icon: {
      path: window.google.maps.SymbolPath.CIRCLE,
      scale: 7,
      fillColor: color,
      fillOpacity: 1,
      strokeColor: "#0b1220",
      strokeWeight: 2,
    },
    title: label,
  });

  const buildInfo = (title, rows, detailUrl) => `
    <div style="min-width:220px;color:#0b1220;font-size:13px;line-height:1.4;">
      <div style="font-weight:700;margin-bottom:4px;">${title}</div>
      ${rows.filter(Boolean).map((r) => `<div>${r}</div>`).join("")}
      ${detailUrl ? `<a href="${detailUrl}" style="display:inline-block;margin-top:6px;color:#2563eb;font-weight:600;">Apri dettaglio</a>` : ""}
    </div>
  `;

  const matchesExtraFilters = (trip, filters) => {
    if (filters.stato_viaggio && filters.stato_viaggio !== "all" && trip.state !== filters.stato_viaggio) return false;
    if (filters.date_from && trip.date && trip.date < filters.date_from) return false;
    if (filters.date_to && trip.date && trip.date > filters.date_to) return false;
    if (filters.cantiere_id) {
      const id = Number(filters.cantiere_id);
      const containsSite = (trip.route_points || []).some((p) => p.type === "site" && Number(p.site_id || 0) === id);
      if (!containsSite) return false;
    }
    if (filters.mezzo_id && Number(trip.vehicle_id || 0) !== Number(filters.mezzo_id)) return false;
    if (filters.autista_id && Number(trip.driver_id || 0) !== Number(filters.autista_id)) return false;
    return true;
  };

  const initMap = () => {
    const container = document.querySelector("[data-operational-map]");
    if (!container || container.dataset.initialized === "true" || !window.google?.maps) return;

    const payload = parsePayload(container);
    const canvas = container.querySelector("[data-operational-map-canvas]");
    const warningEl = container.querySelector("[data-map-warning]");
    const legendEl = container.querySelector("[data-map-legend]");
    if (!canvas) return;

    const selected = payload.filters?.selected || {};
    let currentView = payload.filters?.selected_view || "generale";
    const activeMarkers = [];
    const activePolylines = [];
    let directionsRenderer = null;
    const map = new window.google.maps.Map(canvas, {
      center: { lat: 46.2276, lng: 2.2137 },
      zoom: 6,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: false,
      styles: [{ elementType: "geometry", stylers: [{ color: "#0f172a" }] }, { elementType: "labels.text.fill", stylers: [{ color: "#cbd5e1" }] }, { elementType: "labels.text.stroke", stylers: [{ color: "#0f172a" }] }],
    });
    const infoWindow = new window.google.maps.InfoWindow();

    const buildSelect = (name, options, currentValue, defaultLabel) => {
      const select = container.querySelector(`[data-filter="${name}"]`);
      if (!select) return;
      select.innerHTML = `<option value="">${defaultLabel}</option>` + options.map((o) => `<option value="${o.id ?? o.value}" ${String(currentValue ?? "") === String(o.id ?? o.value) ? "selected" : ""}>${o.label ?? o.name}</option>`).join("");
      select.addEventListener("change", () => {
        selected[name] = select.value;
        render();
      });
    };

    const dateFrom = container.querySelector('[data-filter="date_from"]');
    const dateTo = container.querySelector('[data-filter="date_to"]');
    if (dateFrom) {
      dateFrom.value = selected.date_from || "";
      dateFrom.addEventListener("change", () => {
        selected.date_from = dateFrom.value;
        render();
      });
    }
    if (dateTo) {
      dateTo.value = selected.date_to || "";
      dateTo.addEventListener("change", () => {
        selected.date_to = dateTo.value;
        render();
      });
    }

    buildSelect("stato_viaggio", payload.filters?.trip_states || [], selected.stato_viaggio, "Tutti gli stati");
    buildSelect("cantiere_id", payload.filters?.sites || [], selected.cantiere_id, "Tutti i cantieri");
    buildSelect("mezzo_id", payload.filters?.vehicles || [], selected.mezzo_id, "Tutti i mezzi");
    buildSelect("autista_id", payload.filters?.drivers || [], selected.autista_id, "Tutti gli autisti");

    container.querySelectorAll("[data-view]").forEach((button) => {
      if (button.dataset.view === currentView) button.classList.add("btn-primary");
      button.addEventListener("click", () => {
        currentView = button.dataset.view;
        container.querySelectorAll("[data-view]").forEach((b) => b.classList.remove("btn-primary"));
        button.classList.add("btn-primary");
        render();
      });
    });

    const clearMap = () => {
      activeMarkers.splice(0).forEach((m) => m.setMap(null));
      activePolylines.splice(0).forEach((p) => p.setMap(null));
      if (directionsRenderer) {
        directionsRenderer.setMap(null);
        directionsRenderer = null;
      }
    };

    const addMarker = (position, label, color, infoHtml) => {
      const marker = markerGlyph(label, color);
      marker.setPosition(position);
      marker.setMap(map);
      marker.addListener("click", () => {
        infoWindow.setContent(infoHtml);
        infoWindow.open({ map, anchor: marker });
      });
      activeMarkers.push(marker);
      return marker;
    };

    const drawTripRoute = (trip, emphasize) => {
      const path = (trip.route_points || []).map((point) => ({ lat: point.lat, lng: point.lng }));
      if (path.length < 2) return;
      const polyline = new window.google.maps.Polyline({
        map,
        path,
        geodesic: true,
        strokeColor: emphasize ? "#f59e0b" : "#64748b",
        strokeOpacity: emphasize ? 0.9 : 0.45,
        strokeWeight: emphasize ? 4 : 3,
      });
      activePolylines.push(polyline);
    };

    const renderDirectionsForSingleTrip = (trip) => {
      const points = trip.route_points || [];
      if (points.length < 2 || !window.google.maps.DirectionsService || !window.google.maps.DirectionsRenderer) return false;
      const service = new window.google.maps.DirectionsService();
      directionsRenderer = new window.google.maps.DirectionsRenderer({
        map,
        suppressMarkers: true,
        polylineOptions: { strokeColor: "#f59e0b", strokeOpacity: 0.95, strokeWeight: 5 },
      });
      service.route({
        origin: { lat: points[0].lat, lng: points[0].lng },
        destination: { lat: points[points.length - 1].lat, lng: points[points.length - 1].lng },
        waypoints: points.slice(1, -1).map((p) => ({ location: { lat: p.lat, lng: p.lng }, stopover: true })),
        optimizeWaypoints: false,
        travelMode: window.google.maps.TravelMode.DRIVING,
      }, (result, status) => {
        if (status === "OK" && result) {
          directionsRenderer.setDirections(result);
        } else {
          drawTripRoute(trip, true);
        }
      });
      return true;
    };

    const render = () => {
      clearMap();
      const cfg = VIEW_CONFIG[currentView] || VIEW_CONFIG.generale;
      const bounds = new window.google.maps.LatLngBounds();
      const visibleTrips = (payload.trips || []).filter((trip) => matchesExtraFilters(trip, selected));

      if (cfg.sites) {
        (payload.sites || []).forEach((site) => {
          if (cfg.onlyActiveSites && site.status !== "aperto") return;
          if (cfg.onlyClosedSites && site.status !== "chiuso") return;
          const color = site.status === "aperto" ? COLORS.site_active : COLORS.site_closed;
          const marker = addMarker({ lat: site.lat, lng: site.lng }, site.name, color, buildInfo(site.name, [`<strong>Tipo:</strong> Cantiere`, `<strong>Stato:</strong> ${site.status_label}`, site.city ? `<strong>Città:</strong> ${site.city}` : ""], site.detail_url));
          bounds.extend(marker.getPosition());
        });
      }

      if (cfg.depots) {
        (payload.depots || []).forEach((depot) => {
          const marker = addMarker({ lat: depot.lat, lng: depot.lng }, depot.name, COLORS.depot, buildInfo(depot.name, [`<strong>Tipo:</strong> Deposito`, depot.city ? `<strong>Città:</strong> ${depot.city}` : ""], depot.detail_url));
          bounds.extend(marker.getPosition());
        });
      }

      if (cfg.trips) {
        visibleTrips.forEach((trip) => {
          let tripColor = cfg.tripMode === "vehicle" ? COLORS.vehicle : cfg.tripMode === "driver" ? COLORS.driver : COLORS.trip;
          if (cfg.tripMode === "transport") {
            if (trip.marker_source === "gps_reale") tripColor = COLORS.gps_real;
            else if (trip.marker_source === "gps_non_disponibile") tripColor = COLORS.gps_fallback;
            else tripColor = COLORS.estimated;
          }
          const markerTitle = cfg.tripMode === "vehicle" ? (trip.vehicle_label || `Mezzo viaggio ${trip.code}`) : cfg.tripMode === "driver" ? (trip.driver_name || `Autista viaggio ${trip.code}`) : `Viaggio ${trip.code}`;
          const marker = addMarker({ lat: trip.marker.lat, lng: trip.marker.lng }, markerTitle, tripColor, buildInfo(markerTitle, [`<strong>Tipo:</strong> Viaggio`, `<strong>Codice:</strong> ${trip.code}`, `<strong>Stato:</strong> ${trip.state_label}`, `<strong>Mezzo:</strong> ${trip.vehicle_label || "-"}`, `<strong>Autista:</strong> ${trip.driver_name || "-"}`, `<strong>GPS:</strong> ${trip.gps?.gps_status_label || "Stima"}`, trip.gps?.timestamp ? `<strong>Ultimo update:</strong> ${trip.gps.timestamp}` : "", trip.gps?.speed_kmh !== undefined && trip.gps?.speed_kmh !== null ? `<strong>Velocità:</strong> ${trip.gps.speed_kmh.toFixed(1)} km/h` : "", trip.gps?.status ? `<strong>Stato mezzo:</strong> ${trip.gps.status}` : "", `<strong>Origine:</strong> ${trip.origin}`, `<strong>Destinazione:</strong> ${trip.destination}`], trip.detail_url));
          bounds.extend(marker.getPosition());
          if (cfg.tripMode === "transport") {
            drawTripRoute(trip, true);
            (trip.route_points || []).forEach((point) => {
              const pointColor = point.role === "origin" ? "#22c55e" : point.role === "destination" ? "#f43f5e" : "#38bdf8";
              const pointMarker = addMarker({ lat: point.lat, lng: point.lng }, point.name, pointColor, buildInfo(point.name, [`<strong>Punto:</strong> ${point.role_label || point.role}`, `<strong>Tipo:</strong> ${point.type_label || point.type}`], trip.detail_url));
              bounds.extend(pointMarker.getPosition());
            });
          }
        });

        if (cfg.tripMode === "transport" && visibleTrips.length === 1) {
          clearMap();
          const onlyTrip = visibleTrips[0];
          renderDirectionsForSingleTrip(onlyTrip);
          (onlyTrip.route_points || []).forEach((point) => {
            const pointColor = point.role === "origin" ? "#22c55e" : point.role === "destination" ? "#f43f5e" : "#38bdf8";
            const pointMarker = addMarker({ lat: point.lat, lng: point.lng }, point.name, pointColor, buildInfo(point.name, [`<strong>Punto:</strong> ${point.role_label || point.role}`, `<strong>Tipo:</strong> ${point.type_label || point.type}`], onlyTrip.detail_url));
            bounds.extend(pointMarker.getPosition());
          });
        }
      }

      if (!bounds.isEmpty()) map.fitBounds(bounds, 70);

      const stats = payload.stats || {};
      warningEl.textContent = `Record senza coordinate ignorati: cantieri ${stats.sites_missing_coordinates || 0}, depositi ${stats.depots_missing_coordinates || 0}, viaggi ${stats.trips_missing_coordinates || 0}. Camion con GPS reale: ${stats.trips_with_real_gps || 0}. Camion in fallback: ${stats.trips_with_gps_fallback || 0}.`;

      legendEl.innerHTML = [
        [COLORS.site_active, "Cantiere attivo"],
        [COLORS.site_closed, "Cantiere chiuso"],
        [COLORS.depot, "Deposito"],
        [COLORS.gps_real, "Camion con GPS reale"],
        [COLORS.gps_fallback, "Camion fallback GPS"],
        [COLORS.estimated, "Viaggio stimato"],
        [COLORS.vehicle, "Mezzo"],
        [COLORS.driver, "Autista"],
      ].map(([color, label]) => `<span><span class="dot" style="background:${color}"></span>${label}</span>`).join("");
    };

    render();
    container.dataset.initialized = "true";
  };

  const boot = () => {
    if (typeof window.loadGoogleMapsScriptOnce === "function") {
      window.loadGoogleMapsScriptOnce("initOperationalMap", ["places"]);
    } else {
      initMap();
    }
  };

  window.initOperationalMap = initMap;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
