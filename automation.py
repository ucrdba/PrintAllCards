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

    def reset_controls(self):
        self.stop_event.clear()
        self.pause_event.set()
        self.is_running = False
        self.emergency_stop_triggered = False

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

    def move_and_click(self, x: int, y: int):
        """Moves mouse smoothly to (x, y) if mouse trail is enabled, then clicks."""
        if self.config.enable_mouse_trail:
            pyautogui.moveTo(x, y, duration=0.3, tween=pyautogui.easeOutQuad)
        else:
            pyautogui.moveTo(x, y)
        time.sleep(0.1)
        # Perform click with standard duration to register on Windows controls
        pyautogui.click(x, y, duration=0.05)

    def find_uiautomation_control(self, name_keywords: list, control_types: list = None) -> Optional[Tuple[int, int]]:
        """
        Dynamically searches open Windows controls using UIAutomation to locate
        a button or edit box matching name_keywords (e.g. 'Print', 'Search', 'StudentSearch').
        Returns (x, y) center coordinates if found.
        """
        if not HAS_UIAUTOMATION:
            return None

        try:
            # Walk top-level window controls
            root = auto.GetRootControl()
            for window in root.GetChildren():
                if not window.IsOffscreen:
                    for child in window.GetDescendants():
                        try:
                            c_name = str(child.Name).lower().strip()
                            c_type = str(child.ControlTypeName).lower().strip()

                            # Check control type filter if specified
                            if control_types and not any(ct in c_type for ct in control_types):
                                continue

                            # Check if name contains any of the keywords
                            if any(kw in c_name for kw in name_keywords):
                                rect = child.BoundingRectangle
                                if rect and rect.width() > 0 and rect.height() > 0:
                                    cx = rect.left + rect.width() // 2
                                    cy = rect.top + rect.height() // 2
                                    return (cx, cy)
                        except Exception:
                            continue
        except Exception as e:
            self.logger.error(f"UIAutomation search error: {e}")

        return None

    def process_single_student(self, student_id: str, is_test: bool = False) -> Tuple[bool, str]:
        """
        Performs the 4-step sequence:
        1. Click Search Box (search_x, search_y)
        2. Select all & clear (Ctrl+A, Backspace)
        3. Copy to clipboard & paste (Ctrl+V)
        4. Wait for verification up to max_search_wait
        If is_test is False and verification succeeds and not dry_run, clicks Print.
        """
        if not self.wait_if_paused_or_stopped():
            return False, "Process stopped by user"

        # Step 1: Click Search location
        search_x, search_y = self.config.search_x, self.config.search_y

        # Try dynamic UIAutomation lookup for search box first
        dynamic_search = self.find_uiautomation_control(['studentsearch', 'search', 'student id'], ['edit', 'textbox', 'input'])
        if dynamic_search:
            search_x, search_y = dynamic_search
            self.logger.log(f"Step 1 - Dynamically located Search Box via Windows UIAutomation at ({search_x}, {search_y})")
        else:
            self.logger.log(f"Step 1 - Clicking Search Box at configured location ({search_x}, {search_y})")

        self.move_and_click(search_x, search_y)
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

        # Check if text/numbers exist in the box before pressing Enter
        has_text = False
        try:
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.1)
            copied = pyperclip.paste().strip()
            # If text/numbers are present in the box
            if copied and any(char.isdigit() for char in copied):
                has_text = True
                # Deselect text by moving cursor to end of line
                pyautogui.press('right')
                time.sleep(0.05)
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

        # Step 5: Print if not dry run
        print_x, print_y = self.config.print_x, self.config.print_y
        dynamic_print = self.find_uiautomation_control(['print', 'print card', 'print photo'], ['button', 'menuitem', 'hyperlink', 'text', 'pane', 'group'])
        if dynamic_print:
            print_x, print_y = dynamic_print
            self.logger.log(f"Dynamically located Electron Print element at ({print_x}, {print_y})")

        if self.config.dry_run:
            self.logger.log(f"[DRY RUN] Would trigger Print action at ({print_x}, {print_y})")
            if print_x > 0 and print_y > 0:
                if self.config.enable_mouse_trail:
                    pyautogui.moveTo(print_x, print_y, duration=0.3, tween=pyautogui.easeOutQuad)
                else:
                    pyautogui.moveTo(print_x, print_y)
            if not self.safe_sleep(self.config.print_delay):
                return False, "Interrupted during print delay"
        else:
            if print_x > 0 and print_y > 0:
                self.logger.log(f"Clicking Electron Print button at ({print_x}, {print_y})")
                # For Electron apps: Move mouse, click once to ensure window/tab focus, then click target
                if self.config.enable_mouse_trail:
                    pyautogui.moveTo(print_x, print_y, duration=0.3, tween=pyautogui.easeOutQuad)
                else:
                    pyautogui.moveTo(print_x, print_y)
                time.sleep(0.1)
                pyautogui.click(print_x, print_y)
                time.sleep(0.05)
                pyautogui.click(print_x, print_y)  # Double-click fallback for Electron web buttons
            
            # Send Keyboard Hotkey trigger if configured
            if self.config.print_hotkey:
                self.logger.log(f"Sending Print Hotkey trigger: '{self.config.print_hotkey}'")
                hk = [k.strip() for k in self.config.print_hotkey.lower().split('+')]
                if len(hk) > 1:
                    pyautogui.hotkey(*hk)
                else:
                    pyautogui.press(hk[0])

            if not self.safe_sleep(self.config.print_delay):
                return False, "Interrupted during print delay"

        if not self.safe_sleep(self.config.between_student_delay):
            return False, "Interrupted"

        return True, ""

    def test_print_click(self):
        """Moves mouse and clicks print button once for test print."""
        print_x, print_y = self.config.print_x, self.config.print_y
        dynamic_print = self.find_uiautomation_control(['print'], ['button'])
        if dynamic_print:
            print_x, print_y = dynamic_print
            self.logger.log(f"Dynamically located Print button via Windows UIAutomation at ({print_x}, {print_y})")

        self.logger.log(f"Testing Print button click at ({print_x}, {print_y})")
        self.move_and_click(print_x, print_y)
