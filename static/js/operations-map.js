(() => {
  window.initOperationsMap = () => {
    const configEl = document.getElementById("cantieri-map-config");
    if (!configEl) return;

    // Lingua dal cookie (it default, fr) per tradurre etichette e popup della mappa.
    const _lang = (document.cookie.match(/(?:^|;\s*)lang=(it|fr)/) || [])[1] || "it";
    const _t = (it, fr) => (_lang === "fr" ? fr : it);

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
    const transportProgressColors = {
      green: "#16a34a",
      orange: "#f97316",
      red: "#dc2626",
      unknown: "#6b7280",
    };

    const legendItems = [
      [_t("Cantieri attivi", "Chantiers actifs"), icons.siteActive],
      [_t("Cantieri chiusi", "Chantiers fermés"), icons.siteClosed],
      [_t("Depositi", "Dépôts"), icons.depot],
      [_t("Trasporto · origine", "Transport · départ"), icons.transportOrigin],
      [_t("Trasporto · tappa", "Transport · étape"), icons.transportStop],
      [_t("Trasporto · destinazione", "Transport · destination"), icons.transportDestination],
      [_t("Avanzamento nei tempi", "Dans les temps"), "https://maps.google.com/mapfiles/ms/icons/green-dot.png"],
      [_t("Avanzamento quasi arrivo", "Presque arrivé"), "https://maps.google.com/mapfiles/ms/icons/orange-dot.png"],
      [_t("Avanzamento in ritardo", "En retard"), "https://maps.google.com/mapfiles/ms/icons/red-dot.png"],
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
      if (role === "origin") return _t("Origine", "Départ");
      if (role === "destination") return _t("Destinazione", "Destination");
      return _t("Tappa", "Étape");
    }

    function transportProgressIcon(progressColor) {
      const fillColor = transportProgressColors[progressColor] || transportProgressColors.unknown;
      return {
        path: window.google.maps.SymbolPath.CIRCLE,
        fillColor,
        fillOpacity: 1,
        strokeColor: "#ffffff",
        strokeWeight: 1.5,
        scale: 6,
      };
    }

    function infoHtml({ title, type, status, details, link }) {
      const items = (details || []).filter(Boolean).map((detail) => `<li>${detail}</li>`).join("");
      return `
        <div class="map-infowindow">
          <div class="map-infowindow-title">${title || "—"}</div>
          <div class="map-infowindow-address">${type || ""}${status ? ` · ${status}` : ""}</div>
          ${items ? `<ul class="map-infowindow-list">${items}</ul>` : ""}
          ${link ? `<div class="map-infowindow-actions"><a class="btn btn-primary btn-sm" href="${link}">${_t("Apri dettaglio", "Ouvrir le détail")}</a></div>` : ""}
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
              type: _t("Cantiere", "Chantier"),
              status: site.status || (isClosed ? _t("chiuso", "fermé") : _t("attivo", "actif")),
              details: [site.address, site.caposquadra_name ? `${_t("Caposquadra", "Chef d'équipe")}: ${site.caposquadra_name}` : null],
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
              type: _t("Deposito", "Dépôt"),
              status: depot.is_active ? _t("attivo", "actif") : _t("non attivo", "inactif"),
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
              const pointType = point.type === "depot" ? _t("Deposito", "Dépôt") : point.type === "site" ? _t("Cantiere", "Chantier") : _t("Punto", "Point");
              const progress = trip.progress || {};
              const _stima = _t("Stima non disponibile", "Estimation indisponible");
              const progressLabel =
                typeof progress.percent === "number" ? `${progress.percent}%` : _stima;
              addMarker({
                lat: point.lat,
                lng: point.lng,
                icon: transportProgressIcon(progress.color),
                html: infoHtml({
                  title: `${trip.code} · ${point.name || "—"}`,
                  type: `${_t("Trasporto", "Transport")} (${transportRoleLabel(point.role)})`,
                  status: trip.status,
                  details: [
                    pointType,
                    `${_t("Avanzamento", "Avancement")}: ${progressLabel}`,
                    progress.status_label || _stima,
                    progress.timing_text || _stima,
                    trip.driver_name ? `${_t("Autista", "Chauffeur")}: ${trip.driver_name}` : null,
                    trip.vehicle_name ? `${_t("Mezzo", "Véhicule")}: ${trip.vehicle_name}` : null,
                    trip.date ? `${_t("Data", "Date")}: ${trip.date}` : null,
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
