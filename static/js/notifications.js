document.addEventListener("DOMContentLoaded", () => {
  const container = document.querySelector("[data-notifications]");
  if (!container) return;

  const toggle = container.querySelector("[data-notifications-toggle]");
  const panel = container.querySelector("[data-notifications-panel]");
  const list = container.querySelector("[data-notifications-list]");
  const emptyState = container.querySelector("[data-notifications-empty]");
  const badge = container.querySelector("#notificationBadge");
  const countEndpoint =
    container.dataset.countEndpoint || "/api/notifications/unread-count";
  const listEndpoint = container.dataset.listEndpoint || "/api/notifications/list";
  const markReadEndpoint =
    container.dataset.markReadEndpoint || "/api/notifications/mark-read";
  const pollInterval = Number(container.dataset.pollInterval || 30000);
  const markAllButton = container.querySelector("[data-notifications-mark-all]");

  if (!toggle || !panel || !list || !emptyState || !badge) return;

  const getUnreadCount = (payload) => {
    const raw = payload?.count ?? payload?.unread_count ?? 0;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const setBadge = (count) => {
    const safeCount = Number.isFinite(Number(count)) ? Number(count) : 0;
    if (safeCount > 0) {
      badge.textContent = String(safeCount);
      badge.style.display = "flex";
      badge.setAttribute("aria-label", `${safeCount} notifiche non lette`);
    } else {
      badge.textContent = "0";
      badge.style.display = "none";
      badge.removeAttribute("aria-label");
    }
  };

  const updateNotificationBadge = async () => {
    try {
      const response = await fetch(countEndpoint, { credentials: "same-origin" });
      if (!response.ok) return;
      const payload = await response.json();
      const unreadCount = getUnreadCount(payload);
      setBadge(unreadCount);
      setMarkAllState(unreadCount > 0);
    } catch (error) {
      console.error("Notifications count failed", error);
    }
  };

  const setMarkAllState = (hasUnread) => {
    if (!markAllButton) return;
    markAllButton.disabled = !hasUnread;
    markAllButton.classList.toggle("is-disabled", !hasUnread);
  };

  const renderNotifications = (payload) => {
    const notifications = payload?.notifications || [];
    const unreadCount = getUnreadCount(payload);
    setBadge(unreadCount);
    setMarkAllState(unreadCount > 0);

    list.innerHTML = "";
    if (!notifications.length) {
      emptyState.classList.remove("is-hidden");
      return;
    }

    emptyState.classList.add("is-hidden");
    notifications.forEach((notification) => {
      const item = document.createElement("li");
      item.className = "notifications-panel__item";
      if (!notification.read) item.classList.add("is-unread");

      const link = document.createElement("a");
      link.className = "notifications-panel__link";
      link.href = notification.link_url || "#";
      link.textContent = notification.message;

      link.addEventListener("click", async (event) => {
        if (!notification.link_url) event.preventDefault();
        if (notification.read) return;
        try {
          const response = await fetch(markReadEndpoint, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ notification_id: notification.id }),
          });
          if (!response.ok) return;
          const markPayload = await response.json();
          const unreadCountAfterMark = getUnreadCount(markPayload);
          notification.read = true;
          item.classList.remove("is-unread");
          setBadge(unreadCountAfterMark);
          setMarkAllState(unreadCountAfterMark > 0);
        } catch (error) {
          console.error("Notification read failed", error);
        }
      });

      const meta = document.createElement("span");
      meta.className = "notifications-panel__meta";
      const date = new Date(notification.created_at);
      meta.textContent = Number.isNaN(date.getTime()) ? "" : date.toLocaleString();

      item.appendChild(link);
      if (meta.textContent) item.appendChild(meta);
      list.appendChild(item);
    });
  };

  const fetchNotifications = async () => {
    try {
      const response = await fetch(listEndpoint, { credentials: "same-origin" });
      if (!response.ok) return;
      const payload = await response.json();
      renderNotifications(payload);
    } catch (error) {
      console.error("Notifications polling failed", error);
    }
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const isOpen = panel.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) {
      fetchNotifications();
      updateNotificationBadge();
    }
  });

  document.addEventListener("click", (event) => {
    if (!container.contains(event.target)) {
      panel.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    }
  });

  if (markAllButton) {
    markAllButton.addEventListener("click", async (event) => {
      event.preventDefault();
      try {
        const response = await fetch(markReadEndpoint, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mark_all: true }),
        });
        if (!response.ok) return;
        await response.json();
        fetchNotifications();
        updateNotificationBadge();
      } catch (error) {
        console.error("Notifications mark all failed", error);
      }
    });
  }

  updateNotificationBadge();
  fetchNotifications();
  if (pollInterval > 0) setInterval(updateNotificationBadge, pollInterval);
});
