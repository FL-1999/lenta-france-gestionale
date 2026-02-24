(() => {
  const parseCoordinate = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const init = () => {
    const openBtn = document.getElementById("open-depots-map");
    const modal = document.getElementById("depot-map-modal");
    const mapEl = document.getElementById("depot-map-canvas");
    const message = document.getElementById("depot-map-message");
    if (!openBtn || !modal || !mapEl || !message) return;

    let map = null;
    const markers = [];

    const closeModal = () => {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
    };

    const openModal = () => {
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    };

    const loadDepots = () => {
      const rows = [...document.querySelectorAll("[data-depot-item]")];
      return rows
        .map((row) => ({
          name: row.getAttribute("data-name") || "Deposito",
          lat: parseCoordinate(row.getAttribute("data-lat")),
          lng: parseCoordinate(row.getAttribute("data-lng")),
        }))
        .filter((item) => item.lat !== null && item.lng !== null);
    };

    const drawMap = (depots) => {
      if (!window.google || !window.google.maps) {
        message.textContent = "Mappa non disponibile";
        message.style.display = "block";
        mapEl.style.display = "none";
        return;
      }

      message.style.display = "none";
      mapEl.style.display = "block";

      if (!map) {
        map = new window.google.maps.Map(mapEl, {
          center: { lat: depots[0].lat, lng: depots[0].lng },
          zoom: 8,
          mapTypeControl: false,
          streetViewControl: false,
        });
      }

      markers.forEach((marker) => marker.setMap(null));
      markers.length = 0;

      const bounds = new window.google.maps.LatLngBounds();
      depots.forEach((depot) => {
        const marker = new window.google.maps.Marker({
          map,
          position: { lat: depot.lat, lng: depot.lng },
          title: depot.name,
          icon: "http://maps.google.com/mapfiles/ms/icons/blue-dot.png",
        });
        markers.push(marker);
        bounds.extend(marker.getPosition());
      });
      map.fitBounds(bounds);
    };

    openBtn.addEventListener("click", () => {
      const depots = loadDepots();
      openModal();
      if (depots.length === 0) {
        message.textContent = "Nessun deposito con coordinate disponibili";
        message.style.display = "block";
        mapEl.style.display = "none";
        return;
      }
      drawMap(depots);
    });

    modal.querySelectorAll("[data-depot-map-close]").forEach((button) => {
      button.addEventListener("click", closeModal);
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
