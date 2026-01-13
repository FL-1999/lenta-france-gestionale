(() => {
  const stepper = document.querySelector("[data-cantiere-stepper]");
  if (!stepper) {
    return;
  }

  const form = stepper.closest("form");
  if (!form) {
    return;
  }

  const steps = Array.from(form.querySelectorAll(".cantiere-step"));
  const stepItems = Array.from(stepper.querySelectorAll(".cantiere-stepper-item"));
  const prevButton = form.querySelector('[data-step-action="prev"]');
  const nextButton = form.querySelector('[data-step-action="next"]');
  const mobileMedia = window.matchMedia("(max-width: 768px)");

  if (!steps.length) {
    return;
  }

  let currentIndex = 0;

  const getStepIndex = (step) => Number.parseInt(step.dataset.stepIndex || "0", 10);

  const isMobile = () => mobileMedia.matches;

  const ensureAllVisible = () => {
    steps.forEach((step) => step.classList.add("is-active"));
  };

  const validateCurrentStep = () => {
    const step = steps[currentIndex];
    if (!step) {
      return true;
    }
    const fields = Array.from(step.querySelectorAll("input, select, textarea"));
    for (const field of fields) {
      if (!field.willValidate) {
        continue;
      }
      if (field.checkValidity()) {
        continue;
      }
      if (typeof field.reportValidity === "function") {
        field.reportValidity();
      }
      return false;
    }
    return true;
  };

  const refreshMap = () => {
    if (typeof window.refreshCantiereFormMap === "function") {
      window.setTimeout(() => {
        window.refreshCantiereFormMap();
      }, 80);
    }
  };

  const loadMapIfNeeded = () => {
    const currentStep = steps[currentIndex];
    if (!currentStep || currentStep.dataset.step !== "2") {
      return;
    }
    const mapElement = document.getElementById("cantiere-pick-map");
    if (!mapElement) {
      return;
    }
    if (typeof window.initMap === "function") {
      window.initMap();
    }
  };

  const updateStepper = () => {
    if (!isMobile()) {
      ensureAllVisible();
      loadMapIfNeeded();
      return;
    }

    steps.forEach((step, index) => {
      step.classList.toggle("is-active", index === currentIndex);
    });

    stepItems.forEach((item) => {
      const index = getStepIndex(item);
      item.classList.toggle("is-active", index === currentIndex);
      item.classList.toggle("is-complete", index < currentIndex);
    });

    if (prevButton) {
      prevButton.disabled = currentIndex === 0;
    }
    if (nextButton) {
      nextButton.disabled = currentIndex === steps.length - 1;
    }

    const currentStep = steps[currentIndex];
    if (currentStep && currentStep.dataset.step === "2") {
      loadMapIfNeeded();
      refreshMap();
    }
  };

  const goToStep = (index) => {
    if (index < 0 || index >= steps.length) {
      return;
    }
    if (index > currentIndex && !validateCurrentStep()) {
      return;
    }
    currentIndex = index;
    updateStepper();
  };

  if (prevButton) {
    prevButton.addEventListener("click", () => {
      goToStep(currentIndex - 1);
    });
  }

  if (nextButton) {
    nextButton.addEventListener("click", () => {
      goToStep(currentIndex + 1);
    });
  }

  stepItems.forEach((item) => {
    item.addEventListener("click", () => {
      const index = getStepIndex(item);
      if (index <= currentIndex) {
        goToStep(index);
      } else {
        goToStep(index);
      }
    });
  });

  mobileMedia.addEventListener("change", () => {
    updateStepper();
  });

  updateStepper();
})();
