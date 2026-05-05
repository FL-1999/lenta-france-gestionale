document.addEventListener("DOMContentLoaded", () => {
  console.log("notifications js loaded");

  const toggle = document.getElementById("notificationsToggle");
  const panel = document.getElementById("notificationsPanel");
  const notificationCount = document.getElementById("notificationCount");
  if (!toggle || !panel || !notificationCount) return;

  const isOpen = () => !panel.classList.contains("hidden");

  const openPanel = () => {
    panel.classList.remove("hidden");
    panel.classList.add("open");
    toggle.setAttribute("aria-expanded", "true");
  };

  const closePanel = () => {
    panel.classList.add("hidden");
    panel.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  };

  const updateNotificationCount = async () => {
    try {
      const response = await fetch("/api/notifications/unread-count", { credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();
      const count = Number(data?.count ?? data?.unread_count ?? 0);
      const safeCount = Number.isFinite(count) ? count : 0;
      console.log("unread count:", safeCount);
      notificationCount.textContent = String(safeCount);
    } catch (_error) {
      // silent fail
    }
  };

  toggle.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();

    if (isOpen()) {
      closePanel();
    } else {
      openPanel();
    }
  });

  panel.addEventListener("click", (event) => {
    event.stopPropagation();
  });

  document.addEventListener("click", () => {
    if (isOpen()) closePanel();
  });

  updateNotificationCount();
  setInterval(updateNotificationCount, 30000);
});
