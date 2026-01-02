window.initMap = function initMap() {
    const config = window.cantieriMapConfig;
    if (!config) {
        return;
    }

    const mapElement = document.getElementById(config.elementId);
    if (!mapElement || !window.google || !window.google.maps) {
        return;
    }

    const sites = Array.isArray(config.sites) ? config.sites : [];
    const map = new google.maps.Map(mapElement, {
        mapTypeControl: false,
        fullscreenControl: false,
        ...(config.mapOptions || {})
    });
    const bounds = new google.maps.LatLngBounds();
    const infoWindow = new google.maps.InfoWindow();
    const markers = [];
    let hasMarkers = false;

    const statusColors = {
        aperto: "green",
        chiuso: "red",
        pianificato: "yellow"
    };

    const getMarkerIcon = (site) => {
        if (!config.coloredMarkers) {
            return null;
        }
        const statusKey = (site.status || "").toLowerCase();
        const color = statusColors[statusKey] || "blue";
        return {
            url: `https://maps.google.com/mapfiles/ms/icons/${color}-dot.png`
        };
    };

    const buildInfoWindowContent = (site, detailUrl) => {
        const addressHtml = site.address
            ? `<div class="map-infowindow-address">${site.address}</div>`
            : "";
        const detailButton = detailUrl
            ? `<a href="${detailUrl}" class="btn btn-sm btn-secondary">Apri scheda</a>`
            : "";
        const directionsUrl = `https://www.google.com/maps/dir/?api=1&destination=${site.lat},${site.lng}`;

        return `
            <div class="map-infowindow">
                <div class="map-infowindow-title">${site.name}</div>
                ${addressHtml}
                <div class="map-infowindow-actions">
                    ${detailButton}
                    <a href="${directionsUrl}" class="btn btn-sm btn-primary" target="_blank" rel="noopener">Portami lì</a>
                </div>
            </div>
        `;
    };

    sites.forEach((site) => {
        if (!site || site.lat == null || site.lng == null) {
            return;
        }

        const position = { lat: site.lat, lng: site.lng };
        const marker = new google.maps.Marker({
            position,
            map,
            title: site.name,
            icon: getMarkerIcon(site) || undefined
        });
        const detailUrl = site.detail_url
            || (config.detailUrlTemplate
                ? config.detailUrlTemplate.replace("__SITE_ID__", site.id)
                : "");
        const infoContent = buildInfoWindowContent(site, detailUrl);

        marker.addListener("click", () => {
            if (detailUrl) {
                window.location.assign(detailUrl);
            }
        });

        marker.addListener("mouseover", () => {
            infoWindow.setContent(infoContent);
            infoWindow.open(map, marker);
        });

        marker.addListener("mouseout", () => {
            infoWindow.close();
        });

        markers.push({ marker, site });
        bounds.extend(position);
        hasMarkers = true;
    });

    if (hasMarkers) {
        map.fitBounds(bounds);
    } else {
        map.setCenter(config.emptyMapCenter || { lat: 46.2276, lng: 2.2137 });
        map.setZoom(config.emptyMapZoom || 6);
    }

    let markerCluster = null;
    if (config.clustering && window.markerClusterer && window.markerClusterer.MarkerClusterer) {
        markerCluster = new window.markerClusterer.MarkerClusterer({
            map,
            markers: markers.map((entry) => entry.marker)
        });
    }

    if (config.filters) {
        const statusSelect = document.getElementById("map-filter-status");
        const caposquadraSelect = document.getElementById("map-filter-caposquadra");
        const activeSelect = document.getElementById("map-filter-active");

        const populateOptions = (select, values) => {
            if (!select) {
                return;
            }
            const existingValues = new Set(
                Array.from(select.options).map((option) => option.value)
            );
            values.forEach((value) => {
                if (!value || existingValues.has(String(value))) {
                    return;
                }
                const option = document.createElement("option");
                option.value = value;
                option.textContent = value;
                select.appendChild(option);
                existingValues.add(String(value));
            });
        };

        populateOptions(
            statusSelect,
            sites.map((site) => site.status).filter(Boolean)
        );
        populateOptions(
            caposquadraSelect,
            sites.map((site) => site.caposquadra_name).filter(Boolean)
        );

        const applyFilters = () => {
            const statusValue = statusSelect ? statusSelect.value : "";
            const caposquadraValue = caposquadraSelect ? caposquadraSelect.value : "";
            const activeValue = activeSelect ? activeSelect.value : "";

            const filteredMarkers = markers.filter(({ site }) => {
                if (statusValue && site.status !== statusValue) {
                    return false;
                }
                if (caposquadraValue && site.caposquadra_name !== caposquadraValue) {
                    return false;
                }
                if (activeValue) {
                    const isActive = Boolean(site.is_active);
                    if (activeValue === "true" && !isActive) {
                        return false;
                    }
                    if (activeValue === "false" && isActive) {
                        return false;
                    }
                }
                return true;
            });

            if (markerCluster) {
                markerCluster.clearMarkers();
                markerCluster.addMarkers(filteredMarkers.map((entry) => entry.marker));
                if (typeof markerCluster.render === "function") {
                    markerCluster.render();
                }
            } else {
                markers.forEach(({ marker }) => marker.setMap(null));
                filteredMarkers.forEach(({ marker }) => marker.setMap(map));
            }
        };

        [statusSelect, caposquadraSelect, activeSelect].forEach((select) => {
            if (!select) {
                return;
            }
            select.addEventListener("change", applyFilters);
        });
    }
};
