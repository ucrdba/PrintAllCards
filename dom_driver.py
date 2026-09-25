"""
Drives Schoolhouse Smiles through the Chrome DevTools Protocol (CDP) instead of
screen coordinates.

Schoolhouse Smiles is an Electron app, so when it is started with
--remote-debugging-port=<port> its page can be read and controlled directly: fields,
buttons and radio buttons are found by their visible label or text, and clicks and
typing are delivered to the page as trusted input events. Nothing depends on where the
window is, what covers it, or where a control sits on screen.

Controls are matched by label/text only. The Angular Material ids ('mat-input-2',
'mat-radio-10-input', ...) are generated at runtime and change between launches.
"""
import json
import threading
import urllib.request
from typing import List, Optional, Tuple

try:
    import websocket  # websocket-client
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False

TARGET_EXE_MARKER = "schoolhouse-smiles"
TARGET_TITLE = "School House Photo"
# Heading of the radio group that holds the card types (Student ID, Student ASB, ...)
CARD_TYPE_GROUP = "ID Card"
# Schoolhouse Smiles' local print server, which holds its selected printer(s)
PRINT_SERVER_URL = "http://127.0.0.1:45696"

# Injected into every evaluation (the page can reload, so nothing is kept as a global).
# __norm drops the required-field '*' so 'Student ID *' matches 'Student ID'.
_JS_HELPERS = r"""
const __norm = s => (s || '').replace(/\*/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
const __field = label => {
  for (const ff of document.querySelectorAll('mat-form-field')) {
    const l = ff.querySelector('mat-label, label');
    if (l && __norm(l.innerText) === __norm(label)) {
      const input = ff.querySelector('input, textarea');
      if (input) return input;
    }
  }
  return null;
};
const __button = text => [...document.querySelectorAll('button')].find(b => __norm(b.innerText) === __norm(text)) || null;
// Radios of the mat-radio-group headed by this text (e.g. <h6>ID Card</h6><mat-radio-group>).
// Scoped so other radio groups on the page (such as the Local/Network printer choice) are never read.
const __groupRadios = heading => {
  for (const g of document.querySelectorAll('mat-radio-group')) {
    let named = __norm(g.getAttribute('aria-label')) === __norm(heading);
    for (let e = g.previousElementSibling; e && !named; e = e.previousElementSibling) {
      named = __norm(e.innerText) === __norm(heading);
    }
    if (named) return [...g.querySelectorAll('mat-radio-button')];
  }
  return [];
};
const __radio = (heading, label) => __groupRadios(heading).find(r => __norm(r.innerText) === __norm(label)) || null;
const __center = el => {
  el.scrollIntoView({block: 'center', inline: 'center'});
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  return {x: r.left + r.width / 2, y: r.top + r.height / 2};
};
"""


def get_print_server_printers(timeout: float = 0.5) -> List[str]:
    """
    Names of the printers enabled in Schoolhouse Smiles, read from its local print server
    (PrintService.exe). The printer choice is not on the page and no longer in its
    settings.json - Schoolhouse Smiles keeps it here. [] if the server is not reachable.
    """
    try:
        with urllib.request.urlopen(f"{PRINT_SERVER_URL}/api/settings", timeout=timeout) as resp:
            settings = json.loads(resp.read().decode("utf-8"))
        return [p["name"] for p in settings.get("printers", [])
                if p.get("enabled") and isinstance(p.get("name"), str) and p["name"].strip()]
    except Exception:
        return []


class DomError(Exception):
    """Raised when the DevTools connection fails or a page script throws."""


