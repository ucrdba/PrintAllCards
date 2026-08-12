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
        self.logger.log(f"Step 1 - Clicking Search Box at ({self.config.search_x}, {self.config.search_y})")
        pyautogui.click(self.config.search_x, self.config.search_y)
        if not self.safe_sleep(self.config.search_start_delay):
            return False, "Interrupted"

        # Step 2: Clear existing content
        self.logger.log("Step 2 - Clearing existing text")
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')

        # Step 3: Paste Student ID from clipboard and press Enter
        self.logger.log(f"Step 3 - Copying & pasting Student ID: {student_id} (and pressing Enter)")
        pyperclip.copy(student_id)
        pyautogui.hotkey('ctrl', 'v')
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
        if self.config.dry_run:
            self.logger.log(f"[DRY RUN] Would click Print button at ({self.config.print_x}, {self.config.print_y})")
        else:
            self.logger.log(f"Clicking Print button at ({self.config.print_x}, {self.config.print_y})")
            pyautogui.click(self.config.print_x, self.config.print_y)
            if not self.safe_sleep(self.config.print_delay):
                return False, "Interrupted during print delay"

        if not self.safe_sleep(self.config.between_student_delay):
            return False, "Interrupted"

        return True, ""

    def test_print_click(self):
        """Moves mouse and clicks print button once for test print."""
        self.logger.log(f"Testing Print button click at ({self.config.print_x}, {self.config.print_y})")
        pyautogui.moveTo(self.config.print_x, self.config.print_y)
        time.sleep(0.1)
        pyautogui.click(self.config.print_x, self.config.print_y)
