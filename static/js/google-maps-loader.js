(() => {
  const loaderState = {
    promise: null,
    callbacks: new Set(),
    libraries: null,
  };

  const getApiKey = () => {
    const keyElement = document.querySelector("[data-google-maps-api-key]");
    return keyElement?.dataset?.googleMapsApiKey || "";
  };

  const runCallbacks = () => {
    loaderState.callbacks.forEach((callbackName) => {
      const callback = window[callbackName];
      if (typeof callback === "function") {
        callback();
      }
    });
    loaderState.callbacks.clear();
  };

  window.loadGoogleMapsScriptOnce = (callbackName, libraries = []) => {
    if (callbackName) {
      loaderState.callbacks.add(callbackName);
    }

    if (window.google?.maps) {
      runCallbacks();
      return Promise.resolve(true);
    }

    const apiKey = getApiKey();
    if (!apiKey) {
      return Promise.resolve(false);
    }

    if (loaderState.promise) {
      return loaderState.promise;
    }

    const libraryList = Array.isArray(libraries) ? libraries.filter(Boolean) : [];
    loaderState.libraries = libraryList;

    loaderState.promise = new Promise((resolve) => {
      window.__googleMapsLoaderCallback = () => {
        runCallbacks();
        resolve(true);
      };

      const params = new URLSearchParams({
        key: apiKey,
        callback: "__googleMapsLoaderCallback",
      });
      if (libraryList.length) {
        params.set("libraries", libraryList.join(","));
      }

      const script = document.createElement("script");
      script.src = `https://maps.googleapis.com/maps/api/js?${params.toString()}`;
      script.async = true;
      script.defer = true;
      script.onerror = () => {
        runCallbacks();
        resolve(false);
      };
      document.head.appendChild(script);
    });

    return loaderState.promise;
  };
})();
