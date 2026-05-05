document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-notifications]");
  const toggle = document.getElementById("notificationsToggle");
  const panel = document.getElementById("notificationsPanel");
  const notificationCount = document.getElementById("notificationCount");
  const listContainer = document.getElementById("notificationsList") || document.querySelector("[data-notifications-list]");
  const emptyState = panel?.querySelector("[data-notifications-empty]");
  const markAllButton = panel?.querySelector("[data-notifications-mark-all]");

  if (!root || !toggle || !panel || !notificationCount || !listContainer) return;

  const countEndpoint = root.dataset.countEndpoint || "/api/notifications/unread-count";
  const listEndpoint = root.dataset.listEndpoint || "/api/notifications/recent";
  const markReadEndpoint = root.dataset.markReadEndpoint || "/api/notifications/mark-read";
  const pollInterval = Number(root.dataset.pollInterval || "30000");

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

  const formatDate = (value) => {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("it-IT", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const extractListPayload = (data) => {
    const list = Array.isArray(data)
      ? data
      : Array.isArray(data?.notifications)
        ? data.notifications
        : Array.isArray(data?.items)
          ? data.items
          : [];
    return list.map((item) => ({
      id: item.id,
      text: item.message || item.text || "Notifica",
      createdAt: item.created_at || item.createdAt || null,
      link: item.link_url || item.target_url || item.url || null,
      read: Boolean(item.read ?? item.is_read),
    }));
  };

  const renderNotifications = (notifications) => {
    listContainer.innerHTML = "";

    if (!notifications.length) {
      emptyState?.classList.remove("is-hidden");
      return;
    }

    emptyState?.classList.add("is-hidden");

    notifications.forEach((notification) => {
      const item = document.createElement("div");
      item.className = "notifications-panel__item";
      if (!notification.read) {
        item.classList.add("is-unread");
      }

      const content = document.createElement(notification.link ? "a" : "div");
      content.className = "notifications-panel__content";
      if (notification.link) {
        content.href = notification.link;
      }

      const text = document.createElement("div");
      text.className = "notifications-panel__message";
      text.textContent = notification.text;

      const meta = document.createElement("div");
      meta.className = "notifications-panel__meta";
      meta.textContent = formatDate(notification.createdAt);

      content.appendChild(text);
      content.appendChild(meta);
      item.appendChild(content);
      listContainer.appendChild(item);
    });
  };

  const updateNotificationCount = async () => {
    try {
      const response = await fetch(countEndpoint, { credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();
      const count = Number(data?.count ?? data?.unread_count ?? 0);
      notificationCount.textContent = String(Number.isFinite(count) ? count : 0);
    } catch (_error) {
      // silent fail
    }
  };

  const loadNotifications = async () => {
    try {
      const [countResponse, listResponse] = await Promise.all([
        fetch(countEndpoint, { credentials: "same-origin" }),
        fetch(listEndpoint, { credentials: "same-origin" }),
      ]);
      if (!listResponse.ok) {
        renderNotifications([]);
        return;
      }
      const data = await listResponse.json();
      const notifications = extractListPayload(data);
      renderNotifications(notifications);
      let count = Number.NaN;
      if (countResponse.ok) {
        const countData = await countResponse.json();
        count = Number(countData?.count ?? countData?.unread_count ?? 0);
      } else if (typeof data?.unread_count !== "undefined") {
        count = Number(data.unread_count);
      }
      if (Number.isFinite(count)) {
        notificationCount.textContent = String(Number.isFinite(count) ? count : 0);
        if (count > 0 && notifications.length === 0) {
          console.error(
            "Backend inconsistency: unread count is > 0 but recent notifications list is empty.",
            { count, listEndpoint },
          );
        }
      }
    } catch (_error) {
      renderNotifications([]);
    }
  };

  toggle.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();

    if (isOpen()) {
      closePanel();
      return;
    }

    openPanel();
    loadNotifications();
  });

  markAllButton?.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();

    try {
      const response = await fetch(markReadEndpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mark_all: true }),
      });
      if (!response.ok) return;
      await loadNotifications();
      await updateNotificationCount();
    } catch (_error) {
      // silent fail
    }
  });

  panel.addEventListener("click", (event) => {
    event.stopPropagation();
  });

  document.addEventListener("click", () => {
    if (isOpen()) closePanel();
  });

  updateNotificationCount();
  setInterval(updateNotificationCount, pollInterval > 0 ? pollInterval : 30000);
});