class DomDriver:
    def __init__(self, port: int = 9222):
        self.port = port
        self._ws = None
        self._msg_id = 0
        # The GUI thread (connection checks, card type list) and the automation
        # thread share one socket, so requests and their replies must not interleave.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ connection

    def close(self):
        with self._lock:
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
            self._ws = None

    def connect(self, timeout: float = 2.0) -> Tuple[bool, str]:
        """
        Connects (or confirms the existing connection) to the Schoolhouse Smiles page.
        Returns (connected, reason_if_not).
        """
        if not HAS_WEBSOCKET:
            return False, "The websocket-client package is not installed."

        with self._lock:
            if self._ws is not None:
                try:
                    self.evaluate("1")
                    return True, ""
                except DomError:
                    self.close()

            base = f"http://127.0.0.1:{self.port}"
            try:
                with urllib.request.urlopen(f"{base}/json/version", timeout=timeout) as r:
                    version = json.load(r)
                with urllib.request.urlopen(f"{base}/json/list", timeout=timeout) as r:
                    targets = json.load(r)
            except Exception:
                return False, (f"Schoolhouse Smiles is not accepting DOM control on port {self.port}. "
                               f"Start it with --remote-debugging-port={self.port}.")

            # Never drive some other Chromium/Electron app that happens to use this port
            if TARGET_EXE_MARKER not in str(version.get("User-Agent", "")).lower():
                return False, f"Port {self.port} belongs to another application, not Schoolhouse Smiles."

            pages = [t for t in targets if t.get("type") == "page"]
            page = next((t for t in pages if t.get("title") == TARGET_TITLE), None) or \
                next((t for t in pages if TARGET_EXE_MARKER in str(t.get("url", "")).lower()), None)
            if page is None:
                return False, "Schoolhouse Smiles is running, but its main page was not found."

            try:
                self._ws = websocket.create_connection(
                    page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
            except Exception as e:
                self._ws = None
                return False, f"Could not connect to the Schoolhouse Smiles page: {e}"

            # Let focus/typing work even while the Electron window is not the foreground window
            try:
                self._send("Emulation.setFocusEmulationEnabled", {"enabled": True})
            except DomError:
                pass
            return True, ""

    def _send(self, method: str, params: Optional[dict] = None) -> dict:
        with self._lock:
            if self._ws is None:
                raise DomError("Not connected to Schoolhouse Smiles.")
            self._msg_id += 1
            msg_id = self._msg_id
            try:
                self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
                while True:
                    reply = json.loads(self._ws.recv())
                    if reply.get("id") == msg_id:
                        break
            except Exception as e:
                self.close()
                raise DomError(f"Connection to Schoolhouse Smiles lost: {e}") from e
            if "error" in reply:
                raise DomError(f"{method} failed: {reply['error'].get('message', reply['error'])}")
            return reply.get("result", {})

    def evaluate(self, expression: str):
        result = self._send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("exception", {}).get("description") or details.get("text", "script error")
            raise DomError(f"Page script failed: {text}")
        return result.get("result", {}).get("value")

    def _js(self, body: str):
        return self.evaluate(f"(() => {{ {_JS_HELPERS}\n{body} }})()")

    # ------------------------------------------------------------------ input

    def _click_at(self, x: float, y: float):
        """Trusted left click at page (CSS pixel) coordinates - not screen coordinates."""
        for event in ("mouseMoved", "mousePressed", "mouseReleased"):
            params = {"type": event, "x": x, "y": y}
            if event != "mouseMoved":
                params.update({"button": "left", "clickCount": 1})
            self._send("Input.dispatchMouseEvent", params)

    def press_enter(self):
        common = {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}
        self._send("Input.dispatchKeyEvent", {"type": "keyDown", "text": "\r", **common})
        self._send("Input.dispatchKeyEvent", {"type": "keyUp", **common})

    # ------------------------------------------------------------------ fields

    def read_field(self, label: str) -> Optional[str]:
        """Current value of the text field with this label, or None if it is not on the page."""
        return self._js(f"const el = __field({json.dumps(label)}); return el ? el.value : null;")

    def type_into_field(self, label: str, text: str) -> bool:
        """
        Focuses the labelled field, selects its contents and types text over it with
        trusted input events, so the app's own input handlers (autocomplete, search)
        react exactly as they would to a person typing.
        """
        focused = self._js(
            f"const el = __field({json.dumps(label)}); if (!el) return false;"
            " el.focus(); el.select(); return document.activeElement === el;")
        if not focused:
            return False
        self._send("Input.insertText", {"text": text})
        return True

    # Finds the autocomplete option for exactly this student ID. Options read like
    # 'Briana Aguilar (747764)'; the ID must be a whole token, so searching 1234567
    # never matches 'Someone (12345678)'.
    _JS_OPTION_FOR_ID = (
        "const __opt = id => [...document.querySelectorAll('mat-option')].find(o =>"
        " new RegExp('(^|\\\\D)' + id.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + '(\\\\D|$)').test(o.innerText));")

    def has_option_for_id(self, student_id: str) -> bool:
        """True when an autocomplete option for exactly this student ID is showing."""
        return bool(self._js(f"{self._JS_OPTION_FOR_ID} return !!__opt({json.dumps(student_id)});"))

    def click_option_for_id(self, student_id: str) -> bool:
        """
        Clicks the autocomplete option for exactly this student ID. Clicking the exact
        option (rather than pressing Enter, which picks the first option) guarantees the
        right student when several IDs share a prefix.
        """
        pos = self._js(f"{self._JS_OPTION_FOR_ID} const o = __opt({json.dumps(student_id)}); return o ? __center(o) : null;")
        if not pos:
            return False
        self._click_at(pos["x"], pos["y"])
        return True

    # ------------------------------------------------------------------ buttons & radios

    def find_button(self, text: str) -> Optional[dict]:
        """{'disabled': bool} for the button whose text is exactly text, or None."""
        return self._js(f"const b = __button({json.dumps(text)}); return b ? {{disabled: b.disabled}} : null;")

    def click_button(self, text: str) -> bool:
        pos = self._js(f"const b = __button({json.dumps(text)}); return (b && !b.disabled) ? __center(b) : null;")
        if not pos:
            return False
        self._click_at(pos["x"], pos["y"])
        return True

    def list_card_types(self) -> List[str]:
        """The ID Card options for the open student ([] when no student is open)."""
        return self._js(
            f"return __groupRadios({json.dumps(CARD_TYPE_GROUP)}).map(r => r.innerText.trim()).filter(Boolean);") or []

    def selected_card_type(self) -> Optional[str]:
        return self._js(
            f"const r = __groupRadios({json.dumps(CARD_TYPE_GROUP)}).find(r => r.classList.contains('mat-radio-checked'));"
            " return r ? r.innerText.trim() : null;")

    def click_card_type(self, label: str) -> Optional[bool]:
        """
        Clicks the ID Card radio button with this label unless it is already selected.
        Returns None if no such radio exists, False if it was already selected,
        True if it was clicked.
        """
        pos = self._js(
            f"const r = __radio({json.dumps(CARD_TYPE_GROUP)}, {json.dumps(label)}); if (!r) return null;"
            " if (r.classList.contains('mat-radio-checked')) return false;"
            " return __center(r.querySelector('label') || r);")
        if pos is None:
            return None
        if pos is False:
            return False
        self._click_at(pos["x"], pos["y"])
        return True

    def read_last_printed(self) -> str:
        """The '(Last Printed ...)' line for the open student, or '' if there is none."""
        return self._js(
            "const e = [...document.querySelectorAll('body *')].find(e => e.children.length === 0 && e.textContent.includes('Last Printed'));"
            " return e ? e.textContent.trim() : '';") or ""
