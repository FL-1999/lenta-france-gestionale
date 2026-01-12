(function () {
  const container = document.querySelector("[data-notifications]");
  if (!container) {
    return;
  }

  const toggle = container.querySelector("[data-notifications-toggle]");
  const panel = container.querySelector("[data-notifications-panel]");
  const list = container.querySelector("[data-notifications-list]");
  const emptyState = container.querySelector("[data-notifications-empty]");
  const badge = container.querySelector("[data-notifications-badge]");
  const countEndpoint =
    container.dataset.countEndpoint || "/api/notifications/unread-count";
  const listEndpoint = container.dataset.listEndpoint || "/api/notifications/list";
  const markReadEndpoint =
    container.dataset.markReadEndpoint || "/api/notifications/mark-read";
  const pollInterval = Number(container.dataset.pollInterval || 30000);
  const markAllButton = container.querySelector(
    "[data-notifications-mark-all]"
  );

  if (!toggle || !panel || !list || !emptyState || !badge) {
    return;
  }

  const formatDateTime = (value) => {
    if (!value) {
      return "";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    return date.toLocaleString();
  };

  const setBadge = (count) => {
    if (count > 0) {
      badge.textContent = count > 99 ? "99+" : String(count);
      badge.classList.remove("is-hidden");
    } else {
      badge.textContent = "";
      badge.classList.add("is-hidden");
    }
  };

  const setMarkAllState = (hasUnread) => {
    if (!markAllButton) {
      return;
    }
    markAllButton.disabled = !hasUnread;
    markAllButton.classList.toggle("is-disabled", !hasUnread);
  };

  const renderNotifications = (payload) => {
    const notifications = payload?.notifications || [];
    const unreadCount = payload?.unread_count || 0;
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
      if (!notification.read) {
        item.classList.add("is-unread");
      }

      const link = document.createElement("a");
      link.className = "notifications-panel__link";
      link.href = notification.link_url || "#";
      link.textContent = notification.message;

      const meta = document.createElement("span");
      meta.className = "notifications-panel__meta";
      meta.textContent = formatDateTime(notification.created_at);

      link.addEventListener("click", async (event) => {
        if (!notification.link_url) {
          event.preventDefault();
        }
        try {
          if (notification.read) {
            return;
          }
          const response = await fetch(markReadEndpoint, {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ notification_id: notification.id }),
          });
          if (response.ok) {
            const payload = await response.json();
            notification.read = true;
            item.classList.remove("is-unread");
            setBadge(payload.unread_count || 0);
            setMarkAllState((payload.unread_count || 0) > 0);
          }
        } catch (error) {
          console.error("Notification read failed", error);
        }
      });

      item.appendChild(link);
      if (meta.textContent) {
        item.appendChild(meta);
      }
      list.appendChild(item);
    });
  };

  const fetchNotifications = async () => {
    try {
      const response = await fetch(listEndpoint, { credentials: "same-origin" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      renderNotifications(payload);
    } catch (error) {
      console.error("Notifications polling failed", error);
    }
  };

  const fetchUnreadCount = async () => {
    try {
      const response = await fetch(countEndpoint, {
        credentials: "same-origin",
      });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      const unreadCount = payload?.unread_count || 0;
      setBadge(unreadCount);
      setMarkAllState(unreadCount > 0);
    } catch (error) {
      console.error("Notifications count failed", error);
    }
  };

  const markAllAsRead = async () => {
    try {
      const response = await fetch(markReadEndpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ mark_all: true }),
      });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      setBadge(payload?.unread_count || 0);
      setMarkAllState((payload?.unread_count || 0) > 0);
      fetchNotifications();
    } catch (error) {
      console.error("Notifications mark all failed", error);
    }
  };

  const closePanel = () => {
    panel.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
  };

  const openPanel = () => {
    panel.classList.add("is-open");
    toggle.setAttribute("aria-expanded", "true");
    fetchNotifications();
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    if (panel.classList.contains("is-open")) {
      closePanel();
      return;
    }
    openPanel();
  });

  document.addEventListener("click", (event) => {
    if (!container.contains(event.target)) {
      closePanel();
    }
  });

  if (markAllButton) {
    markAllButton.addEventListener("click", (event) => {
      event.preventDefault();
      markAllAsRead();
    });
  }

  fetchUnreadCount();
  if (pollInterval > 0) {
    setInterval(fetchUnreadCount, pollInterval);
  }
})();
