(() => {
  window.initMap = () => {
    if (typeof window.initPlaceFormMaps === "function") {
      window.initPlaceFormMaps();
    }
  };

  window.refreshCantiereFormMap = () => {
    if (typeof window.refreshPlaceFormMaps === "function") {
      window.refreshPlaceFormMaps();
    }
  };
})();
