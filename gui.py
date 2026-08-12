import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
import os
from typing import List

import pyautogui
from pynput import mouse
from config import AppConfig
from logger import AppLogger
from excel_handler import ExcelHandler
from automation import AutomationController

class AppGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Student Photo Print Automator")
        self.root.geometry("850x820")
        self.root.minsize(800, 750)

        self.config = AppConfig.load()
        self.logger = AppLogger(gui_callback=self.append_log)
        self.automation = AutomationController(self.config, self.logger)

        self.student_ids: List[str] = []
        self.is_processing = False
        self.automation_thread: threading.Thread = None

        self._build_ui()
        self._load_config_to_ui()
        
        # Start periodic GUI updates for status check
        self.root.after(200, self._check_automation_status)

    def _build_ui(self):
        # Configure styles
        style = ttk.Style()
        style.theme_use('clam')
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title Banner
        title_label = ttk.Label(main_frame, text="STUDENT PHOTO PRINT AUTOMATOR", font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 10))

        # Split top area into Left (Excel & Student list) and Right (Locations, Timing, Controls)
        top_pane = ttk.Frame(main_frame)
        top_pane.pack(fill=tk.BOTH, expand=False, pady=5)

        left_pane = ttk.Frame(top_pane, width=320)
        left_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        right_pane = ttk.Frame(top_pane)
        right_pane.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        # --- SECTION 1: EXCEL FILE & STUDENT LIST ---
        excel_frame = ttk.LabelFrame(left_pane, text="EXCEL FILE & STUDENTS", padding="8")
        excel_frame.pack(fill=tk.BOTH, expand=True)

        file_btn_frame = ttk.Frame(excel_frame)
        file_btn_frame.pack(fill=tk.X, pady=2)
        
        self.btn_excel = ttk.Button(file_btn_frame, text="Select Excel File", command=self._select_excel_file)
        self.btn_excel.pack(side=tk.RIGHT, padx=2)
        
        self.lbl_file_path = ttk.Label(file_btn_frame, text="No file selected", font=("Arial", 8), foreground="gray")
        self.lbl_file_path.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.lbl_found_count = ttk.Label(excel_frame, text="0 PHOTOGRAPHED STUDENTS FOUND", font=("Arial", 9, "bold"), foreground="#0066cc")
        self.lbl_found_count.pack(anchor=tk.W, pady=5)

        # Student Listbox
        list_frame = ttk.Frame(excel_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        self.student_listbox = tk.Listbox(list_frame, height=12, selectmode=tk.EXTENDED, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.student_listbox.yview)
        self.student_listbox.config(yscrollcommand=scrollbar.set)
        
        self.student_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Save / Load remaining student list buttons
        export_btn_box = ttk.Frame(excel_frame)
        export_btn_box.pack(fill=tk.X, pady=(5, 0))

        btn_remove_student = ttk.Button(export_btn_box, text="🗑️ Remove Selected", command=self._remove_selected_student)
        btn_remove_student.pack(side=tk.LEFT, padx=2)

        btn_save_list = ttk.Button(export_btn_box, text="Save Remaining List", command=self._save_remaining_list)
        btn_save_list.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        btn_load_list = ttk.Button(export_btn_box, text="Load Saved List", command=self._load_saved_list)
        btn_load_list.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=2)

        # Bind Delete / Backspace keys to listbox for quick removal
        self.student_listbox.bind("<Delete>", lambda e: self._remove_selected_student())
        self.student_listbox.bind("<BackSpace>", lambda e: self._remove_selected_student())

        # --- SECTION 2: AUTOMATION LOCATIONS ---
        loc_frame = ttk.LabelFrame(right_pane, text="AUTOMATION LOCATIONS", padding="8")
        loc_frame.pack(fill=tk.X, pady=(0, 5))

        # Search Location
        s_row = ttk.Frame(loc_frame)
        s_row.pack(fill=tk.X, pady=3)
        ttk.Label(s_row, text="Student Search:", width=15).pack(side=tk.LEFT)
        ttk.Label(s_row, text="X:").pack(side=tk.LEFT)
        self.ent_search_x = ttk.Entry(s_row, width=6)
        self.ent_search_x.pack(side=tk.LEFT, padx=2)
        ttk.Label(s_row, text="Y:").pack(side=tk.LEFT)
        self.ent_search_y = ttk.Entry(s_row, width=6)
        self.ent_search_y.pack(side=tk.LEFT, padx=2)
        btn_pick_search = ttk.Button(s_row, text="Select Location", command=lambda: self._capture_location("Search"))
        btn_pick_search.pack(side=tk.RIGHT)

        # Print Location
        p_row = ttk.Frame(loc_frame)
        p_row.pack(fill=tk.X, pady=3)
        ttk.Label(p_row, text="Print Button:", width=15).pack(side=tk.LEFT)
        ttk.Label(p_row, text="X:").pack(side=tk.LEFT)
        self.ent_print_x = ttk.Entry(p_row, width=6)
        self.ent_print_x.pack(side=tk.LEFT, padx=2)
        ttk.Label(p_row, text="Y:").pack(side=tk.LEFT)
        self.ent_print_y = ttk.Entry(p_row, width=6)
        self.ent_print_y.pack(side=tk.LEFT, padx=2)
        btn_pick_print = ttk.Button(p_row, text="Select Location", command=lambda: self._capture_location("Print"))
        btn_pick_print.pack(side=tk.RIGHT)

        # --- SECTION 3: TIMING & CONFIG ---
        timing_frame = ttk.LabelFrame(right_pane, text="TIMING & OPTIONS", padding="8")
        timing_frame.pack(fill=tk.X, pady=5)

        t_grid = ttk.Frame(timing_frame)
        t_grid.pack(fill=tk.X)

        ttk.Label(t_grid, text="Search Start Delay (s):").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.ent_delay_start = ttk.Entry(t_grid, width=8)
        self.ent_delay_start.grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(t_grid, text="Max Search Wait (s):").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.ent_delay_wait = ttk.Entry(t_grid, width=8)
        self.ent_delay_wait.grid(row=1, column=1, padx=5, pady=2)

        ttk.Label(t_grid, text="Print Delay (s):").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.ent_delay_print = ttk.Entry(t_grid, width=8)
        self.ent_delay_print.grid(row=2, column=1, padx=5, pady=2)

        ttk.Label(t_grid, text="Between Student Delay (s):").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.ent_delay_between = ttk.Entry(t_grid, width=8)
        self.ent_delay_between.grid(row=3, column=1, padx=5, pady=2)

        ttk.Label(t_grid, text="Print Hotkey (e.g. ctrl+p):").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.ent_print_hotkey = ttk.Entry(t_grid, width=8)
        self.ent_print_hotkey.grid(row=4, column=1, padx=5, pady=2)

        # Clear Fields Button
        btn_clear_fields = ttk.Button(timing_frame, text="Clear All Fields", command=self._clear_all_fields)
        btn_clear_fields.pack(anchor=tk.W, pady=(5, 0))

        # Checkboxes
        self.var_mouse_trail = tk.BooleanVar(value=self.config.enable_mouse_trail)
        chk_trail = ttk.Checkbutton(timing_frame, text="Enable Visible Mouse Movement Trail", variable=self.var_mouse_trail)
        chk_trail.pack(anchor=tk.W, pady=(5, 0))

        self.var_require_verification = tk.BooleanVar(value=self.config.require_verification)
        chk_verify = ttk.Checkbutton(timing_frame, text="Require Strict StudentSearch Verification", variable=self.var_require_verification)
        chk_verify.pack(anchor=tk.W, pady=(2, 0))

        self.var_dry_run = tk.BooleanVar(value=self.config.dry_run)
        chk_dry_run = ttk.Checkbutton(timing_frame, text="Dry Run (Do not click Print)", variable=self.var_dry_run)
        chk_dry_run.pack(anchor=tk.W, pady=(2, 0))

        # --- SECTION 4: TEST BUTTONS ---
        test_frame = ttk.LabelFrame(right_pane, text="TESTING", padding="8")
        test_frame.pack(fill=tk.X, pady=5)

        test_btn_box = ttk.Frame(test_frame)
        test_btn_box.pack(fill=tk.X)
        
        btn_test_student = ttk.Button(test_btn_box, text="Test Current Student", command=self._test_current_student)
        btn_test_student.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        btn_test_print = ttk.Button(test_btn_box, text="Test Print", command=self._test_print_button)
        btn_test_print.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=2)

        # --- SECTION 5: CONTROL BUTTONS ---
        control_frame = ttk.LabelFrame(main_frame, text="CONTROL", padding="8")
        control_frame.pack(fill=tk.X, pady=5)

        ctrl_box = ttk.Frame(control_frame)
        ctrl_box.pack(fill=tk.X)

        self.btn_start = tk.Button(ctrl_box, text="START", bg="#28a745", fg="white", font=("Arial", 11, "bold"), command=self._start_automation)
        self.btn_start.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        self.btn_pause = tk.Button(ctrl_box, text="PAUSE", bg="#ffc107", fg="black", font=("Arial", 11, "bold"), command=self._pause_automation)
        self.btn_pause.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        self.btn_stop = tk.Button(ctrl_box, text="STOP", bg="#dc3545", fg="white", font=("Arial", 11, "bold"), command=self._stop_automation)
        self.btn_stop.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        # Emergency Stop Banner
        lbl_emerg = ttk.Label(control_frame, text="Emergency stop hotkey: Press the ESC key anytime or move mouse to upper-left corner.", foreground="#cc0000", font=("Arial", 9, "italic"))
        lbl_emerg.pack(pady=(5, 0))

        # --- SECTION 6: PROGRESS & STATUS ---
        prog_frame = ttk.LabelFrame(main_frame, text="PROGRESS", padding="8")
        prog_frame.pack(fill=tk.X, pady=5)

        lbl_box = ttk.Frame(prog_frame)
        lbl_box.pack(fill=tk.X)

        self.lbl_curr_student = ttk.Label(lbl_box, text="Current Student: None", font=("Arial", 10, "bold"))
        self.lbl_curr_student.pack(side=tk.LEFT)

        self.lbl_prog_stats = ttk.Label(lbl_box, text="Progress: 0 / 0 (0.0%)", font=("Arial", 10))
        self.lbl_prog_stats.pack(side=tk.RIGHT)

        self.progress_bar = ttk.Progressbar(prog_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=5)

        self.lbl_status = ttk.Label(prog_frame, text="Status: Ready", font=("Arial", 9, "italic"), foreground="gray")
        self.lbl_status.pack(anchor=tk.W)

        # --- SECTION 7: LOG WINDOW ---
        log_frame = ttk.LabelFrame(main_frame, text="LOG", padding="8")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.txt_log = tk.Text(log_frame, height=8, font=("Consolas", 9), state=tk.DISABLED)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.txt_log.yview)
        self.txt_log.config(yscrollcommand=log_scroll.set)

        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _load_config_to_ui(self):
        self.ent_search_x.insert(0, str(self.config.search_x))
        self.ent_search_y.insert(0, str(self.config.search_y))
        self.ent_print_x.insert(0, str(self.config.print_x))
        self.ent_print_y.insert(0, str(self.config.print_y))

        self.ent_delay_start.insert(0, str(self.config.search_start_delay))
        self.ent_delay_wait.insert(0, str(self.config.max_search_wait))
        self.ent_delay_print.insert(0, str(self.config.print_delay))
        self.ent_delay_between.insert(0, str(self.config.between_student_delay))
        self.ent_print_hotkey.insert(0, str(self.config.print_hotkey))

        if self.config.last_excel_path and os.path.exists(self.config.last_excel_path):
            self._load_excel_file(self.config.last_excel_path)

    def _clear_all_fields(self):
        """Clears all text entry fields in the GUI."""
        self.ent_search_x.delete(0, tk.END)
        self.ent_search_y.delete(0, tk.END)
        self.ent_print_x.delete(0, tk.END)
        self.ent_print_y.delete(0, tk.END)

        self.ent_delay_start.delete(0, tk.END)
        self.ent_delay_wait.delete(0, tk.END)
        self.ent_delay_print.delete(0, tk.END)
        self.ent_delay_between.delete(0, tk.END)
        self.ent_print_hotkey.delete(0, tk.END)
        self.logger.log("Cleared all configuration input fields.")

    def _save_ui_to_config(self) -> bool:
        try:
            sx = self.ent_search_x.get().strip()
            sy = self.ent_search_y.get().strip()
            px = self.ent_print_x.get().strip()
            py = self.ent_print_y.get().strip()

            d_start = self.ent_delay_start.get().strip()
            d_wait = self.ent_delay_wait.get().strip()
            d_print = self.ent_delay_print.get().strip()
            d_between = self.ent_delay_between.get().strip()
            p_hk = self.ent_print_hotkey.get().strip()

            self.config.search_x = int(sx) if sx else 0
            self.config.search_y = int(sy) if sy else 0
            self.config.print_x = int(px) if px else 0
            self.config.print_y = int(py) if py else 0

            self.config.search_start_delay = float(d_start) if d_start else 0.5
            self.config.max_search_wait = float(d_wait) if d_wait else 15.0
            self.config.print_delay = float(d_print) if d_print else 2.0
            self.config.between_student_delay = float(d_between) if d_between else 0.5
            self.config.print_hotkey = p_hk if p_hk else "ctrl+p"
            self.config.require_verification = self.var_require_verification.get()
            self.config.enable_mouse_trail = self.var_mouse_trail.get()
            self.config.dry_run = self.var_dry_run.get()

            # Validation
            if self.config.search_start_delay < 0 or self.config.max_search_wait < 0 or self.config.print_delay < 0 or self.config.between_student_delay < 0:
                raise ValueError("Delays must be non-negative.")

            self.config.save()
            return True
        except ValueError as e:
            messagebox.showerror("Invalid Settings", f"Please enter valid numeric configuration values.\nDetails: {e}")
            return False

    def append_log(self, text: str):
        def _update():
            self.txt_log.config(state=tk.NORMAL)
            self.txt_log.insert(tk.END, text + "\n")
            self.txt_log.see(tk.END)
            self.txt_log.config(state=tk.DISABLED)
        self.root.after(0, _update)

    def _select_excel_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Excel or CSV File",
            filetypes=[("Data Files", "*.xlsx *.xls *.csv"), ("Excel Files", "*.xlsx *.xls"), ("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if file_path:
            self._load_excel_file(file_path)

    def _save_remaining_list(self):
        """Saves the current remaining unprinted student IDs to a CSV or XLSX file."""
        if not self.student_ids:
            messagebox.showwarning("No Students", "There are no remaining student IDs to save.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save Remaining Student List",
            defaultextension=".csv",
            filetypes=[("CSV File", "*.csv"), ("Excel File", "*.xlsx")]
        )
        if file_path:
            success, msg = ExcelHandler.export_remaining_students(self.student_ids, file_path)
            if success:
                self.logger.log(msg)
                messagebox.showinfo("Export Success", f"Saved {len(self.student_ids)} remaining student IDs to file:\n{file_path}")
            else:
                self.logger.error(msg)
                messagebox.showerror("Export Error", msg)

    def _load_saved_list(self):
        """Loads a previously saved student list directly into the app."""
        file_path = filedialog.askopenfilename(
            title="Load Saved Student List",
            filetypes=[("Student List Files", "*.csv *.xlsx *.xls"), ("All Files", "*.*")]
        )
        if file_path:
            items, err = ExcelHandler.load_student_list(file_path)
            if err:
                self.logger.error(err)
                messagebox.showerror("Load Error", err)
                return

            self.student_ids = [clean_id for clean_id, _ in items]
            self.student_listbox.delete(0, tk.END)
            for _, meta_str in items:
                self.student_listbox.insert(tk.END, meta_str)

            count = len(self.student_ids)
            self.lbl_file_path.config(text=os.path.basename(file_path))
            self.lbl_found_count.config(text=f"{count} SAVED STUDENTS LOADED", foreground="#0066cc")
            self.logger.log(f"Loaded saved student list: {file_path} ({count} students)")

    def _remove_selected_student(self):
        """Removes all currently selected student IDs from the listbox and queue."""
        selected_indices = self.student_listbox.curselection()
        if not selected_indices:
            messagebox.showinfo("Select Student", "Please select one or more students from the list to remove.")
            return

        removed_ids = []
        # Delete in reverse order so indices remain valid
        for idx in sorted(selected_indices, reverse=True):
            removed_id = self.student_ids.pop(idx)
            self.student_listbox.delete(idx)
            removed_ids.append(removed_id)

        # Update remaining count label
        count = len(self.student_ids)
        self.lbl_found_count.config(text=f"{count} PHOTOGRAPHED STUDENTS REMAINING", foreground="#0066cc")
        self.logger.log(f"Removed {len(removed_ids)} student ID(s) from list: {', '.join(reversed(removed_ids))}")

    def _load_excel_file(self, file_path: str):
        self.lbl_file_path.config(text=os.path.basename(file_path))
        items, err = ExcelHandler.load_photographed_students(file_path)
        
        self.student_listbox.delete(0, tk.END)
        if err:
            self.lbl_found_count.config(text="0 PHOTOGRAPHED STUDENTS FOUND", foreground="red")
            self.logger.error(err)
            messagebox.showerror("Excel Error", err)
            return

        self.student_ids = [clean_id for clean_id, _ in items]
        for _, meta_str in items:
            self.student_listbox.insert(tk.END, meta_str)

        count = len(self.student_ids)
        self.lbl_found_count.config(text=f"{count} PHOTOGRAPHED STUDENTS FOUND", foreground="#0066cc")
        self.logger.log(f"Loaded Excel file: {file_path}")
        self.logger.log(f"Found {count} PHOTOGRAPHED students")
        
        self.config.last_excel_path = file_path
        self.config.save()

    def _capture_location(self, target_name: str):
        messagebox.showinfo(
            "Capture Location", 
            f"After clicking OK, position your mouse cursor over the {target_name} location. Capturing in 3 seconds..."
        )
        for i in range(3, 0, -1):
            self.lbl_status.config(text=f"Status: Capturing {target_name} in {i} seconds...")
            self.root.update()
            time.sleep(1)

        x, y = pyautogui.position()
        if target_name == "Search":
            self.ent_search_x.delete(0, tk.END)
            self.ent_search_x.insert(0, str(x))
            self.ent_search_y.delete(0, tk.END)
            self.ent_search_y.insert(0, str(y))
        else:
            self.ent_print_x.delete(0, tk.END)
            self.ent_print_x.insert(0, str(x))
            self.ent_print_y.delete(0, tk.END)
            self.ent_print_y.insert(0, str(y))

        self.lbl_status.config(text=f"Status: Captured {target_name} at ({x}, {y})")
        self.logger.log(f"Captured {target_name} Location: X={x}, Y={y}")
        self._save_ui_to_config()

    def _test_current_student(self):
        if not self._save_ui_to_config():
            return

        sel = self.student_listbox.curselection()
        if sel:
            student_id = self.student_ids[sel[0]]
        elif self.student_ids:
            student_id = self.student_ids[0]
        else:
            messagebox.showwarning("No Student", "Please load an Excel file with students first.")
            return

        self.lbl_curr_student.config(text=f"Current Student: {student_id}")
        self.lbl_status.config(text=f"Status: Testing {student_id} in 1 second...")
        self.logger.log(f"Testing current student: {student_id}")
        self.root.update()

        # Run test in thread to prevent UI freezing
        def run_test():
            time.sleep(1.0)  # Allow Tkinter dialog/button focus to clear
            self.automation.reset_controls()
            success, msg = self.automation.process_single_student(student_id, is_test=True)
            if success:
                messagebox.showinfo("Test Success", f"Successfully verified student {student_id} in StudentSearch!")
            else:
                messagebox.showerror("Test Failed", f"Test failed: {msg}")
            self.lbl_status.config(text="Status: Ready")

        threading.Thread(target=run_test, daemon=True).start()

    def _test_print_button(self):
        if not self._save_ui_to_config():
            return

        if messagebox.askyesno("Confirm Test Print", f"Click Print button at X: {self.config.print_x}, Y: {self.config.print_y}?\n\nThe click will occur 1 second after you click Yes to allow focus to return to your target app."):
            self.root.update()
            time.sleep(1.0)
            self.automation.test_print_click()
            messagebox.showinfo("Test Print", "Print button clicked.")

    def _start_automation(self):
        if not self._save_ui_to_config():
            return

        if not self.student_ids:
            messagebox.showwarning("No Students", "No student IDs loaded. Please select an Excel file.")
            return

        if self.config.search_x == 0 and self.config.search_y == 0:
            messagebox.showwarning("Location Required", "Please configure the Student Search location first.")
            return

        if self.config.print_x == 0 and self.config.print_y == 0 and not self.config.dry_run:
            messagebox.showwarning("Location Required", "Please configure the Print Button location first.")
            return

        total = len(self.student_ids)
        msg = f"You are about to process {total} students.\n\nThe application will automatically enter each Student ID"
        if not self.config.dry_run:
            msg += " and click the Print button."
        else:
            msg += " (DRY RUN MODE - Print will NOT be clicked)."

        msg += "\n\nContinue?"

        if not messagebox.askyesno("Confirm Automation", msg):
            return

        self.is_processing = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_pause.config(text="PAUSE", bg="#ffc107")
        self.automation.reset_controls()

        self.logger.log("Starting automation batch...")
        self.automation_thread = threading.Thread(target=self._run_automation_loop, daemon=True)
        self.automation_thread.start()

    def _pause_automation(self):
        if not self.is_processing:
            return

        if self.automation.pause_event.is_set():
            self.automation.pause_event.clear()
            self.btn_pause.config(text="RESUME", bg="#17a2b8")
            self.lbl_status.config(text="Status: PAUSED")
            self.logger.log("Automation PAUSED")
        else:
            self.automation.pause_event.set()
            self.btn_pause.config(text="PAUSE", bg="#ffc107")
            self.lbl_status.config(text="Status: Resuming...")
            self.logger.log("Automation RESUMED")

    def _stop_automation(self):
        if not self.is_processing:
            return

        self.automation.stop_event.set()
        self.automation.pause_event.set()
        self.logger.log("STOP requested by user.")
        self.lbl_status.config(text="Status: Stopping...")

    def _run_automation_loop(self):
        total = len(self.student_ids)
        printed = 0
        skipped = 0
        errors = 0
        start_time = time.time()

        while self.student_ids:
            if self.automation.stop_event.is_set():
                break

            sid = self.student_ids[0]
            processed_count = printed + skipped + errors + 1
            self._update_progress_ui(sid, processed_count, total)
            self.logger.log(f"Processing student {sid} ({processed_count}/{total})")

            success, msg = self.automation.process_single_student(sid)

            if success:
                printed += 1
                self.student_ids.pop(0)
                self.root.after(0, lambda: self.student_listbox.delete(0))
            else:
                if self.automation.stop_event.is_set():
                    self.logger.log(f"Batch stopped on student {sid}")
                    break

                self.logger.error(msg)

                # Show timeout modal prompt on main GUI thread
                user_choice = self._prompt_timeout_dialog(sid, msg)
                if user_choice == "retry":
                    # Retry current student
                    self.logger.log(f"User chose RETRY for student {sid}")
                    retry_success, retry_msg = self.automation.process_single_student(sid)
                    if retry_success:
                        printed += 1
                        self.student_ids.pop(0)
                        self.root.after(0, lambda: self.student_listbox.delete(0))
                    else:
                        errors += 1
                        self.student_ids.pop(0)
                        self.root.after(0, lambda: self.student_listbox.delete(0))
                elif user_choice == "skip":
                    self.logger.log(f"User chose SKIP for student {sid}")
                    skipped += 1
                    self.student_ids.pop(0)
                    self.root.after(0, lambda: self.student_listbox.delete(0))
                else:  # stop
                    self.logger.log(f"User chose STOP on student {sid}")
                    self.automation.stop_event.set()
                    break

        elapsed = time.strftime("%H:%M:%S", time.gmtime(time.time() - start_time))
        
        self.root.after(0, lambda: self._show_summary(total, printed, skipped, errors, elapsed))
        self.is_processing = False

    def _update_progress_ui(self, student_id: str, current: int, total: int):
        def _upd():
            self.lbl_curr_student.config(text=f"Current Student: {student_id}")
            pct = (current / total) * 100
            self.lbl_prog_stats.config(text=f"Progress: {current} / {total} ({pct:.1f}%)")
            self.progress_bar['value'] = pct
            self.lbl_status.config(text=f"Status: Processing {student_id}...")
        self.root.after(0, _upd)

    def _prompt_timeout_dialog(self, student_id: str, error_msg: str) -> str:
        res_var = tk.StringVar(value="stop")

        def _ask():
            dialog = tk.Toplevel(self.root)
            dialog.title("Student Search Timeout")
            dialog.geometry("400x200")
            dialog.grab_set()

            ttk.Label(dialog, text="Student Search Timeout", font=("Arial", 11, "bold"), foreground="red").pack(pady=5)
            ttk.Label(dialog, text=f"Student ID: {student_id}\n\n{error_msg}").pack(pady=5)

            btn_box = ttk.Frame(dialog)
            btn_box.pack(pady=15)

            def _choose(val):
                res_var.set(val)
                dialog.destroy()

            ttk.Button(btn_box, text="Retry", command=lambda: _choose("retry")).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_box, text="Skip", command=lambda: _choose("skip")).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_box, text="Stop", command=lambda: _choose("stop")).pack(side=tk.LEFT, padx=5)

            dialog.wait_window()

        self.root.after(0, _ask)
        # Wait for user input safely
        while self.root.winfo_exists():
            try:
                if res_var.get() != "stop" or not self.is_processing:
                    break
            except Exception:
                break
            time.sleep(0.1)

        return res_var.get()

    def _show_summary(self, total: int, printed: int, skipped: int, errors: int, elapsed: str):
        self.btn_start.config(state=tk.NORMAL)
        self.btn_pause.config(text="PAUSE", bg="#ffc107")
        self.lbl_status.config(text="Status: Complete")
        self.lbl_curr_student.config(text="Current Student: None")

        summary_msg = (
            f"Printing Complete\n\n"
            f"Total Students:       {total}\n"
            f"Successfully Printed: {printed}\n"
            f"Skipped:              {skipped}\n"
            f"Errors:               {errors}\n\n"
            f"Elapsed Time: {elapsed}"
        )
        self.logger.log("==========================================")
        self.logger.log(summary_msg.replace("\n\n", " - "))
        self.logger.log("==========================================")

        messagebox.showinfo("Printing Complete", summary_msg)

    def _check_automation_status(self):
        """Periodic status check loop on Tkinter thread."""
        if self.automation.emergency_stop_triggered:
            self._stop_automation()
            self.automation.emergency_stop_triggered = False
            messagebox.showerror("Emergency Stop", "Automation stopped via Emergency Hotkey (ESC key) or Mouse Corner!")
        
        self.root.after(200, self._check_automation_status)
