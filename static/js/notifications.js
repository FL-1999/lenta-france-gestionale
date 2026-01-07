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
  const endpoint = container.dataset.endpoint || "/api/notifications/poll";
  const readEndpoint = container.dataset.readEndpoint || "/api/notifications/{id}/read";
  const pollInterval = Number(container.dataset.pollInterval || 30000);

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

  const renderNotifications = (payload) => {
    const notifications = payload?.notifications || [];
    const unreadCount = payload?.unread_count || 0;
    setBadge(unreadCount);

    list.innerHTML = "";
    if (!notifications.length) {
      emptyState.classList.remove("is-hidden");
      return;
    }

    emptyState.classList.add("is-hidden");
    notifications.forEach((notification) => {
      const item = document.createElement("li");
      item.className = "notifications-panel__item";
      if (!notification.is_read) {
        item.classList.add("is-unread");
      }

      const link = document.createElement("a");
      link.className = "notifications-panel__link";
      link.href = notification.target_url || "#";
      link.textContent = notification.message;

      const meta = document.createElement("span");
      meta.className = "notifications-panel__meta";
      meta.textContent = formatDateTime(notification.created_at);

      link.addEventListener("click", async (event) => {
        if (!notification.target_url) {
          event.preventDefault();
        }
        try {
          await fetch(readEndpoint.replace("{id}", notification.id), {
            method: "POST",
            credentials: "same-origin",
          });
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
      const response = await fetch(endpoint, { credentials: "same-origin" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      renderNotifications(payload);
    } catch (error) {
      console.error("Notifications polling failed", error);
    }
  };

  const closePanel = () => {
    panel.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
  };

  const openPanel = () => {
    panel.classList.add("is-open");
    toggle.setAttribute("aria-expanded", "true");
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

  fetchNotifications();
  if (pollInterval > 0) {
    setInterval(fetchNotifications, pollInterval);
  }
})();
