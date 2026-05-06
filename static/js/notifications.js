document.addEventListener("DOMContentLoaded", () => {
  const container = document.querySelector("[data-notifications]");
  const toggle = document.getElementById("notificationsToggle");
  const panel = document.getElementById("notificationsPanel");
  const badge = document.getElementById("notificationCount");
  const list = document.getElementById("notificationsList") || container?.querySelector("[data-notifications-list]");
  const markAllButton = container?.querySelector("[data-notifications-mark-all]");
  const clearAllButton = container?.querySelector("[data-notifications-clear-all]");

  if (!container || !toggle || !panel || !badge || !list) return;

  const countEndpoint = container.dataset.countEndpoint || "/api/notifications/unread-count";
  const listEndpoint = container.dataset.listEndpoint || "/api/notifications/recent";
  const markReadEndpoint = container.dataset.markReadEndpoint || "/api/notifications/mark-read";
  const clearAllEndpoint = container.dataset.clearAllEndpoint || "/api/notifications/clear-all";
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

  const setClearAllState = (hasNotifications) => {
    if (!clearAllButton) return;
    clearAllButton.disabled = !hasNotifications;
    clearAllButton.classList.toggle("is-disabled", !hasNotifications);
  };

  const isPanelOpen = () => !panel.classList.contains("hidden");
  const closePanel = () => { panel.classList.add("hidden"); toggle.setAttribute("aria-expanded", "false"); };
  const openPanel = () => { panel.classList.remove("hidden"); toggle.setAttribute("aria-expanded", "true"); };

  const updateNotificationBadge = async () => {
    try {
      const response = await fetch(countEndpoint, { credentials: "same-origin" });
      if (!response.ok) return;
      const payload = await response.json();
      const unreadCount = getUnreadCount(payload);
      setBadge(unreadCount);
      setMarkAllState(unreadCount > 0);
    } catch (_error) {}
  };

  const renderNotifications = (payload) => {
    const notifications = Array.isArray(payload?.notifications) ? payload.notifications : [];
    list.innerHTML = "";

    if (!notifications.length) {
      list.innerHTML = '<div class="notification-empty">Nessuna notifica</div>';
      setClearAllState(false);
      return;
    }

    setClearAllState(true);

    notifications.forEach((notification) => {
      const isRead = Boolean(notification.is_read ?? notification.read);
      const linkUrl = notification.url || notification.link_url || null;

      const item = document.createElement("div");
      item.className = "notification-item";
      item.dataset.notificationId = notification.id;
      item.dataset.read = String(isRead);
      if (!isRead) item.classList.add("is-unread");

      const text = document.createElement(linkUrl ? "a" : "div");
      if (linkUrl) {
        text.href = linkUrl;
        text.className = "notifications-panel__link";
      }
      text.textContent = notification.message || "Notifica";

      text.addEventListener("click", async (event) => {
        if (!linkUrl) event.preventDefault();
        if (item.dataset.read === "true") return;
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
          item.classList.remove("is-unread");
          item.classList.add("is-read");
          item.dataset.read = "true";
          setBadge(unreadCountAfterMark);
          setMarkAllState(unreadCountAfterMark > 0);
        } catch (_error) {}
      });

      const meta = document.createElement("div");
      meta.className = "notifications-panel__meta";
      meta.textContent = notification.created_at || "";

      item.appendChild(text);
      if (meta.textContent) item.appendChild(meta);
      list.appendChild(item);
    });
  };


  const markAllAsRead = async ({ refreshList = false } = {}) => {
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
      list.querySelectorAll(".notification-item.is-unread").forEach((item) => {
        item.classList.remove("is-unread");
        item.classList.add("is-read");
        item.dataset.read = "true";
      });
      if (refreshList) loadNotificationsList({ markOnOpen: false });
    } catch (_error) {}
  };

  const loadNotificationsList = async ({ markOnOpen = false } = {}) => {
    list.innerHTML = '<div class="notification-empty">Caricamento notifiche...</div>';
    try {
      const response = await fetch(listEndpoint, { credentials: "same-origin" });
      if (!response.ok) {
        list.innerHTML = '<div class="notification-empty">Errore caricamento notifiche</div>';
        return;
      }
      let payload;
      try {
        payload = await response.json();
      } catch (_parseError) {
        list.innerHTML = '<div class="notification-empty">Errore caricamento notifiche</div>';
        return;
      }

      if (!payload || typeof payload !== "object" || !Array.isArray(payload.notifications)) {
        list.innerHTML = '<div class="notification-empty">Errore caricamento notifiche</div>';
        return;
      }

      renderNotifications(payload);
      const unreadCount = getUnreadCount(payload);
      setBadge(unreadCount);
      setMarkAllState(unreadCount > 0);
      if (markOnOpen && unreadCount > 0) markAllAsRead();
    } catch (_error) {
      list.innerHTML = '<div class="notification-empty">Errore caricamento notifiche</div>';
    }
  };

  toggle.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (isPanelOpen()) return closePanel();
    openPanel();
    loadNotificationsList({ markOnOpen: true });
  });

  panel.addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", () => { if (isPanelOpen()) closePanel(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && isPanelOpen()) closePanel(); });

  if (markAllButton) {
    markAllButton.addEventListener("click", (event) => {
      event.preventDefault();
      markAllAsRead({ refreshList: true });
    });
  }

  if (clearAllButton) {
    clearAllButton.addEventListener("click", async (event) => {
      event.preventDefault();
      try {
        const response = await fetch(clearAllEndpoint, {
          method: "POST",
          credentials: "same-origin",
        });
        if (!response.ok) return;
        const payload = await response.json();
        setBadge(getUnreadCount(payload));
        setMarkAllState(false);
        setClearAllState(false);
        list.innerHTML = '<div class="notification-empty">Nessuna notifica</div>';
      } catch (_error) {}
    });
  }

  setClearAllState(false);
  closePanel();
  updateNotificationBadge();
  if (pollInterval > 0) setInterval(updateNotificationBadge, pollInterval);
});
