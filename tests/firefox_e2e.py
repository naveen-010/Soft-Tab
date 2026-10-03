"""Integration checks against real Firefox in an isolated, temporary profile.

Requires Selenium and Firefox. Selenium Manager obtains geckodriver as needed.
Run: python tests/firefox_e2e.py
"""
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "soft-tab-447fe68d-3fe1-4f95-9a46-bf6ce9124d11@local.extension"
UUID = "66a111cc-1291-4d61-bbf7-4ef09f884243"
PAGE = b"""<!doctype html><title>Unsaved draft</title>
<textarea id="draft"></textarea><div style="height:4000px">Live test page</div>
<script>window.nonce = crypto.randomUUID(); window.ticks = 0;
setInterval(() => window.ticks++, 100);</script>"""


class PageServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), PageServer)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}/"
options = Options()
options.add_argument("-headless")
options.set_preference("extensions.webextensions.uuids", json.dumps({ADDON_ID: UUID}))
options.set_preference("browser.ctrlTab.sortByRecentlyUsed", False)
service = Service(service_args=["--allow-system-access"])


with webdriver.Firefox(options=options, service=service) as driver:
    driver.set_script_timeout(10)
    driver.install_addon(str(ROOT / "extension"), temporary=True)
    driver.get(f"moz-extension://{UUID}/popup.html")
    bridge = driver.current_window_handle
    wait = WebDriverWait(driver, 10)

    def api(expression):
        driver.switch_to.window(bridge)
        return driver.execute_async_script(
            "const done = arguments[0]; Promise.resolve().then(async () => {"
            + expression
            + "}).then(value => done({value}), error => done({error: error.message}));"
        )

    def value(expression):
        result = api(expression)
        assert "error" not in result, result
        return result.get("value")

    def message(kind, **extra):
        return value("return browser.runtime.sendMessage(" + json.dumps({"type": kind, **extra}) + ");")

    def state():
        return message("state")

    def available_state():
        return api("return browser.runtime.sendMessage({type:'state'});").get("value")

    def create_target(path=""):
        handles = set(driver.window_handles)
        tab = value(f"return browser.tabs.create({{url: {json.dumps(url + path)}}});")
        handle = next(handle for handle in driver.window_handles if handle not in handles)
        driver.switch_to.window(handle)
        wait.until(lambda _: driver.execute_script("return Boolean(window.nonce)"))
        return tab, handle

    @contextmanager
    def chrome():
        driver.set_context("chrome")
        try:
            yield
        finally:
            driver.set_context("content")

    def unbind_close():
        # Equivalent effective binding to clearing Close Tab in about:keyboard.
        # Only the isolated test profile's current browser window is touched.
        with chrome():
            driver.execute_script("document.getElementById('key_close')?.remove();")

    def selected_uri():
        with chrome():
            return driver.execute_script("return gBrowser.selectedBrowser.currentURI.spec;")

    def press(*modifiers, key):
        # Send browser-level input through Firefox's own test input helper.
        # WebDriver content actions alone do not exercise XUL key commands.
        with chrome():
            driver.execute_script("""
              const utils = {window, parent: window};
              Services.scriptloader.loadSubScript('chrome://remote/content/external/EventUtils.js', utils);
              utils.synthesizeKey(arguments[0], arguments[1], window);
            """, "KEY_Tab" if key == Keys.TAB else key,
              {"ctrlKey": Keys.CONTROL in modifiers, "altKey": Keys.ALT in modifiers,
               "shiftKey": Keys.SHIFT in modifiers})

    def soft_close(tab_id):
        value(f"await browser.tabs.update({tab_id}, {{active: true}}); return browser.runtime.sendMessage({{type: 'soft-close'}});")

    def get_tab(tab_id):
        return value(f"return browser.tabs.get({tab_id}).catch(() => null);")

    print("Firefox", driver.capabilities["browserVersion"], flush=True)
    assert state() == {"tabs": [], "delaySeconds": 60, "error": ""}
    commands = value("return browser.commands.getAll();")
    assert next(command for command in commands if command["name"] == "soft-close")["shortcut"] == "Ctrl+W"
    print("PASS: default shortcut registration and one-minute delay", flush=True)

    tab, handle = create_target("draft")
    nonce = driver.execute_script("return window.nonce")
    driver.find_element(By.ID, "draft").send_keys("An unsaved AI prompt that must survive.")
    driver.execute_script("window.scrollTo(0, 600)")
    ticks = driver.execute_script("return window.ticks")
    unbind_close()
    press(Keys.CONTROL, key="w")
    wait.until(lambda _: selected_uri().startswith("moz-extension:"))
    saved = get_tab(tab["id"])
    assert saved["hidden"] and not saved["discarded"] and not saved["autoDiscardable"]
    assert len(state()["tabs"]) == 1
    for recently_used in (False, True):
        with chrome():
            driver.execute_script("Services.prefs.setBoolPref('browser.ctrlTab.sortByRecentlyUsed', arguments[0]);", recently_used)
        press(Keys.CONTROL, key=Keys.TAB)
        assert selected_uri().startswith("moz-extension:"), "Ctrl Tab selected a hidden tab"
    press(Keys.ALT, Keys.SHIFT, key="w")
    wait.until(lambda _: selected_uri() == url + "draft")
    driver.switch_to.window(handle)
    assert driver.execute_script("return window.nonce") == nonce
    assert driver.find_element(By.ID, "draft").get_attribute("value") == "An unsaved AI prompt that must survive."
    assert driver.execute_script("return window.scrollY") == 600
    assert driver.execute_script("return window.ticks") > ticks
    assert get_tab(tab["id"])["autoDiscardable"]
    assert not state()["tabs"]
    assert not value("return browser.alarms.getAll();")
    print("PASS: actual Ctrl W / undo keys, both Ctrl Tab modes, live state and draft retained", flush=True)

    # Use a long hold while checking event-page recovery, then a short real timer.
    soft_close(tab["id"])
    original_deadline = state()["tabs"][0]["expiresAt"]
    value("const background = await browser.runtime.getBackgroundPage(); background.location.reload(); return true;")
    wait.until(lambda _: (current := available_state()) and current["tabs"] and current["tabs"][0]["expiresAt"] == original_deadline)
    assert get_tab(tab["id"])["hidden"]
    message("undo")
    assert not get_tab(tab["id"])["hidden"]
    print("PASS: background-page reload retains the live tab and original deadline", flush=True)

    # Stale unhide events cannot cancel a subsequent soft close.
    value(f"await browser.tabs.update({tab['id']}, {{active: true}}); "
          "const requests = [browser.runtime.sendMessage({type:'soft-close'}), "
          "browser.runtime.sendMessage({type:'undo'}), browser.runtime.sendMessage({type:'soft-close'})]; "
          "await Promise.all(requests); return true;")
    assert get_tab(tab["id"])["hidden"]
    assert len(state()["tabs"]) == 1
    assert len(value("return browser.alarms.getAll();")) == 1
    message("undo")
    print("PASS: rapid close / undo / close keeps the final timer", flush=True)

    result = api(f"await browser.tabs.update({tab['id']}, {{pinned: true, active: true}}); return browser.runtime.sendMessage({{type:'soft-close'}});")
    assert "Pinned" in result.get("error", "")
    assert not get_tab(tab["id"])["hidden"]
    message("dismiss-error")
    value(f"return browser.tabs.update({tab['id']}, {{pinned: false}});")
    print("PASS: unsupported pinned tabs stay safely visible", flush=True)

    invalid = api("return browser.runtime.sendMessage({type:'set-delay', seconds:0});")
    assert "error" in invalid
    assert state()["delaySeconds"] == 60
    message("dismiss-error")
    message("set-delay", seconds=5)
    soft_close(tab["id"])
    message("undo")
    time.sleep(5.5)
    assert get_tab(tab["id"]) is not None
    print("PASS: delay validation and undo cancels an actual pending expiry", flush=True)

    # Revealing a tab via Firefox must cancel its pending close.
    soft_close(tab["id"])
    value(f"return browser.tabs.show({tab['id']});")
    wait.until(lambda _: (current := available_state()) is not None and not current["tabs"])
    assert not value("return browser.alarms.getAll();")
    time.sleep(5.5)
    assert get_tab(tab["id"]) is not None
    print("PASS: externally revealing a hidden tab cancels timed closing", flush=True)

    # Different close times have independent deadlines; changes affect new holds.
    soft_close(tab["id"])
    message("set-delay", seconds=10)
    second, second_handle = create_target("second")
    soft_close(second["id"])
    assert len(state()["tabs"]) == 2
    driver.get_full_page_screenshot_as_file(str(ROOT / "tests" / "popup-light.png"))
    wait.until(lambda _: get_tab(tab["id"]) is None)
    assert get_tab(second["id"])["hidden"]
    assert len(state()["tabs"]) == 1
    assert value(f"return browser.sessions.getRecentlyClosed();")[0]["tab"]
    message("undo")
    print("PASS: real timed close, independent deadlines, setting changes leave existing timers intact", flush=True)

    # Popup settings and restore buttons use the real background, without HTML injection.
    driver.switch_to.window(bridge)
    delay = driver.find_element(By.ID, "delay")
    delay.clear()
    delay.send_keys("30")
    driver.find_element(By.CSS_SELECTOR, "#delay-form button").click()
    wait.until(lambda _: state()["delaySeconds"] == 30)
    soft_close(second["id"])
    wait.until(lambda _: driver.find_elements(By.CSS_SELECTOR, ".tab-restore"))
    expected_deadline = state()["tabs"][0]["expiresAt"]
    wait.until(lambda _: int(driver.find_element(By.CSS_SELECTOR, ".countdown").get_attribute("data-expires-at")) == expected_deadline)
    driver.get_full_page_screenshot_as_file(str(ROOT / "tests" / "popup-light.png"))
    button = driver.find_element(By.CSS_SELECTOR, ".tab-restore")
    assert "Unsaved draft" in button.text
    button.click()
    wait.until(lambda _: not get_tab(second["id"])["hidden"])
    print("PASS: popup delay saving and restore button", flush=True)

    # The last visible tab needs a replacement, in its original window.
    isolated = value(f"return browser.windows.create({{url: {json.dumps(url + 'last')}}});")
    last = isolated["tabs"][0]
    value(f"const bg = await browser.runtime.getBackgroundPage(); await bg.run(() => bg.softClose({isolated['id']})); return true;")
    assert get_tab(last["id"])["hidden"]
    visible = value(f"return browser.tabs.query({{windowId: {isolated['id']}, hidden:false}});")
    assert len(visible) == 1 and visible[0]["url"] == "about:newtab"
    # Undo from another window must not restore the isolated window's held tab.
    assert not state()["tabs"]
    message("undo")
    assert get_tab(last["id"])["hidden"]
    value(f"const bg = await browser.runtime.getBackgroundPage(); await bg.run(() => bg.undo({isolated['id']})); return true;")
    assert not get_tab(last["id"])["hidden"]
    value(f"return browser.windows.remove({isolated['id']});")
    print("PASS: last visible tab, no parking window, undo isolated per window", flush=True)

    # Simulate fresh session storage while session markers survive a browser restart.
    soft_close(second["id"])
    value("await browser.storage.session.clear(); const bg = await browser.runtime.getBackgroundPage(); bg.location.reload(); return true;")
    wait.until(lambda _: (current := available_state()) is not None and not current["tabs"])
    assert not get_tab(second["id"])["hidden"]
    assert get_tab(second["id"])["autoDiscardable"]
    assert not value("return browser.alarms.getAll();")
    message("set-delay", seconds=60)
    print("PASS: restart recovery reveals tabs and clears old deadlines", flush=True)

    # Open the actual toolbar popup, not just its HTML in an extension tab.
    # Firefox's first-tab-hidden notice may have opened a native panel.
    with chrome():
        driver.execute_script("for (const panel of document.querySelectorAll('panel')) if (panel.state === 'open') panel.hidePopup();")
    time.sleep(.3)
    popup = value("await browser.action.openPopup(); await new Promise(resolve => setTimeout(resolve, 500)); "
                  "const popup = browser.extension.getViews({type:'popup'})[0]; "
                  "return {width: popup.innerWidth, scrollWidth: popup.document.documentElement.scrollWidth, "
                  "hasUndo: Boolean(popup.document.getElementById('undo'))};")
    assert popup["hasUndo"] and popup["scrollWidth"] <= popup["width"], popup
    print("PASS: real toolbar popup opens without horizontal overflow", flush=True)

server.shutdown()
print("All Firefox integration checks passed.", flush=True)
