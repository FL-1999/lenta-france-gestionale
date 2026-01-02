function initCantieriMap(containerId, cantieriData, options = {}) {
    const mapElement = document.getElementById(containerId);
    if (!mapElement || !window.google || !window.google.maps) {
        return null;
    }

    const map = new google.maps.Map(mapElement, {
        mapTypeControl: false,
        fullscreenControl: false,
        ...(options.mapOptions || {})
    });
    const bounds = new google.maps.LatLngBounds();
    const infoWindow = new google.maps.InfoWindow();
    const detailUrlTemplate = options.detailUrlTemplate || null;
    const detailLabel = options.detailLabel || "Apri scheda";
    const directionsLabel = options.directionsLabel || "Portami lì";
    const showDirections = options.showDirections !== false;
    let hasMarkers = false;

    (cantieriData || []).forEach((site) => {
        if (!site || site.lat == null || site.lng == null) {
            return;
        }

        const position = { lat: site.lat, lng: site.lng };
        const marker = new google.maps.Marker({
            position,
            map,
            title: site.name
        });
        bounds.extend(position);
        hasMarkers = true;

        const actions = [];
        if (detailUrlTemplate) {
            const detailUrl = detailUrlTemplate.replace("__SITE_ID__", site.id);
            actions.push(`<a href="${detailUrl}" class="btn btn-sm btn-secondary">${detailLabel}</a>`);
        }
        if (showDirections) {
            const directionsUrl = `https://www.google.com/maps/dir/?api=1&destination=${site.lat},${site.lng}`;
            actions.push(
                `<a href="${directionsUrl}" class="btn btn-sm btn-primary" target="_blank" rel="noopener">${directionsLabel}</a>`
            );
        }

        const indirizzo = site.address
            ? `<div class="map-infowindow-address">${site.address}</div>`
            : "";
        const actionsHtml = actions.length
            ? `<div class="map-infowindow-actions">${actions.join("")}</div>`
            : "";
        const content = `
            <div class="map-infowindow">
                <div class="map-infowindow-title">${site.name}</div>
                ${indirizzo}
                ${actionsHtml}
            </div>
        `;

        marker.addListener("click", () => {
            infoWindow.setContent(content);
            infoWindow.open(map, marker);
        });
    });

    if (hasMarkers) {
        map.fitBounds(bounds);
    } else {
        const defaultCenter = options.emptyMapCenter || { lat: 46.2276, lng: 2.2137 };
        map.setCenter(defaultCenter);
        map.setZoom(options.emptyMapZoom || 6);
    }

    return map;
}
