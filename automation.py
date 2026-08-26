import time
import threading
from typing import Callable, Optional, Tuple
import pyautogui
import pyperclip
from config import AppConfig
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
        3. Copy to clipboard & paste (Ctrl+V)
        4. Wait for verification up to max_search_wait
        If is_test is False and verification succeeds and not dry_run, clicks Print.
        """
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

        # Step 1: Click Search location
        search_x, search_y = self.config.search_x, self.config.search_y


        self.move_and_click(search_x, search_y, "SEARCH")
        if not self.safe_sleep(self.config.search_start_delay):
            return False, "Interrupted"

        # Step 2: Clear existing content
        self.logger.log("Step 2 - Clearing existing text")
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.05)
        pyautogui.press('backspace')
        time.sleep(0.1)

        # Step 3: Copy to clipboard & paste single instance
        self.logger.log(f"Step 3 - Copying & pasting Student ID: {student_id}")
        pyperclip.copy(student_id)
        time.sleep(0.15)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)

        # Fallback check if paste succeeded
        has_text = True
        try:
            copied = pyperclip.paste().strip()
            if not copied or not any(char.isdigit() for char in copied):
                has_text = False
        except Exception:
            pass

        # Fallback: if clipboard check is unavailable, try typing explicitly to ensure numbers are entered
        if not has_text:
            self.logger.log(f"No text detected after paste. Typing Student ID explicitly: {student_id}")
            pyautogui.write(student_id, interval=0.03)
            time.sleep(0.15)

        # Press Enter only after ensuring numbers/ID exist in the box
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

    def test_print_click(self):
        """Moves mouse and clicks print button once for test print."""
        print_x, print_y = self.config.print_x, self.config.print_y
        dynamic_print = self.find_print_button()
        if dynamic_print:
            print_x, print_y = dynamic_print
            self.logger.log(f"Located Print button via UIAutomation at ({print_x}, {print_y})")

        self.logger.log(f"Testing Print button click at ({print_x}, {print_y})")
        self.move_and_click(print_x, print_y, "TEST PRINT")
