(function () {
    function buildInfoWindowContent(site, detailUrl) {
        const indirizzo = site.indirizzo
            ? `<div class="map-infowindow-address">${site.indirizzo}</div>`
            : "";
        const detailButton = detailUrl
            ? `<a href="${detailUrl}" class="btn btn-sm btn-secondary">Apri scheda</a>`
            : "";
        const directionsUrl = `https://www.google.com/maps/dir/?api=1&destination=${site.lat},${site.lng}`;

        return `
            <div class="map-infowindow">
                <div class="map-infowindow-title">${site.nome}</div>
                ${indirizzo}
                <div class="map-infowindow-actions">
                    ${detailButton}
                    <a href="${directionsUrl}" class="btn btn-sm btn-primary" target="_blank" rel="noopener">Portami lì</a>
                </div>
            </div>
        `;
    }

    window.initCantieriMap = function initCantieriMap() {
        const config = window.cantieriMapConfig;
        if (!config) {
            return;
        }

        const mapElement = document.getElementById(config.elementId);
        if (!mapElement) {
            return;
        }

        const map = new google.maps.Map(mapElement, {
            mapTypeControl: false,
            fullscreenControl: false
        });
        const bounds = new google.maps.LatLngBounds();
        const infoWindow = new google.maps.InfoWindow();
        const sites = Array.isArray(config.sites) ? config.sites : [];
        let hasLocations = false;

        sites.forEach((site) => {
            if (site.lat == null || site.lng == null) {
                return;
            }

            const position = { lat: site.lat, lng: site.lng };
            const marker = new google.maps.Marker({
                position,
                map,
                title: site.nome
            });
            bounds.extend(position);
            hasLocations = true;

            const detailUrl = site.detail_url
                || (config.detailUrlTemplate
                    ? config.detailUrlTemplate.replace("__SITE_ID__", site.id)
                    : "");
            const content = buildInfoWindowContent(site, detailUrl);

            marker.addListener("click", () => {
                infoWindow.setContent(content);
                infoWindow.open(map, marker);
            });
        });

        if (hasLocations) {
            map.fitBounds(bounds);
        } else {
            map.setCenter({ lat: 46.2276, lng: 2.2137 });
            map.setZoom(6);
        }
    };
})();
