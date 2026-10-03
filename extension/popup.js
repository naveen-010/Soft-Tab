const $ = id => document.getElementById(id);
let tabs = [];
let shownError = "";
let loading = false;

const send = (type, extra = {}) => browser.runtime.sendMessage({ type, ...extra });

function showError(message) {
  $("error-text").textContent = message;
  $("error").hidden = !message;
}

function updateCountdowns() {
  for (const element of document.querySelectorAll(".countdown")) {
    const seconds = Math.max(0, Math.ceil((Number(element.dataset.expiresAt) - Date.now()) / 1000));
    element.textContent = seconds ? `${seconds}s · restore` : "Closing…";
  }
}

async function refresh(initial = false) {
  if (loading) return;
  loading = true;
  try {
    const state = await send("state");
    tabs = state.tabs;
    if (initial) {
      $("delay").value = state.delaySeconds;
      const { setupCollapsed = false } = await browser.storage.local.get("setupCollapsed");
      $("setup").open = !setupCollapsed;
    }
    if (state.error !== shownError) {
      shownError = state.error;
      showError(state.error);
    }
    $("undo").disabled = !tabs.length;
    $("empty").hidden = Boolean(tabs.length);
    $("count").textContent = `${tabs.length} ${tabs.length === 1 ? "tab" : "tabs"}`;
    // Keep focused restore buttons intact while the timer ticks.
    const existingIds = [...$("tabs").children].map(row => Number(row.dataset.tabId));
    if (JSON.stringify(existingIds) !== JSON.stringify(tabs.map(tab => tab.id))) {
      $("tabs").replaceChildren(...tabs.map(tab => {
        const row = document.createElement("li");
        row.dataset.tabId = tab.id;
        const button = document.createElement("button");
        button.className = "tab-restore";
        button.title = `Restore ${tab.title}`;
        const title = document.createElement("span");
        title.className = "tab-title";
        title.textContent = tab.title;
        const countdown = document.createElement("span");
        countdown.className = "countdown";
        countdown.dataset.expiresAt = tab.expiresAt;
        button.append(title, countdown);
        button.addEventListener("click", () => act("restore", { tabId: tab.id }));
        row.append(button);
        return row;
      }));
    }
    for (const [index, tab] of tabs.entries()) {
      const row = $("tabs").children[index];
      row.querySelector("button").title = `Restore ${tab.title}`;
      row.querySelector(".tab-title").textContent = tab.title;
      row.querySelector(".countdown").dataset.expiresAt = tab.expiresAt;
    }
    updateCountdowns();
  } catch (error) {
    showError(error.message);
  } finally {
    loading = false;
  }
}

async function act(type, extra = {}) {
  try {
    await send(type, extra);
    await refresh();
  } catch (error) {
    showError(error.message);
  }
}

$("soft-close").addEventListener("click", () => act("soft-close"));
$("undo").addEventListener("click", () => act("undo"));
$("dismiss-error").addEventListener("click", async () => {
  await act("dismiss-error");
  showError("");
});
$("open-shortcuts").addEventListener("click", () => act("open-shortcuts"));
$("delay-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await send("set-delay", { seconds: Number($("delay").value) });
    $("save-status").textContent = "Saved. Applies to the next soft close.";
  } catch (error) {
    showError(error.message);
  }
});
$("setup").addEventListener("toggle", () => {
  browser.storage.local.set({ setupCollapsed: !$("setup").open });
});
refresh(true);
setInterval(() => refresh(), 1000);
