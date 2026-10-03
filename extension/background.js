const HOLD_KEY = "tab-reprieve-hold";
const ALARM_PREFIX = "close-tab:";
const held = new Map();
let lastError = "";

async function updateBadge() {
  await browser.action.setBadgeBackgroundColor({ color: "#246d54" });
  await browser.action.setBadgeText({ text: lastError ? "!" : held.size ? String(held.size) : "" });
  await browser.action.setTitle({ title: lastError || "Soft-Tab" });
}

async function report(error) {
  console.error("Soft-Tab:", error);
  lastError = error.message || String(error);
  await updateBadge();
}

async function release(tabId, tab) {
  const record = held.get(tabId);
  if (!record) return;
  held.delete(tabId);
  await browser.alarms.clear(ALARM_PREFIX + tabId);
  if (tab) {
    await browser.tabs.update(tabId, { autoDiscardable: record.autoDiscardable });
    await browser.sessions.removeTabValue(tabId, HOLD_KEY);
  }
  await updateBadge();
}

async function initialize() {
  const { running } = await browser.storage.session.get("running");
  await browser.storage.session.set({ running: true });
  for (const tab of await browser.tabs.query({})) {
    const record = await browser.sessions.getTabValue(tab.id, HOLD_KEY);
    if (!record) continue;
    held.set(tab.id, record);
    // A browser restart loses live pages. Reveal recovered tabs rather than
    // closing them on old deadlines. Event-page wakeups retain session storage.
    if (!running || !tab.hidden || tab.active) {
      await browser.tabs.show(tab.id);
      await release(tab.id, tab);
    } else {
      await browser.alarms.create(ALARM_PREFIX + tab.id, { when: record.expiresAt });
    }
  }
  await updateBadge();
}

// Serialize commands, undo, and expiry so a rapid undo cannot race a close.
let queue = initialize().catch(report);
function run(task) {
  const result = queue.then(task);
  queue = result.catch(report);
  return result;
}

async function softClose(windowId) {
  const [tab] = await browser.tabs.query({ windowId, active: true });
  if (!tab || tab.hidden || held.has(tab.id)) return;
  if (tab.pinned) throw new Error("Pinned tabs stay open. Unpin this tab before soft closing it.");
  const sharing = tab.sharingState;
  if (sharing && (sharing.camera || sharing.microphone || sharing.screen)) {
    throw new Error("This tab is sharing camera, microphone, or screen. It has been left open.");
  }

  const { delaySeconds = 60 } = await browser.storage.local.get("delaySeconds");
  const record = {
    closedAt: Date.now(),
    expiresAt: Date.now() + delaySeconds * 1000,
    autoDiscardable: tab.autoDiscardable ?? true
  };
  const visible = await browser.tabs.query({ windowId, hidden: false });
  const next = visible.find(candidate => candidate.index > tab.index) ||
    visible.filter(candidate => candidate.index < tab.index).at(-1);

  await browser.sessions.setTabValue(tab.id, HOLD_KEY, record);
  held.set(tab.id, record);
  try {
    await browser.tabs.update(tab.id, { autoDiscardable: false });
    if (next) await browser.tabs.update(next.id, { active: true });
    else await browser.tabs.create({ windowId, active: true });
    const hiddenIds = await browser.tabs.hide(tab.id);
    if (!hiddenIds.includes(tab.id)) {
      throw new Error("Firefox could not hide this tab. It has been left open.");
    }
    await browser.alarms.create(ALARM_PREFIX + tab.id, { when: record.expiresAt });
    lastError = "";
    await updateBadge();
  } catch (error) {
    const current = await browser.tabs.get(tab.id).catch(() => null);
    if (current) {
      await browser.tabs.show(tab.id);
      await browser.tabs.update(tab.id, { active: true });
    }
    await release(tab.id, current);
    throw error;
  }
}

async function restore(tabId) {
  if (!held.has(tabId)) return;
  const tab = await browser.tabs.get(tabId).catch(() => null);
  if (!tab) return release(tabId);
  await browser.tabs.show(tabId);
  await release(tabId, tab);
  await browser.tabs.update(tabId, { active: true });
  await browser.windows.update(tab.windowId, { focused: true });
  lastError = "";
  await updateBadge();
}

async function list(windowId) {
  const tabs = await browser.tabs.query({ windowId });
  return tabs.filter(tab => held.has(tab.id)).map(tab => ({
    id: tab.id,
    title: tab.title || "Untitled tab",
    expiresAt: held.get(tab.id).expiresAt,
    closedAt: held.get(tab.id).closedAt
  })).sort((a, b) => b.closedAt - a.closedAt || b.id - a.id);
}

async function undo(windowId) {
  const [latest] = await list(windowId);
  if (latest) await restore(latest.id);
}

async function expire(tabId) {
  const record = held.get(tabId);
  if (!record) return;
  const tab = await browser.tabs.get(tabId).catch(() => null);
  if (!tab) return release(tabId);
  // Firefox or another extension may have revealed the tab independently.
  if (!tab.hidden || tab.active) return release(tabId, tab);
  if (record.expiresAt > Date.now()) {
    return browser.alarms.create(ALARM_PREFIX + tabId, { when: record.expiresAt });
  }
  try {
    await browser.tabs.update(tabId, { autoDiscardable: record.autoDiscardable });
    await browser.sessions.removeTabValue(tabId, HOLD_KEY);
    await browser.tabs.remove(tabId);
    await release(tabId);
  } catch (error) {
    // A failed close must not leave an indefinitely hidden tab.
    await browser.tabs.show(tabId);
    await release(tabId, tab);
    throw error;
  }
}

browser.commands.onCommand.addListener((command) => {
  run(async () => {
    const window = await browser.windows.getLastFocused();
    if (command === "soft-close") await softClose(window.id);
    if (command === "undo-soft-close") await undo(window.id);
  });
});

browser.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name.startsWith(ALARM_PREFIX)) {
    run(() => expire(Number(alarm.name.slice(ALARM_PREFIX.length))));
  }
});

browser.tabs.onRemoved.addListener(tabId => run(() => release(tabId)));
browser.tabs.onUpdated.addListener((tabId, change) => {
  if (change.hidden === false) run(async () => {
    if (!held.has(tabId)) return;
    const tab = await browser.tabs.get(tabId).catch(() => null);
    if (!tab || !tab.hidden) await release(tabId, tab);
  });
});

browser.runtime.onMessage.addListener((message, sender) => {
  if (sender.id !== browser.runtime.id) return;
  return run(async () => {
    const windowId = (await browser.windows.getCurrent()).id;
    switch (message.type) {
      case "state": {
        const { delaySeconds = 60 } = await browser.storage.local.get("delaySeconds");
        return { tabs: await list(windowId), delaySeconds, error: lastError };
      }
      case "soft-close":
        await softClose(windowId);
        break;
      case "undo":
        await undo(windowId);
        break;
      case "restore": {
        const tabs = await list(windowId);
        if (tabs.some(tab => tab.id === message.tabId)) await restore(message.tabId);
        break;
      }
      case "set-delay":
        if (!Number.isInteger(message.seconds) || message.seconds < 5 || message.seconds > 3600) {
          throw new Error("Choose a delay between 5 and 3600 seconds.");
        }
        await browser.storage.local.set({ delaySeconds: message.seconds });
        break;
      case "dismiss-error":
        lastError = "";
        await updateBadge();
        break;
      case "open-shortcuts":
        await browser.commands.openShortcutSettings();
        break;
    }
  });
});
