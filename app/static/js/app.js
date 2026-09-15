document.addEventListener("click", (event) => {
    document.querySelectorAll(".notification-menu[open]").forEach((menu) => {
        if (!menu.contains(event.target)) {
            menu.removeAttribute("open");
        }
    });
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        document.querySelectorAll(".notification-menu[open]").forEach((menu) => {
            menu.removeAttribute("open");
        });
    }
});

async function refreshNotifications(menu) {
    if (!menu || menu.dataset.loading === "true") {
        return;
    }

    menu.dataset.loading = "true";
    try {
        const response = await fetch(menu.dataset.feedUrl, {
            headers: { Accept: "application/json" },
            credentials: "same-origin",
        });
        if (!response.ok) {
            return;
        }

        const data = await response.json();
        const badge = menu.querySelector(".notification-badge");
        const summary = menu.querySelector("summary");
        const unreadLabel = menu.querySelector(".notification-unread-label");
        const feed = menu.querySelector(".notification-feed");
        const markAll = menu.querySelector(".notification-mark-all");

        badge.textContent = data.badge_text;
        badge.hidden = data.unread_count === 0;
        summary.setAttribute(
            "aria-label",
            data.unread_count
                ? `Notifications: ${data.unread_count} unread`
                : "Notifications",
        );
        unreadLabel.textContent = `${data.unread_count} unread`;
        markAll.hidden = data.unread_count === 0;
        feed.innerHTML = data.html;
    } catch (_error) {
        // Keep the server-rendered notification state if a refresh fails.
    } finally {
        delete menu.dataset.loading;
    }
}

document.querySelectorAll(".notification-menu").forEach((menu) => {
    menu.addEventListener("toggle", () => {
        if (menu.open) {
            refreshNotifications(menu);
        }
    });
});

window.addEventListener("focus", () => {
    document.querySelectorAll(".notification-menu").forEach((menu) => {
        refreshNotifications(menu);
    });
});
