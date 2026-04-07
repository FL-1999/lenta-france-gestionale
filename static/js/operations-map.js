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

    const icons = {
      siteActive: "https://maps.google.com/mapfiles/ms/icons/green-dot.png",
      siteClosed: "https://maps.google.com/mapfiles/ms/icons/grey-dot.png",
      depot: "https://maps.google.com/mapfiles/ms/icons/blue-dot.png",
      transportOrigin: "https://maps.google.com/mapfiles/ms/icons/orange-dot.png",
      transportStop: "https://maps.google.com/mapfiles/ms/icons/yellow-dot.png",
      transportDestination: "https://maps.google.com/mapfiles/ms/icons/red-dot.png",
    };

    const legendItems = [
      ["Cantieri attivi", icons.siteActive],
      ["Cantieri chiusi", icons.siteClosed],
      ["Depositi", icons.depot],
      ["Trasporto · origine", icons.transportOrigin],
      ["Trasporto · tappa", icons.transportStop],
      ["Trasporto · destinazione", icons.transportDestination],
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
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: true,
    });

    const infoWindow = new google.maps.InfoWindow();
    let bounds = new google.maps.LatLngBounds();
    const overlays = [];

    const filters = {
      view: document.getElementById("map-filter-view"),
      tripStatus: document.getElementById("map-filter-trip-status"),
      site: document.getElementById("map-filter-site"),
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
      [...new Set(transports.map((trip) => trip.status).filter(Boolean))]
        .sort()
        .map((status) => ({ value: status, label: status }))
    );

    fillSelect(
      filters.site,
      sites
        .map((site) => ({ value: site.id, label: site.name || `#${site.id}` }))
        .sort((a, b) => a.label.localeCompare(b.label))
    );

    function selectedValue(el) {
      return (el?.value || "").trim();
    }

    function clearOverlays() {
      overlays.forEach((overlay) => overlay?.setMap?.(null));
      overlays.length = 0;
      infoWindow.close();
    }

    function extendBounds(lat, lng) {
      if (typeof lat === "number" && typeof lng === "number") {
        bounds.extend({ lat, lng });
      }
    }

    function addMarker({ lat, lng, icon, html }) {
      if (typeof lat !== "number" || typeof lng !== "number") return;
      const marker = new google.maps.Marker({
        map,
        position: { lat, lng },
        icon,
      });
      marker.addListener("click", () => {
        infoWindow.setContent(html || "");
        infoWindow.open({ anchor: marker, map });
      });
      overlays.push(marker);
      extendBounds(lat, lng);
    }

    function addPolyline(path) {
      if (!Array.isArray(path) || path.length < 2) return;
      const polyline = new google.maps.Polyline({
        map,
        path,
        strokeColor: "#fb923c",
        strokeOpacity: 0.85,
        strokeWeight: 4,
        geodesic: true,
      });
      overlays.push(polyline);
      path.forEach((point) => extendBounds(point.lat, point.lng));
    }

    function transportRoleLabel(role) {
      if (role === "origin") return "Origine";
      if (role === "destination") return "Destinazione";
      return "Tappa";
    }

    function transportRoleIcon(role) {
      if (role === "origin") return icons.transportOrigin;
      if (role === "destination") return icons.transportDestination;
      return icons.transportStop;
    }

    function infoHtml({ title, type, status, details, link }) {
      const items = (details || []).filter(Boolean).map((detail) => `<li>${detail}</li>`).join("");
      return `
        <div class="map-infowindow">
          <div class="map-infowindow-title">${title || "—"}</div>
          <div class="map-infowindow-address">${type || ""}${status ? ` · ${status}` : ""}</div>
          ${items ? `<ul class="map-infowindow-list">${items}</ul>` : ""}
          ${link ? `<div class="map-infowindow-actions"><a class="btn btn-primary btn-sm" href="${link}">Apri dettaglio</a></div>` : ""}
        </div>
      `;
    }

    function render() {
      clearOverlays();
      bounds = new google.maps.LatLngBounds();

      const view = selectedValue(filters.view) || "general";
      const tripStatus = selectedValue(filters.tripStatus);
      const siteFilter = selectedValue(filters.site);

      const showTransport = view === "general" || view === "transport";
      const showSitesActive = view === "general" || view === "sites_active";
      const showSitesClosed = view === "sites_closed";
      const showDepots = view === "general" || view === "depots";

      if (showSitesActive || showSitesClosed) {
        sites.forEach((site) => {
          const isClosed = String(site.status || "").toLowerCase() === "chiuso" || site.is_active === false;
          if (showSitesActive && isClosed) return;
          if (showSitesClosed && !isClosed) return;
          if (siteFilter && String(site.id || "") !== siteFilter) return;

          addMarker({
            lat: site.lat,
            lng: site.lng,
            icon: isClosed ? icons.siteClosed : icons.siteActive,
            html: infoHtml({
              title: site.name,
              type: "Cantiere",
              status: site.status || (isClosed ? "chiuso" : "attivo"),
              details: [site.address, site.caposquadra_name ? `Caposquadra: ${site.caposquadra_name}` : null],
              link: site.detail_url || parsed.detailUrlTemplate?.replace("__SITE_ID__", String(site.id || "")),
            }),
          });
        });
      }

      if (showDepots) {
        depots.forEach((depot) => {
          addMarker({
            lat: depot.lat,
            lng: depot.lng,
            icon: icons.depot,
            html: infoHtml({
              title: depot.name,
              type: "Deposito",
              status: depot.is_active ? "attivo" : "non attivo",
              details: [depot.address],
              link: depot.detail_url || "/manager/depositi",
            }),
          });
        });
      }

      if (showTransport) {
        transports
          .filter((trip) => {
            if (tripStatus && trip.status !== tripStatus) return false;
            if (!siteFilter) return true;
            return (trip.route_points || []).some(
              (point) => point.type === "site" && String(point.id || "") === siteFilter
            );
          })
          .forEach((trip) => {
            const routePoints = (trip.route_points || []).filter(
              (point) => typeof point.lat === "number" && typeof point.lng === "number"
            );
            if (routePoints.length === 0) return;

            addPolyline(routePoints.map((point) => ({ lat: point.lat, lng: point.lng })));

            routePoints.forEach((point) => {
              const pointType = point.type === "depot" ? "Deposito" : point.type === "site" ? "Cantiere" : "Punto";
              addMarker({
                lat: point.lat,
                lng: point.lng,
                icon: transportRoleIcon(point.role),
                html: infoHtml({
                  title: `${trip.code} · ${point.name || "—"}`,
                  type: `Trasporto (${transportRoleLabel(point.role)})`,
                  status: trip.status,
                  details: [
                    pointType,
                    trip.driver_name ? `Autista: ${trip.driver_name}` : null,
                    trip.vehicle_name ? `Mezzo: ${trip.vehicle_name}` : null,
                    trip.date ? `Data: ${trip.date}` : null,
                  ],
                  link: trip.detail_url,
                }),
              });
            });
          });
      }

      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, 64);
      } else {
        map.setCenter({ lat: 45.4642, lng: 9.19 });
        map.setZoom(6);
      }
    }

    Object.values(filters).forEach((element) => element?.addEventListener("change", render));
    render();
  };

  if (window.loadGoogleMapsScriptOnce) {
    window.loadGoogleMapsScriptOnce("initOperationsMap");
  } else if (window.google?.maps) {
    window.initOperationsMap();
  }
})();
