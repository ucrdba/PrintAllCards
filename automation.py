import time
import threading
from typing import Callable, List, Optional, Tuple
import pyautogui
import pyperclip
from config import AppConfig
from dom_driver import DomDriver, DomError
from logger import AppLogger

# Optional UIAutomation fallback for robust Windows control verification
try:
    import uiautomation as auto
    HAS_UIAUTOMATION = True
except ImportError:
    HAS_UIAUTOMATION = False

from pynput import keyboard

# Enable PyAutoGUI safety features
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

class AutomationController:
    def __init__(self, config: AppConfig, logger: AppLogger):
        self.config = config
        self.logger = logger
        
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Unpaused initially
        
        self.is_running = False
        self.current_student = ""
        self.emergency_stop_triggered = False

        self.job_durations: List[float] = []
        self.get_queue_job_count: Optional[Callable[[], int]] = None

        # Wired in from the GUI: draws the on-screen mouse trail. Signature is
        # (from_x, from_y, to_x, to_y, label).
        self.show_trail: Optional[Callable[[int, int, int, int, str], None]] = None

        # DOM control of Schoolhouse Smiles (see dom_driver.py). _dom_fallback_reason
        # remembers the last "not available" message so it is logged once, not per student.
        self.dom = DomDriver(port=getattr(config, 'dom_debug_port', 9222))
        self._dom_fallback_reason: Optional[str] = None

        # Why the last process_single_student call failed, when the batch loop should
        # treat it specially. FAILURE_NOT_FOUND: the student is not in Schoolhouse Smiles.
        self.last_failure_kind: str = ""

        self.key_listener = None
        self._start_keyboard_listener()

    def _start_keyboard_listener(self):
        """Starts background global keyboard listener for ESC key emergency stop."""
        def on_press(key):
            try:
                # Check for ESC key or Ctrl+Shift+S
                if key == keyboard.Key.esc:
                    self.logger.error("EMERGENCY HOTKEY TRIGGERED (ESC key pressed)!")
                    self.stop_event.set()
                    self.emergency_stop_triggered = True
            except Exception:
                pass

        self.key_listener = keyboard.Listener(on_press=on_press)
        self.key_listener.daemon = True
        self.key_listener.start()

    def reset_job_durations(self):
        self.job_durations = []

    def get_job_timing_stats(self) -> Tuple[float, float, float]:
        """Returns (min_time, max_time, avg_time) for completed jobs in seconds."""
        if not self.job_durations:
            return 0.0, 0.0, 0.0
        min_t = min(self.job_durations)
        max_t = max(self.job_durations)
        avg_t = sum(self.job_durations) / len(self.job_durations)
        return min_t, max_t, avg_t

    def reset_controls(self):
        self.stop_event.clear()
        self.pause_event.set()
        self.is_running = False
        self.emergency_stop_triggered = False

    def verify_target_app_active(self, target_x: int, target_y: int, expected_exe_name: str = "schoolhouse-smiles.exe") -> Tuple[bool, str]:
        """
        Verification check disabled. Always returns True.
        """
        return True, "Verification disabled"

    def check_emergency_stop(self) -> bool:
        """Checks if mouse is at top-left corner (0,0) or (0..5, 0..5)."""
        x, y = pyautogui.position()
        if x <= 5 and y <= 5:
            self.logger.error("EMERGENCY STOP TRIGGERED (Mouse in upper-left corner)!")
            self.stop_event.set()
            self.emergency_stop_triggered = True
            return True
        return False

    def wait_if_paused_or_stopped(self) -> bool:
        """
        Returns False if automation should stop completely.
        """
        while not self.pause_event.is_set():
            if self.stop_event.is_set() or self.check_emergency_stop():
                return False
            time.sleep(0.1)
            
        if self.stop_event.is_set() or self.check_emergency_stop():
            return False
            
        return True

    def safe_sleep(self, seconds: float) -> bool:
        """Sleeps in small increments checking for stop/pause/emergency stop."""
        end_time = time.time() + seconds
        while time.time() < end_time:
            if not self.wait_if_paused_or_stopped():
                return False
            time.sleep(0.05)
        return True

    def verify_student_search(self, expected_id: str, max_wait: float) -> bool:
        """
        Verifies that StudentSearch textbox contains the expected student ID.
        Strategy 1: UIAutomation (if available).
        Strategy 2: Copy text via Ctrl+A, Ctrl+C fallback test if configured/needed.
        """
        start_time = time.time()

        while time.time() - start_time < max_wait:
            if not self.wait_if_paused_or_stopped():
                return False

            # Approach A: UIAutomation focused element value check
            if HAS_UIAUTOMATION:
                try:
                    focused = auto.GetFocusedControl()
                    if focused:
                        val = ""
                        if hasattr(focused, 'GetValuePattern'):
                            val = focused.GetValuePattern().Value
                        elif hasattr(focused, 'Name'):
                            val = focused.Name
                        if val and expected_id in str(val):
                            return True
                except Exception:
                    pass

            # Approach B: Clipboard selection verification
            # Copy active content using Ctrl+A then Ctrl+C
            try:
                pyautogui.hotkey('ctrl', 'a')
                pyautogui.hotkey('ctrl', 'c')
                time.sleep(0.1)
                clip_val = pyperclip.paste().strip()
                if clip_val == expected_id:
                    return True
            except Exception:
                pass

            time.sleep(0.3)

        return False

    # Placed on the clipboard before a Ctrl+C read-back, so a copy that silently
    # fails cannot be mistaken for the ID that was just pasted from the clipboard
    _CLIPBOARD_SENTINEL = "⁣__search_box_readback__⁣"

    def read_search_box_text(self) -> Optional[str]:
        """
        Returns the current text of the focused StudentSearch box, or None if it
        cannot be read. Tries the UIAutomation value of the focused edit control
        first, then a Ctrl+A / Ctrl+C read-back.
        """
        if HAS_UIAUTOMATION:
            try:
                focused = auto.GetFocusedControl()
                # The search box is an Angular Material autocomplete, which UIA
                # reports as a ComboBoxControl with a ValuePattern
                if focused and focused.ControlTypeName in ("EditControl", "ComboBoxControl"):
                    return str(focused.GetValuePattern().Value or "")
            except Exception:
                pass

        try:
            pyperclip.copy(self._CLIPBOARD_SENTINEL)
            time.sleep(0.05)
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.05)
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.15)
            clip_val = pyperclip.paste()
            if clip_val != self._CLIPBOARD_SENTINEL:
                return clip_val
        except Exception:
            pass
        return None

    def _enter_student_id(self, student_id: str) -> Tuple[bool, str]:
        """
        Clears the search box, enters student_id and confirms the box holds exactly
        that ID before anything else happens. The first two attempts paste; the last
        one types the ID key by key. Returns (confirmed, last_text_seen).
        """
        attempts = 3
        seen = None
        for attempt in range(1, attempts + 1):
            if not self.wait_if_paused_or_stopped():
                return False, "Process stopped by user"

            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.05)
            pyautogui.press('backspace')
            time.sleep(0.1)

            if attempt < attempts:
                pyperclip.copy(student_id)
                time.sleep(0.15)
                pyautogui.hotkey('ctrl', 'v')
            else:
                self.logger.log(f"Typing Student ID explicitly: {student_id}")
                pyautogui.write(student_id, interval=0.03)
            time.sleep(0.2)

            seen = self.read_search_box_text()
            if seen is not None and seen.strip() == student_id:
                return True, seen.strip()

            shown = "unreadable" if seen is None else f"'{seen.strip()}'"
            self.logger.log(f"Search box check {attempt}/{attempts}: expected '{student_id}', found {shown}")

        return False, "" if seen is None else seen.strip()

    def draw_trail(self, to_x: int, to_y: int, label: str = ""):
        """
        Asks the GUI to draw a visible trail from the cursor's current position to
        (to_x, to_y) so the operator can see where each automated click is heading.
        Safe to call from the automation thread; the GUI marshals it back to Tk.
        """
        if not self.config.enable_mouse_trail or not callable(self.show_trail):
            return
        try:
            from_x, from_y = pyautogui.position()
            self.show_trail(int(from_x), int(from_y), int(to_x), int(to_y), label)
        except Exception:
            pass

    def move_and_click(self, x: int, y: int, label: str = ""):
        """Moves mouse smoothly to (x, y) if mouse trail is enabled, then clicks."""
        self.draw_trail(x, y, label)
        if self.config.enable_mouse_trail:
            pyautogui.moveTo(x, y, duration=0.3, tween=pyautogui.easeOutQuad)
        else:
            pyautogui.moveTo(x, y)
        time.sleep(0.1)
        # Perform click with standard duration to register on Windows controls
        pyautogui.click(x, y, duration=0.05)

    TARGET_EXE = "schoolhouse-smiles.exe"
    FAILURE_NOT_FOUND = "not_found"

    def _window_process_name(self, hwnd: int) -> str:
        """Returns the lower-cased exe name owning hwnd, or '' if it cannot be determined."""
        try:
            import ctypes
            import ctypes.wintypes
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return ""
            # PROCESS_QUERY_LIMITED_INFORMATION - works without elevation
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = ctypes.wintypes.DWORD(1024)
                if not ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    return ""
                return buf.value.rsplit("\\", 1)[-1].lower()
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return ""

    def find_print_button(self) -> Optional[Tuple[int, int]]:
        """
        Locates the target app's Print button through Windows UIAutomation and returns
        its centre, or None if it cannot be found.

        This exists because the button moves vertically: a student who has been printed
        before gets an extra "(Last Printed ...)" line above the buttons, pushing Print
        a couple of hundred pixels down the Y axis, so a fixed coordinate misses it.

        Only the Print button is located this way. The search box keeps its configured
        coordinates, since it sits at the top of the window where nothing shifts it.
        """
        if not HAS_UIAUTOMATION:
            return None

        try:
            root = auto.GetRootControl()

            window = None
            for child in root.GetChildren():
                try:
                    if child.IsOffscreen:
                        continue
                    # Confirm by process, not by title: clicking a Print button that
                    # belongs to some other application would be worse than not finding one.
                    if self._window_process_name(child.NativeWindowHandle) == self.TARGET_EXE:
                        window = child
                        break
                except Exception:
                    continue

            if window is None:
                return None

            # 'Print with Dialog' also starts with "print" and opens a dialog instead of
            # printing, so an exact name match always wins over a prefix match.
            exact = None
            prefix = None
            for ctrl, _depth in auto.WalkControl(window, includeTop=False, maxDepth=40):
                try:
                    if ctrl.ControlTypeName != "ButtonControl":
                        continue
                    name = str(ctrl.Name).strip().lower()
                except Exception:
                    continue

                if name == "print":
                    exact = ctrl
                    break
                if prefix is None and name.startswith("print") and "dialog" not in name:
                    prefix = ctrl

            found = exact or prefix
            if found is None:
                return None

            rect = found.BoundingRectangle
            if not rect or rect.width() <= 0 or rect.height() <= 0:
                return None

            return (rect.left + rect.width() // 2, rect.top + rect.height() // 2)
        except Exception as e:
            self.logger.log(f"UIAutomation Print lookup failed ({e}) - falling back to configured coordinates.")
            return None

    def click_card_type(self) -> bool:
        """
        Clicks the configured Card Type selector for the current student, immediately
        before the Print action. This only runs when Card Type is marked Required; if the
        checkbox is unchecked, or the location was never captured (0, 0), it is a no-op
        and the student proceeds unchanged.
        """
        if not getattr(self.config, 'card_type_required', False):
            return True

        card_x = getattr(self.config, 'card_type_x', 0)
        card_y = getattr(self.config, 'card_type_y', 0)

        if card_x <= 0 and card_y <= 0:
            self.logger.log("Card Type is marked Required but no location is configured - skipping card type selection.")
            return True

        # Selecting a card type prints nothing, so it is clicked for real even in
        # dry run - dry run only suppresses the Print action itself.
        try:
            self.logger.log(f"Selecting Card Type at ({card_x}, {card_y})")
            self.move_and_click(card_x, card_y, "CARD TYPE")
        except pyautogui.FailSafeException:
            self.logger.error("EMERGENCY STOP TRIGGERED: Mouse moved to screen corner (PyAutoGUI FailSafe)")
            self.stop_event.set()
            self.emergency_stop_triggered = True
            return False

        return self.safe_sleep(self.config.search_start_delay)

    def process_single_student(self, student_id: str, is_test: bool = False) -> Tuple[bool, str]:
        """
        Performs the 4-step sequence:
        1. Click Search Box (search_x, search_y)
        2. Select all & clear (Ctrl+A, Backspace)
        3. Paste the ID (Ctrl+V) and confirm the search box holds exactly that ID,
           retrying (paste, paste, then typing) and failing the student before
           Enter is pressed if it never does
        4. Wait for verification up to max_search_wait
        If is_test is False and verification succeeds and not dry_run, clicks Print.
        """
        self.last_failure_kind = ""
        try:
            return self._execute_single_student(student_id, is_test)
        except pyautogui.FailSafeException:
            self.logger.error("EMERGENCY STOP TRIGGERED: Mouse moved to screen corner (PyAutoGUI FailSafe)")
            self.stop_event.set()
            self.emergency_stop_triggered = True
            return False, "Emergency stop (Mouse moved to screen corner)"

    def _execute_single_student(self, student_id: str, is_test: bool = False) -> Tuple[bool, str]:
        if not self.wait_if_paused_or_stopped():
            return False, "Process stopped by user"

        # Step 0: Check Print Queue Sync gating threshold if enabled
        if not is_test and getattr(self.config, 'enable_queue_sync', False) and callable(self.get_queue_job_count):
            max_jobs = getattr(self.config, 'max_queue_jobs', 5)
            while True:
                if self.stop_event.is_set():
                    return False, "Process stopped by user"

                cur_jobs = self.get_queue_job_count()
                if cur_jobs < max_jobs:
                    break

                self.logger.log(f"[QUEUE SYNC] Print queue count is {cur_jobs} (Limit: {max_jobs}). Pausing automation until queue drops below {max_jobs}...")
                if not self.safe_sleep(1.0):
                    return False, "Interrupted"

        job_start_t = time.time()

        if self.dom_ready():
            return self._execute_single_student_dom(student_id, is_test, job_start_t)

        # Step 1: Click Search location
        search_x, search_y = self.config.search_x, self.config.search_y


        self.move_and_click(search_x, search_y, "SEARCH")
        if not self.safe_sleep(self.config.search_start_delay):
            return False, "Interrupted"

        # Steps 2-3: Clear the box, enter the ID, and confirm the box holds exactly
        # that ID - never press Enter on a stale, partial or wrong ID
        self.logger.log(f"Step 2 - Clearing search box and entering Student ID: {student_id}")
        time.sleep(0.1)
        confirmed, seen = self._enter_student_id(student_id)
        if not confirmed:
            if self.stop_event.is_set():
                return False, "Process stopped by user"
            found = f"'{seen}'" if seen else "nothing readable"
            return False, f"Search box shows {found} instead of Student ID {student_id} - not pressing Enter"
        self.logger.log(f"Step 3 - Search box confirmed to contain Student ID: {student_id}")

        # Press Enter only after the search box is confirmed to hold the ID
        self.logger.log(f"Pressing Enter key for Student ID: {student_id}")
        pyautogui.press('enter')

        # Step 4: Verification
        if self.config.require_verification:
            self.logger.log(f"Step 4 - Waiting up to {self.config.max_search_wait}s for StudentSearch verification...")
            verified = self.verify_student_search(student_id, self.config.max_search_wait)
            if not verified:
                return False, f"StudentSearch timeout for {student_id}"
            self.logger.log(f"StudentSearch confirmed: {student_id}")
        else:
            self.logger.log("Step 4 - Verification skipped (Require Strict StudentSearch Verification is unchecked)")

        if is_test:
            return True, f"Student {student_id} verified successfully!"

        # Step 5: Re-select the Card Type for this student (only when marked Required)
        if not self.click_card_type():
            return False, "Interrupted during Card Type selection"

        # Step 6: Print if not dry run
        print_x, print_y = self.config.print_x, self.config.print_y
        dynamic_print = self.find_print_button()
        if dynamic_print:
            drift = abs(dynamic_print[1] - print_y)
            print_x, print_y = dynamic_print
            self.logger.log(f"Located Print button via UIAutomation at ({print_x}, {print_y}) - {drift}px from the configured Y")

        if self.config.dry_run:
            self.logger.log(f"[DRY RUN] Would trigger Print action at ({print_x}, {print_y})")
            if print_x > 0 and print_y > 0:
                self.draw_trail(print_x, print_y, "PRINT (DRY RUN)")
                if self.config.enable_mouse_trail:
                    pyautogui.moveTo(print_x, print_y, duration=0.3, tween=pyautogui.easeOutQuad)
                else:
                    pyautogui.moveTo(print_x, print_y)
            if not self.safe_sleep(self.config.print_delay):
                return False, "Interrupted during print delay"
        else:
            if print_x > 0 and print_y > 0:
                self.logger.log(f"Clicking Print button at ({print_x}, {print_y})")
                self.move_and_click(print_x, print_y, "PRINT")
            elif self.config.print_hotkey:
                self.logger.log(f"Sending Print Hotkey trigger: '{self.config.print_hotkey}'")
                hk = [k.strip() for k in self.config.print_hotkey.lower().split('+')]
                if len(hk) > 1:
                    pyautogui.hotkey(*hk)
                else:
                    pyautogui.press(hk[0])


        if not self.safe_sleep(self.config.between_student_delay):
            return False, "Interrupted"

        if not is_test:
            duration = time.time() - job_start_t
            self.job_durations.append(duration)

        return True, ""

    # ------------------------------------------------------------------ DOM control

    def dom_ready(self) -> bool:
        """
        True when DOM control is enabled and Schoolhouse Smiles accepts it. When it is
        enabled but unavailable, logs why (once per distinct reason) so the fall back
        to screen coordinates is never silent.
        """
        if not getattr(self.config, 'use_dom_control', False):
            return False
        self.dom.port = getattr(self.config, 'dom_debug_port', 9222)
        ok, reason = self.dom.connect()
        if ok:
            if self._dom_fallback_reason is not None:
                self.logger.log("[DOM] Connected to Schoolhouse Smiles - using DOM control.")
            self._dom_fallback_reason = None
            return True
        if reason != self._dom_fallback_reason:
            self.logger.error(f"[DOM] {reason} Falling back to screen coordinates.")
            self._dom_fallback_reason = reason
        return False

    def _execute_single_student_dom(self, student_id: str, is_test: bool, job_start_t: float) -> Tuple[bool, str]:
        """
        The per-student flow using DOM control: every control is found by its label or
        text, and the student record is confirmed loaded (the Student ID field shows the
        ID) before Card Type or Print are touched. Dry run still suppresses only Print.
        """
        dom = self.dom
        try:
            # Step 1: type the ID into Student Search and confirm the box holds exactly it
            self.logger.log(f"[DOM] Step 1 - Entering Student ID {student_id} into Student Search")
            confirmed = False
            seen = None
            for attempt in range(1, 4):
                if not self.wait_if_paused_or_stopped():
                    return False, "Process stopped by user"
                if not dom.type_into_field("Student Search", student_id):
                    return False, "Student Search box was not found in Schoolhouse Smiles"
                seen = dom.read_field("Student Search")
                if seen is not None and seen.strip() == student_id:
                    confirmed = True
                    break
                self.logger.log(f"[DOM] Search box check {attempt}/3: expected '{student_id}', found '{seen}'")
            if not confirmed:
                return False, f"Search box shows '{seen}' instead of Student ID {student_id} - not selecting a student"

            # Step 2: wait for the autocomplete to list exactly this ID. No match means the
            # student is not in Schoolhouse Smiles, so fail now rather than waiting out
            # max_search_wait. A longer ID that merely contains this one does not count.
            wait_until = time.time() + min(self.config.max_search_wait, 5.0)
            while not dom.has_option_for_id(student_id):
                if time.time() >= wait_until:
                    self.last_failure_kind = self.FAILURE_NOT_FOUND
                    return False, (f"Student {student_id} was not found in Schoolhouse Smiles - "
                                   f"searching for the ID returned no match.")
                if not self.safe_sleep(0.1):
                    return False, "Process stopped by user"

            # Click that exact option. Enter would pick the first option, which can be a
            # different student whose ID shares this prefix.
            self.logger.log(f"[DOM] Step 2 - Search box confirmed; selecting the search result for {student_id}")
            if not dom.click_option_for_id(student_id):
                return False, f"The search result for {student_id} disappeared before it could be selected"

            # Step 3: wait for the student record itself to load
            deadline = time.time() + self.config.max_search_wait
            shown = dom.read_field("Student ID")
            while shown is None or shown.strip() != student_id:
                if time.time() >= deadline:
                    return False, (f"Student record did not load within {self.config.max_search_wait}s - "
                                   f"Student ID field shows '{shown}' instead of {student_id}")
                if not self.safe_sleep(0.1):
                    return False, "Process stopped by user"
                shown = dom.read_field("Student ID")
            self.logger.log(f"[DOM] Step 3 - Student record loaded: {student_id}")

            if is_test:
                return True, f"Student {student_id} loaded successfully (DOM control)!"

            # Step 4: Card Type (only when marked Required)
            if getattr(self.config, 'card_type_required', False):
                name = getattr(self.config, 'card_type_name', '').strip()
                if name:
                    clicked = dom.click_card_type(name)
                    if clicked is None:
                        return False, f"Card Type '{name}' was not found on the student page"
                    if clicked:
                        wait_until = time.time() + 2.0
                        while dom.selected_card_type() != name and time.time() < wait_until:
                            if not self.safe_sleep(0.1):
                                return False, "Process stopped by user"
                        if dom.selected_card_type() != name:
                            return False, f"Card Type '{name}' could not be selected"
                        self.logger.log(f"[DOM] Step 4 - Selected Card Type '{name}'")
                    else:
                        self.logger.log(f"[DOM] Step 4 - Card Type '{name}' was already selected")
                else:
                    self.logger.log("[DOM] Step 4 - No Card Type name set; using the Card Type coordinates")
                    if not self.click_card_type():
                        return False, "Interrupted during Card Type selection"

            # Step 5: Print (the button named exactly 'Print', never 'Print with Dialog')
            button = dom.find_button("Print")
            if button is None:
                return False, "Print button was not found on the student page"
            if button.get("disabled"):
                return False, "Print button is disabled on the student page"

            if self.config.dry_run:
                self.logger.log("[DRY RUN] [DOM] Would click the Print button")
                if not self.safe_sleep(self.config.print_delay):
                    return False, "Interrupted during print delay"
            else:
                before = dom.read_last_printed()
                if not dom.click_button("Print"):
                    return False, "Print button could not be clicked"
                self.logger.log("[DOM] Step 5 - Clicked Print")
                if not self.safe_sleep(self.config.print_delay):
                    return False, "Interrupted during print delay"
                after = dom.read_last_printed()
                if after and after != before:
                    self.logger.log(f"[DOM] Print confirmed by Schoolhouse Smiles: {after}")
                else:
                    self.logger.log("[DOM] 'Last Printed' has not updated yet - the print may still be in progress")
        except DomError as e:
            return False, f"Lost DOM control of Schoolhouse Smiles: {e}"

        if not self.safe_sleep(self.config.between_student_delay):
            return False, "Interrupted"

        self.job_durations.append(time.time() - job_start_t)
        return True, ""

    def test_print_click(self):
        """Clicks the Print button once for a test print (DOM control when available)."""
        if self.dom_ready():
            try:
                if self.dom.click_button("Print"):
                    self.logger.log("[DOM] Test Print - clicked the Print button")
                else:
                    self.logger.error("[DOM] Test Print - Print button not found or disabled")
            except DomError as e:
                self.logger.error(f"[DOM] Test Print failed: {e}")
            return

        print_x, print_y = self.config.print_x, self.config.print_y
        dynamic_print = self.find_print_button()
        if dynamic_print:
            print_x, print_y = dynamic_print
            self.logger.log(f"Located Print button via UIAutomation at ({print_x}, {print_y})")

        self.logger.log(f"Testing Print button click at ({print_x}, {print_y})")
        self.move_and_click(print_x, print_y, "TEST PRINT")
