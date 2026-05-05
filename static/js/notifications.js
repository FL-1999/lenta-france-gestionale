document.addEventListener("DOMContentLoaded", () => {
  const container = document.querySelector("[data-notifications]");
  const toggle = document.getElementById("notificationsToggle");
  const panel = document.getElementById("notificationsPanel");
  const badge = document.getElementById("notificationCount");
  const list = document.getElementById("notificationsList") || container?.querySelector("[data-notifications-list]");
  const emptyState = container?.querySelector("[data-notifications-empty]");
  const markAllButton = container?.querySelector("[data-notifications-mark-all]");

  if (!container || !toggle || !panel || !badge || !list || !emptyState) return;

  const countEndpoint = container.dataset.countEndpoint || "/api/notifications/unread-count";
  const listEndpoint = container.dataset.listEndpoint || "/api/notifications/list";
  const markReadEndpoint = container.dataset.markReadEndpoint || "/api/notifications/mark-read";
  const pollInterval = Number(container.dataset.pollInterval || 30000);

  const getUnreadCount = (payload) => {
    const raw = payload?.count ?? payload?.unread_count ?? 0;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const setBadge = (count) => {
    const safeCount = Number.isFinite(Number(count)) ? Number(count) : 0;
    badge.textContent = String(safeCount);
    badge.setAttribute("aria-label", `${safeCount} notifiche non lette`);
  };

  const setMarkAllState = (hasUnread) => {
    if (!markAllButton) return;
    markAllButton.disabled = !hasUnread;
    markAllButton.classList.toggle("is-disabled", !hasUnread);
  };

  const isPanelOpen = () => !panel.classList.contains("hidden");

  const closePanel = () => {
    panel.classList.add("hidden");
    toggle.setAttribute("aria-expanded", "false");
  };

  const openPanel = () => {
    panel.classList.remove("hidden");
    toggle.setAttribute("aria-expanded", "true");
  };

  const updateNotificationBadge = async () => {
    try {
      const response = await fetch(countEndpoint, { credentials: "same-origin" });
      if (!response.ok) return;
      const payload = await response.json();
      const unreadCount = getUnreadCount(payload);
      setBadge(unreadCount);
      setMarkAllState(unreadCount > 0);
    } catch (_error) {
      // silent fail
    }
  };

  const renderNotifications = (payload) => {
    const notifications = payload?.notifications || [];
    const unreadCount = getUnreadCount(payload);

    setBadge(unreadCount);
    setMarkAllState(unreadCount > 0);
    list.innerHTML = "";

    if (!notifications.length) {
      emptyState.textContent = "Nessuna notifica";
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
        } catch (_error) {
          // silent fail
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

  const loadNotificationsList = async () => {
    try {
      const response = await fetch(listEndpoint, { credentials: "same-origin" });
      if (!response.ok) return;
      const payload = await response.json();
      renderNotifications(payload);
    } catch (_error) {
      // silent fail
    }
  };

  toggle.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();

    if (isPanelOpen()) {
      closePanel();
      return;
    }

    openPanel();
    loadNotificationsList();
    updateNotificationBadge();
  });

  panel.addEventListener("click", (event) => {
    event.stopPropagation();
  });

  document.addEventListener("click", () => {
    if (isPanelOpen()) closePanel();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isPanelOpen()) closePanel();
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
        const markPayload = await response.json();
        const unreadCountAfterMarkAll = getUnreadCount(markPayload);
        setBadge(unreadCountAfterMarkAll);
        setMarkAllState(unreadCountAfterMarkAll > 0);

        list.querySelectorAll(".notifications-panel__item").forEach((item) => item.classList.remove("is-unread"));
        if (!list.children.length) {
          emptyState.textContent = "Nessuna notifica";
          emptyState.classList.remove("is-hidden");
        }

        updateNotificationBadge();
      } catch (_error) {
        // silent fail
      }
    });
  }

  closePanel();
  updateNotificationBadge();
  if (pollInterval > 0) setInterval(updateNotificationBadge, pollInterval);
});
