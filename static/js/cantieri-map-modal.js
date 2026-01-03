(() => {
    const modal = document.getElementById("cantieri-map-modal");
    const modalBody = document.getElementById("cantieri-map-modal-body");
    const wrapper = document.getElementById("cantieri-map-wrapper");
    const openButtons = document.querySelectorAll("[data-cantieri-map-open]");
    const closeButtons = modal ? modal.querySelectorAll("[data-cantieri-map-close]") : [];
    const externalButtons = document.querySelectorAll("[data-cantieri-map-external]");

    if (!modal || !modalBody || !wrapper || openButtons.length === 0) {
        return;
    }

    const mapElement = wrapper.querySelector("#cantieri-map");
    if (!mapElement) {
        return;
    }

    const originalParent = wrapper.parentElement;
    const originalNextSibling = wrapper.nextElementSibling;
    let scrollY = 0;

    const getMapState = () => window.cantieriMapState || null;

    const updateExternalButtons = () => {
        let url = "";
        const state = getMapState();
        if (state && state.map) {
            const center = state.map.getCenter();
            if (center) {
                url = `https://www.google.com/maps/search/?api=1&query=${center.lat()},${center.lng()}`;
            }
        }

        if (!url) {
            const config = window.cantieriMapConfig;
            const sites = Array.isArray(config?.sites) ? config.sites : [];
            const firstSite = sites.find((site) => Number.isFinite(Number(site?.lat)) && Number.isFinite(Number(site?.lng)));
            if (firstSite) {
                url = `https://www.google.com/maps/search/?api=1&query=${firstSite.lat},${firstSite.lng}`;
            }
        }

        if (!url) {
            url = "https://www.google.com/maps";
        }

        externalButtons.forEach((button) => {
            button.setAttribute("data-google-maps-url", url);
        });
    };

    const openExternal = (event) => {
        event.preventDefault();
        const url = event.currentTarget.getAttribute("data-google-maps-url");
        if (url) {
            window.open(url, "_blank", "noopener");
        }
    };

    const lockScroll = () => {
        scrollY = window.scrollY || 0;
        document.body.classList.add("map-modal-open");
        document.body.style.top = `-${scrollY}px`;
    };

    const unlockScroll = () => {
        document.body.classList.remove("map-modal-open");
        document.body.style.top = "";
        window.scrollTo(0, scrollY);
    };

    const moveWrapperToModal = () => {
        modalBody.appendChild(wrapper);
        mapElement.classList.add("cantieri-map--fullscreen");
        mapElement.classList.remove("cantieri-map--preview");
    };

    const restoreWrapper = () => {
        if (!originalParent) {
            return;
        }
        if (originalNextSibling) {
            originalParent.insertBefore(wrapper, originalNextSibling);
        } else {
            originalParent.appendChild(wrapper);
        }
        mapElement.classList.remove("cantieri-map--fullscreen");
        mapElement.classList.add("cantieri-map--preview");
    };

    const resizeMap = () => {
        const state = getMapState();
        if (!state || !state.map || !window.google?.maps) {
            return;
        }
        const currentCenter = state.map.getCenter();
        const currentZoom = state.map.getZoom();
        window.google.maps.event.trigger(state.map, "resize");
        if (currentCenter) {
            state.map.setCenter(currentCenter);
        } else if (state.defaultCenter) {
            state.map.setCenter(state.defaultCenter);
        }
        if (Number.isFinite(currentZoom)) {
            state.map.setZoom(currentZoom);
        } else if (state.defaultZoom) {
            state.map.setZoom(state.defaultZoom);
        }
    };

    const openModal = () => {
        modal.classList.add("is-visible");
        modal.setAttribute("aria-hidden", "false");
        lockScroll();
        moveWrapperToModal();
        updateExternalButtons();
        resizeMap();
    };

    const closeModal = () => {
        modal.classList.remove("is-visible");
        modal.setAttribute("aria-hidden", "true");
        restoreWrapper();
        unlockScroll();
        updateExternalButtons();
        resizeMap();
    };

    openButtons.forEach((button) => button.addEventListener("click", openModal));
    closeButtons.forEach((button) => button.addEventListener("click", closeModal));
    modal.addEventListener("click", (event) => {
        if (event.target === modal) {
            closeModal();
        }
    });

    externalButtons.forEach((button) => {
        button.addEventListener("click", openExternal);
    });

    window.addEventListener("resize", () => {
        if (modal.classList.contains("is-visible")) {
            resizeMap();
        }
    });

    updateExternalButtons();
})();
