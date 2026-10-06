# Soft-Tab

Accidentally closed a tab? Soft-Tab keeps it alive briefly so you can recover the closed tab without reloading. A Firefox extension that soft closes tabs without unloading their pages but hidees the tab giving the feel of actually closing it. Undo brings back the original live tab, including unsaved drafts and in-memory page state. After 60 seconds by default, the tab closes for real.

# About

With Soft-Tab enabled, when you close a tab using Ctrl + W , it looks as usual : tab closes, goes out of visibility, u cant see it in the tab bar, and you cant get to it with tab cycler (ctrl + tab). But under the hood, the tab is still alive for a fixed time (say 30 or 60 seconds). Till that time, you can press Alt + Shift + W to restore it completely like it was never closed, without any reload which can save your unsaved work or draft. After that fixed time , the tab actually closes and on recovering it makes it reload. 

The extension is useful for the case when you mistakenly closes a tab and restoring it refreshes it and damages your work. And for the case when you dont want to restore and just normally close the tab, do it. The tab is alive for 30 seconds but after that it gets closed so theres literally zero cons of using this extension and pro is right in front of you.


Protection applies to the shortcut command only. Clicking a tab’s ×, closing the window, browser restarts, crashes, and page reloads are outside its protection. Hidden pages remain active for grace period; they are not frozen.

[Soft Tab Firefox Addon](https://addons.mozilla.org/en-US/firefox/addon/soft-tab/)

## Load it in Firefox

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…**.
3. Select `extension/manifest.json` from this project, or `dist/soft-tab-1.0.0.xpi`.
4. Pin Soft-Tab to the toolbar if you want quick access to its undo list.

This build is unsigned. Temporary add-ons are removed when Firefox restarts. For a permanent installation in standard Firefox, submit the XPI to Mozilla's Add-on Developer Hub for signing, using **On your own** distribution if you do not want a public listing. Signing is separate from building the extension. No signing credentials are included or needed to test it.

## Set up the shortcuts manually

**Until you unbind Firefox's Close Tab shortcut, Ctrl W can close your tab normally. The extension deliberately does not detect, verify, or change the browser's shortcut settings.**

1. Open `about:keyboard` in Firefox 147 or later.
2. Find **Close Tab** and clear or change its **Ctrl W** binding (**Cmd W** on Mac).
3. Open `about:addons`, click the gear menu, and choose **Manage Extension Shortcuts**.
4. Under **Soft-Tab**, assign **Ctrl W** to **Soft close the current tab** if needed. The manifest suggests this shortcut, but browser conflicts and existing preferences may require manual assignment.
5. **Alt Shift W** restores the most recently soft-closed tab in the current window. You can change this shortcut in the same settings. To use **Ctrl Shift T**, first free Firefox's **Reopen Last Closed Tab** binding in `about:keyboard`, then assign it to the extension's restore command.

The toolbar popup includes these instructions and a button to open extension shortcut settings. Its setup section can be collapsed; this is a presentation preference, not a shortcut check.

In Zen, unbind **Close Tab** under **Settings → Keyboard Shortcuts**, then configure the extension shortcuts through `about:addons`. This build was verified in Firefox; Zen's workspace and tab UI integration has not been tested.

## How it works

- Switches to the next visible tab (or the previous one if there is no next tab).
- Hides the original tab in its existing window, at its existing position, using Firefox's `tabs.hide()` API. It creates no holding window and never duplicates or reloads a page.
- Hidden tabs do not appear in the tab strip or either Ctrl Tab cycling mode. Firefox can still expose them in its own hidden-tab list.
- Temporarily sets `autoDiscardable` to `false` to prevent Firefox's automatic memory unloading during the grace period, and restores the previous value on recovery.
- Gives each held tab its own expiry alarm. The delay can be changed from 5 to 3600 seconds; changes affect future soft closes only.
- Undo, selecting a tab from the popup, or revealing the tab through Firefox cancels the pending close.
- If it is the last visible tab, opens a new tab to keep the original window available for undo.
- Pinned tabs and tabs actively sharing camera, microphone, or screen remain open; a message explains why they could not be hidden.

The badge shows the number of held tabs across windows. The popup and undo shortcut operate on the current window. The popup lists the newest soft close first and shows the remaining time.

Hidden pages remain **live**, not frozen: audio, game logic, requests, and AI responses may continue; Firefox may throttle background work. Closing the window, clicking a tab's ×, middle-clicking, crashes, and site-triggered reloads are outside the soft-close shortcut. A restart cannot preserve a live JavaScript session. On a fresh browser session, the extension reveals any marked tabs recovered by Firefox and cancels old deadlines rather than closing them unexpectedly.

## Privacy and permissions

No content scripts, host permissions, network requests, analytics, or external dependencies are included in the add-on. It does not read or save chat contents or drafts.

- `tabs`: list held tabs and display their titles.
- `tabHide`: hide and reveal tabs.
- `alarms`: close tabs after the configured delay, even when the background event page is sleeping.
- `storage`: save the delay and collapsed setup preference; distinguish background wakeups from fresh browser sessions using memory-only session storage.
- `sessions`: attach the deadline and previous discard setting to each held tab, so an event-page reload can recover its timers.

No URLs or page contents are stored by the extension. Tab metadata is local to Firefox. Mozilla's signing service is not used at runtime.

## Build and verify

The add-on runs directly from `extension/`; there is no JavaScript build step.

```sh
python tools/package.py
npx --yes web-ext lint --source-dir extension --warnings-as-errors
```

The integration checks use real Firefox in an isolated headless profile, never your existing browser profile:

```sh
python -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python tests/firefox_e2e.py
```

Selenium Manager downloads geckodriver if it is not installed. Tests cover keyboard commands, both Ctrl Tab modes, draft/scroll/JavaScript-state preservation, expiry, cancelled timers, independent deadlines, rapid close/undo, background reload, external reveal, pinned tabs, popup controls and countdowns, last-tab handling, window isolation, simulated restart recovery, and opening the actual toolbar popup.

Official references: [hiding tabs](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/tabs/hide), [Firefox shortcut customization](https://support.mozilla.org/en-US/kb/customize-keyboard-shortcuts-firefox), [extension commands](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/commands), [signing and distribution](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/).
