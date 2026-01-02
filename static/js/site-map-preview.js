(() => {
  const parseCoordinate = (value) => {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const init = () => {
    const modal = document.getElementById("site-map-preview-modal");
    const mapContainer = document.getElementById("site-preview-map");
    const message = document.getElementById("site-preview-message");
    const title = document.getElementById("site-preview-title");

    if (!modal || !mapContainer || !message || !title) {
      return;
    }

    let map = null;
    let marker = null;

    const openModal = () => {
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
    };

    const closeModal = () => {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
    };

    const hideMap = () => {
      mapContainer.style.display = "none";
    };

    const showMap = () => {
      mapContainer.style.display = "block";
    };

    const showMessage = (text) => {
      message.textContent = text;
      message.style.display = "block";
    };

    const hideMessage = () => {
      message.style.display = "none";
    };

    const updateMap = (position) => {
      if (!window.google || !window.google.maps) {
        showMessage("Mappa non disponibile");
        hideMap();
        return;
      }

      if (!map) {
        map = new window.google.maps.Map(mapContainer, {
          center: position,
          zoom: 15,
          mapTypeControl: false,
          streetViewControl: false,
        });
        marker = new window.google.maps.Marker({
          map,
          position,
        });
      } else {
        map.setCenter(position);
        if (marker) {
          marker.setPosition(position);
        } else {
          marker = new window.google.maps.Marker({
            map,
            position,
          });
        }
        window.google.maps.event.trigger(map, "resize");
      }
    };

    const openPreview = (button) => {
      const siteName = button.getAttribute("data-site-name") || "Cantiere";
      const lat = parseCoordinate(button.getAttribute("data-lat"));
      const lng = parseCoordinate(button.getAttribute("data-lng"));
      const hasCoordinates = lat !== null && lng !== null;

      title.textContent = `📍 ${siteName}`;
      openModal();

      if (!hasCoordinates) {
        showMessage("Posizione non impostata");
        hideMap();
        return;
      }

      hideMessage();
      showMap();
      updateMap({ lat, lng });
    };

    document.querySelectorAll(".btn-site-map").forEach((button) => {
      button.addEventListener("click", () => openPreview(button));
    });

    modal.querySelectorAll("[data-site-map-close]").forEach((button) => {
      button.addEventListener("click", closeModal);
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
