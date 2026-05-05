document.addEventListener("DOMContentLoaded", () => {
  console.log("notifications js loaded");

  const toggle = document.getElementById("notificationsToggle");
  const panel = document.getElementById("notificationsPanel");
  const notificationCount = document.getElementById("notificationCount");
  if (!toggle || !panel || !notificationCount) return;

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

  toggle.addEventListener("click", () => {
    console.log("toggle clicked");
    panel.classList.toggle("hidden");
  });

  updateNotificationCount();
  setInterval(updateNotificationCount, 30000);
});
