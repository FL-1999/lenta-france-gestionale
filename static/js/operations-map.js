(() => {
  window.initOperationsMap = () => {
    const configEl = document.getElementById("cantieri-map-config");
    if (!configEl) return;

    let parsed;
    try {
      parsed = JSON.parse(configEl.textContent || "{}");
    } catch (error) {
      console.error("Invalid operations map config", error);
      return;
    }

    const dataset = parsed.dataset || {};
    const sites = Array.isArray(dataset.sites) ? dataset.sites : [];
    const depots = Array.isArray(dataset.depots) ? dataset.depots : [];
    const transports = Array.isArray(dataset.transports) ? dataset.transports : [];

    const mapEl = document.getElementById("cantieri-map");
    if (!mapEl || !window.google?.maps) return;

    const markerIcons = {
    siteActive: "https://maps.google.com/mapfiles/ms/icons/green-dot.png",
    siteClosed: "https://maps.google.com/mapfiles/ms/icons/grey-dot.png",
    depot: "https://maps.google.com/mapfiles/ms/icons/blue-dot.png",
    transport: "https://maps.google.com/mapfiles/ms/icons/orange-dot.png",
    vehicle: "https://maps.google.com/mapfiles/ms/icons/purple-dot.png",
    driver: "https://maps.google.com/mapfiles/ms/icons/yellow-dot.png",
  };

    const legendItems = [
    ["Cantieri attivi", markerIcons.siteActive],
    ["Cantieri chiusi", markerIcons.siteClosed],
    ["Depositi", markerIcons.depot],
    ["Trasporti", markerIcons.transport],
    ["Mezzi", markerIcons.vehicle],
    ["Autisti", markerIcons.driver],
  ];

    const legend = document.getElementById("operations-map-legend");
    if (legend) {
      legend.innerHTML = legendItems
        .map(
          ([label, icon]) =>
            `<span class="map-legend__item"><img src="${icon}" alt="" /><span>${label}</span></span>`
        )
        .join("");
    }

    const map = new google.maps.Map(mapEl, {
    center: { lat: 45.4642, lng: 9.19 },
    zoom: 6,
    mapTypeControl: true,
    streetViewControl: false,
    fullscreenControl: true,
  });

    const infoWindow = new google.maps.InfoWindow();
    let bounds = new google.maps.LatLngBounds();
    const overlays = [];

  function extendBounds(lat, lng) {
    if (typeof lat !== "number" || typeof lng !== "number") return;
    bounds.extend({ lat, lng });
  }

  function makeInfoHtml({ title, type, status, details, link }) {
    const detailsHtml = (details || [])
      .filter(Boolean)
      .map((item) => `<li>${item}</li>`)
      .join("");
    return `
      <div class="map-infowindow">
        <div class="map-infowindow-title">${title || "—"}</div>
        <div class="map-infowindow-address">${type || ""}${status ? ` · ${status}` : ""}</div>
        ${detailsHtml ? `<ul class="map-infowindow-list">${detailsHtml}</ul>` : ""}
        ${link ? `<div class="map-infowindow-actions"><a class="btn btn-primary btn-sm" href="${link}">Apri dettaglio</a></div>` : ""}
      </div>
    `;
  }

  function addMarker({ lat, lng, icon, html }) {
    if (typeof lat !== "number" || typeof lng !== "number") return null;
    const marker = new google.maps.Marker({ map, position: { lat, lng }, icon });
    marker.addListener("click", () => {
      infoWindow.setContent(html);
      infoWindow.open(map, marker);
    });
    overlays.push(marker);
    extendBounds(lat, lng);
    return marker;
  }

  function addPolyline(path) {
    if (!Array.isArray(path) || path.length < 2) return;
    const polyline = new google.maps.Polyline({
      map,
      path,
      strokeColor: "#fb923c",
      strokeOpacity: 0.9,
      strokeWeight: 4,
      geodesic: true,
    });
    overlays.push(polyline);
  }

  function parseDate(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

    const filters = {
    view: document.getElementById("map-filter-view"),
    date: document.getElementById("map-filter-date"),
    tripStatus: document.getElementById("map-filter-trip-status"),
    site: document.getElementById("map-filter-site"),
    driver: document.getElementById("map-filter-driver"),
    vehicle: document.getElementById("map-filter-vehicle"),
  };

  function fillSelect(selectEl, values, valueKey = "value", labelKey = "label") {
    if (!selectEl) return;
    values.forEach((item) => {
      const option = document.createElement("option");
      option.value = String(item[valueKey] ?? "");
      option.textContent = item[labelKey] || "—";
      selectEl.appendChild(option);
    });
  }

    fillSelect(
    filters.tripStatus,
    [...new Set(transports.map((t) => t.status).filter(Boolean))]
      .sort()
      .map((status) => ({ value: status, label: status }))
  );
    fillSelect(
    filters.site,
    sites.map((s) => ({ value: s.id, label: s.name })).sort((a, b) => a.label.localeCompare(b.label))
  );
    fillSelect(
    filters.driver,
    [...new Map(transports.filter((t) => t.driver_id).map((t) => [t.driver_id, t.driver_name || `ID ${t.driver_id}`])).entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label))
  );
    fillSelect(
    filters.vehicle,
    [...new Map(transports.filter((t) => t.vehicle_id).map((t) => [t.vehicle_id, t.vehicle_name || `ID ${t.vehicle_id}`])).entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label))
  );

  function clearOverlays() {
    overlays.forEach((overlay) => {
      if (overlay?.setMap) overlay.setMap(null);
    });
    overlays.length = 0;
  }

  function selectedValue(el) {
    return (el?.value || "").trim();
  }

  function isTripInDatePeriod(trip, period) {
    if (!period) return true;
    const tripDate = parseDate(trip.date);
    if (!tripDate) return false;
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const diffDays = Math.floor((tripDate.getTime() - now.getTime()) / 86400000);
    if (period === "today") return diffDays === 0;
    if (period === "7d") return diffDays >= 0 && diffDays <= 7;
    if (period === "30d") return diffDays >= 0 && diffDays <= 30;
    return true;
  }

  function render() {
    clearOverlays();
    bounds = new google.maps.LatLngBounds();

    const selectedView = selectedValue(filters.view) || "general";
    const selectedDate = selectedValue(filters.date);
    const selectedTripStatus = selectedValue(filters.tripStatus);
    const selectedSite = selectedValue(filters.site);
    const selectedDriver = selectedValue(filters.driver);
    const selectedVehicle = selectedValue(filters.vehicle);

    const showGeneral = selectedView === "general";
    const showTransport = showGeneral || selectedView === "transport";
    const showSitesActive = showGeneral || selectedView === "sites_active";
    const showSitesClosed = selectedView === "sites_closed";
    const showDepots = showGeneral || selectedView === "depots";
    const showVehicles = selectedView === "vehicles";
    const showDrivers = selectedView === "drivers";

    const filteredTrips = transports.filter((trip) => {
      if (selectedTripStatus && trip.status !== selectedTripStatus) return false;
      if (selectedDriver && String(trip.driver_id || "") !== selectedDriver) return false;
      if (selectedVehicle && String(trip.vehicle_id || "") !== selectedVehicle) return false;
      if (!isTripInDatePeriod(trip, selectedDate)) return false;
      if (selectedSite) {
        const hasSite = (trip.route_points || []).some(
          (point) => point.type === "site" && String(point.id || "") === selectedSite
        );
        if (!hasSite) return false;
      }
      return true;
    });

    if (showSitesActive || showSitesClosed) {
      sites.forEach((site) => {
        const isClosed = String(site.status || "").toLowerCase() === "chiuso";
        if (showSitesActive && isClosed) return;
        if (showSitesClosed && !isClosed) return;
        if (selectedSite && String(site.id) !== selectedSite) return;
        addMarker({
          lat: site.lat,
          lng: site.lng,
          icon: isClosed ? markerIcons.siteClosed : markerIcons.siteActive,
          html: makeInfoHtml({
            title: site.name,
            type: "Cantiere",
            status: site.status || (site.is_active ? "attivo" : "non attivo"),
            details: [site.address, site.caposquadra_name ? `Caposquadra: ${site.caposquadra_name}` : null],
            link: parsed.detailUrlTemplate?.replace("__SITE_ID__", String(site.id)),
          }),
        });
      });
    }

    if (showDepots) {
      depots.forEach((depot) => {
        addMarker({
          lat: depot.lat,
          lng: depot.lng,
          icon: markerIcons.depot,
          html: makeInfoHtml({
            title: depot.name,
            type: "Deposito",
            status: depot.is_active ? "attivo" : "non attivo",
            details: [depot.address],
            link: "/manager/depositi",
          }),
        });
      });
    }

    if (showTransport || showVehicles || showDrivers) {
      filteredTrips.forEach((trip) => {
        const routePoints = (trip.route_points || []).filter(
          (point) => typeof point.lat === "number" && typeof point.lng === "number"
        );
        const path = routePoints.map((point) => ({ lat: point.lat, lng: point.lng }));

        if (showTransport) {
          addPolyline(path);
          routePoints.forEach((point) => {
            const roleLabel = point.role === "origin" ? "Origine" : point.role === "destination" ? "Destinazione" : "Tappa";
            addMarker({
              lat: point.lat,
              lng: point.lng,
              icon: markerIcons.transport,
              html: makeInfoHtml({
                title: `${trip.code} · ${point.name}`,
                type: `Trasporto (${roleLabel})`,
                status: trip.status,
                details: [
                  trip.driver_name ? `Autista: ${trip.driver_name}` : null,
                  trip.vehicle_name ? `Mezzo: ${trip.vehicle_name}` : null,
                  trip.date ? `Data: ${trip.date}` : null,
                ],
                link: trip.detail_url,
              }),
            });
          });
        }

        const destinationPoint = routePoints[routePoints.length - 1] || routePoints[0];
        if (!destinationPoint) return;

        if (showVehicles && trip.vehicle_name) {
          addMarker({
            lat: destinationPoint.lat,
            lng: destinationPoint.lng,
            icon: markerIcons.vehicle,
            html: makeInfoHtml({
              title: trip.vehicle_name,
              type: "Mezzo",
              status: trip.status,
              details: [trip.code, trip.driver_name ? `Autista: ${trip.driver_name}` : null],
              link: trip.detail_url,
            }),
          });
        }

        if (showDrivers && trip.driver_name) {
          addMarker({
            lat: destinationPoint.lat,
            lng: destinationPoint.lng,
            icon: markerIcons.driver,
            html: makeInfoHtml({
              title: trip.driver_name,
              type: "Autista",
              status: trip.status,
              details: [trip.code, trip.vehicle_name ? `Mezzo: ${trip.vehicle_name}` : null],
              link: trip.detail_url,
            }),
          });
        }
      });
    }

    if (!bounds.isEmpty()) {
      map.fitBounds(bounds, 64);
    }
  }

    Object.values(filters).forEach((el) => el?.addEventListener("change", render));
    render();
  };

  if (window.loadGoogleMapsScriptOnce) {
    window.loadGoogleMapsScriptOnce("initOperationsMap");
  } else if (window.google?.maps) {
    window.initOperationsMap();
  }
})();
