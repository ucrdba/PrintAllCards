import sys
import os
import ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
from typing import List

import pyautogui
import pyperclip
from pynput import mouse
try:
    import win32print
except ImportError:
    win32print = None

from config import AppConfig
from logger import AppLogger
from excel_handler import ExcelHandler
from automation import AutomationController
from version import APP_VERSION


class ToolTip:
    """Creates a floating mouse-hover tooltip popup over GUI widgets."""
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)

        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#ffffe1", foreground="#333333",
            relief=tk.SOLID, borderwidth=1,
            font=("Arial", 9, "normal"), padx=6, pady=4
        )
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


class ThermometerGauge(tk.Canvas):
    """Custom canvas-based vertical thermometer gauge to visualize print queue load."""
    def __init__(self, parent, width=120, height=260, max_val=20, **kwargs):
        super().__init__(parent, width=width, height=height, bg=kwargs.get('bg', '#f4f6f8'), highlightthickness=0)
        self.width = width
        self.height = height
        self.max_val = max_val
        self.current_val = 0
        self.draw_gauge()

    def set_value(self, val: int, max_val: int = None):
        if max_val is not None and max_val > 0:
            self.max_val = max_val
        self.current_val = max(0, val)
        self.draw_gauge()

    def draw_gauge(self):
        self.delete("all")
        cx = self.width // 2 - 10
        top_y = 35
        bottom_y = self.height - 45
        bulb_radius = 18
        stem_width = 16

        # Color gradient based on queue level
        val = self.current_val
        if val == 0:
            fill_color = "#28a745"  # Green - Empty/Idle
        elif val < 5:
            fill_color = "#17a2b8"  # Teal - Light activity
        elif val < 10:
            fill_color = "#ffc107"  # Yellow/Gold - Moderate
        elif val < 15:
            fill_color = "#fd7e14"  # Orange - High load
        else:
            fill_color = "#dc3545"  # Red - Heavy queue load

        # Stem background (glass tube)
        stem_left = cx - stem_width // 2
        stem_right = cx + stem_width // 2
        self.create_rectangle(stem_left, top_y, stem_right, bottom_y, fill="#e9ecef", outline="#adb5bd", width=2)

        # Bulb background & fill (bottom)
        bulb_y = bottom_y + bulb_radius - 2
        self.create_oval(cx - bulb_radius, bulb_y - bulb_radius, cx + bulb_radius, bulb_y + bulb_radius, fill=fill_color, outline="#6c757d", width=2)

        # Calculate fluid level stem height
        fill_pct = min(1.0, val / max(1, self.max_val))
        fluid_height = fill_pct * (bottom_y - top_y)
        fluid_top_y = bottom_y - fluid_height

        if fluid_height > 0:
            self.create_rectangle(stem_left + 2, fluid_top_y, stem_right - 2, bottom_y + 4, fill=fill_color, outline="")

        # Tick marks & labels
        tick_steps = 4
        for i in range(tick_steps + 1):
            tick_val = int((self.max_val / tick_steps) * i)
            ty = bottom_y - (i / tick_steps) * (bottom_y - top_y)
            self.create_line(stem_right + 2, ty, stem_right + 10, ty, fill="#495057", width=1.5)
            self.create_text(stem_right + 14, ty, text=str(tick_val), anchor=tk.W, font=("Arial", 8, "bold"), fill="#495057")

        # Glass shine highlight on stem
        self.create_line(stem_left + 3, top_y + 2, stem_left + 3, bottom_y - 2, fill="#ffffff", width=1.5)

        # Numeric value callout badge inside gauge top banner
        self.create_rectangle(5, 5, self.width - 5, 28, fill="#ffffff", outline="#ced4da", width=1)
        text_color = fill_color if val > 0 else "#28a745"
        self.create_text(self.width // 2, 16, text=f"{val} JOBS", font=("Arial", 10, "bold"), fill=text_color)


class AppGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Student Photo Print Automator v{APP_VERSION}")
        self.root.geometry("850x700")
        self.root.minsize(700, 500)

        # Set application icon (supports PyInstaller bundle and Windows Taskbar)
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
        icon_ico = os.path.join(base_dir, 'app_icon.ico')
        icon_png = os.path.join(base_dir, 'app_icon.png')

        if os.path.exists(icon_ico):
            try:
                self.root.iconbitmap(icon_ico)
            except Exception:
                pass

        if os.path.exists(icon_png):
            try:
                from PIL import Image, ImageTk
                photo = ImageTk.PhotoImage(Image.open(icon_png))
                self.root.iconphoto(True, photo)
            except Exception:
                pass

        self.config = AppConfig.load()
        self.logger = AppLogger(gui_callback=self.append_log)
        self.automation = AutomationController(self.config, self.logger)
        self.automation.get_queue_job_count = self._get_current_queue_job_count
        self.automation.show_trail = self._show_mouse_trail

        # Lazily-created click-through overlay used to draw the mouse trail
        self._trail_overlay = None
        self._trail_canvas = None
        self._trail_origin = (0, 0)

        self.student_ids: List[str] = []
        self.processed_history: List[dict] = []
        self.initial_total_count = 0
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

        # Outer Canvas with Scrollbar for responsive window sizing across different screen resolution/DPI displays
        container_canvas = tk.Canvas(self.root, highlightthickness=0)
        v_scrollbar = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=container_canvas.yview)
        
        main_frame = ttk.Frame(container_canvas, padding="10")
        main_frame.bind(
            "<Configure>",
            lambda e: container_canvas.configure(scrollregion=container_canvas.bbox("all"))
        )

        canvas_window = container_canvas.create_window((0, 0), window=main_frame, anchor="nw")

        def _on_canvas_configure(event):
            container_canvas.itemconfig(canvas_window, width=event.width)

        container_canvas.bind("<Configure>", _on_canvas_configure)
        container_canvas.configure(yscrollcommand=v_scrollbar.set)

        # Mouse wheel scrolling support
        def _on_mousewheel(event):
            container_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        container_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        container_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Title Banner Row with Help Button
        title_box = ttk.Frame(main_frame)
        title_box.pack(fill=tk.X, pady=(0, 10))

        title_label = ttk.Label(title_box, text=f"STUDENT PHOTO PRINT AUTOMATOR v{APP_VERSION}", font=("Arial", 14, "bold"))
        title_label.pack(side=tk.LEFT)

        btn_app_help = ttk.Button(title_box, text="❓ Help & Guide", command=self._show_help_guide)
        btn_app_help.pack(side=tk.RIGHT)
        ToolTip(btn_app_help, "Opens the interactive User Guide & Timing Reference handbook.")

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

        # Toolbar Card: Import Action Buttons (Top) & Radiobuttons directly underneath (Right-aligned)
        toolbar = ttk.Frame(excel_frame)
        toolbar.pack(fill=tk.X, pady=(0, 6))

        # Row 1: Loaded File status on left, Import Buttons on right
        row1 = ttk.Frame(toolbar)
        row1.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(row1, text="📄 Loaded File:", font=("Arial", 8, "bold"), foreground="#495057").pack(side=tk.LEFT, padx=(0, 4))
        self.lbl_file_path = ttk.Label(row1, text="No file selected", font=("Arial", 8), foreground="#6c757d")
        self.lbl_file_path.pack(side=tk.LEFT, fill=tk.X, expand=True)

        btn_box = ttk.Frame(row1)
        btn_box.pack(side=tk.RIGHT)

        self.btn_excel = ttk.Button(btn_box, text="Import Excel/CSV", command=self._select_excel_file)
        self.btn_excel.pack(side=tk.LEFT, padx=2)
        ToolTip(self.btn_excel, "Imports photographed student records from an Excel (.xlsx/.xls) or CSV file.")

        self.btn_sync_zip = ttk.Button(btn_box, text="Import Sync File(s)", command=self._select_sync_zip_file)
        self.btn_sync_zip.pack(side=tk.LEFT, padx=2)
        ToolTip(self.btn_sync_zip, "Imports student records from sync archive zip file(s).")

        # Row 2: Radiobuttons placed directly under the two import buttons (right-aligned)
        row2 = ttk.Frame(toolbar)
        row2.pack(fill=tk.X, pady=(2, 0))

        radio_box = ttk.Frame(row2)
        radio_box.pack(side=tk.RIGHT, padx=2)

        ttk.Label(radio_box, text="Mode:", font=("Arial", 8, "bold")).pack(side=tk.LEFT, padx=(0, 2))
        self.var_import_mode = tk.StringVar(value="single")
        rb_single = ttk.Radiobutton(radio_box, text="Single", value="single", variable=self.var_import_mode)
        rb_single.pack(side=tk.LEFT, padx=3)
        ToolTip(rb_single, "Single Mode: Replaces the current student list when importing a file.")

        rb_append = ttk.Radiobutton(radio_box, text="Multiple", value="append", variable=self.var_import_mode)
        rb_append.pack(side=tk.LEFT, padx=3)
        ToolTip(rb_append, "Multiple Mode: Allows selecting multiple files to append and merge into the current list.")

        self.lbl_found_count = ttk.Label(excel_frame, text="0 PHOTOGRAPHED STUDENTS FOUND", font=("Arial", 9, "bold"), foreground="#0066cc")
        self.lbl_found_count.pack(anchor=tk.W, pady=(4, 6))

        # Quick Search / Filter Bar for Student List
        filter_box = ttk.Frame(excel_frame)
        filter_box.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(filter_box, text="🔍 Search (ID / Name):", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(0, 4))
        self.ent_filter_list = ttk.Entry(filter_box)
        self.ent_filter_list.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.ent_filter_list.bind("<KeyRelease>", lambda e: self._on_filter_list_changed())
        ToolTip(self.ent_filter_list, "Type student ID, first name, last name, or grade to highlight matching students.")

        btn_clear_filter = ttk.Button(filter_box, text="Clear", width=6, command=self._clear_list_filter)
        btn_clear_filter.pack(side=tk.RIGHT)
        ToolTip(btn_clear_filter, "Clears the search text filter.")

        # Student Treeview Table (Sortable Columns)
        tree_frame = ttk.Frame(excel_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        columns = ("id", "first_name", "last_name", "grade")
        self.student_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=10, selectmode="extended")
        ToolTip(self.student_tree, "Right-click anywhere inside table to open context menu (Copy ID, Remove, Clear All). Double-click copies ID.")
        
        self.student_tree.heading("id", text="Student ID ↕", command=lambda: self._sort_treeview("id", False))
        self.student_tree.heading("first_name", text="First Name ↕", command=lambda: self._sort_treeview("first_name", False))
        self.student_tree.heading("last_name", text="Last Name ↕", command=lambda: self._sort_treeview("last_name", False))
        self.student_tree.heading("grade", text="Grade ↕", command=lambda: self._sort_treeview("grade", False))

        self.student_tree.column("id", width=110, minwidth=80)
        self.student_tree.column("first_name", width=120, minwidth=80)
        self.student_tree.column("last_name", width=120, minwidth=80)
        self.student_tree.column("grade", width=60, minwidth=40)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.student_tree.yview)
        self.student_tree.config(yscrollcommand=scrollbar.set)
        
        self.student_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Track sorting states
        self.sort_reverse = {"id": False, "first_name": False, "last_name": False, "grade": False}
        self.student_records: List[dict] = []

        # Save / Load remaining student list buttons
        export_btn_box = ttk.Frame(excel_frame)
        export_btn_box.pack(fill=tk.X, pady=(5, 0))

        btn_remove_student = ttk.Button(export_btn_box, text="🗑️ Remove Selected", command=self._remove_selected_student)
        btn_remove_student.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_remove_student, "Deletes highlighted student row(s) from the list.")

        btn_remove_prior = ttk.Button(export_btn_box, text="✂️ Delete Prior", command=self._remove_prior_students)
        btn_remove_prior.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_remove_prior, "Removes all student rows above the highlighted student ID.")

        btn_restore_prior = ttk.Button(export_btn_box, text="↩️ Restore Prior N", command=self._restore_previous_students)
        btn_restore_prior.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_restore_prior, "Restores the last N processed/deleted students back to the top of the queue.")

        btn_save_list = ttk.Button(export_btn_box, text="Save Remaining List", command=self._save_remaining_list)
        btn_save_list.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ToolTip(btn_save_list, "Exports unprinted remaining student records to a CSV/XLSX file.")

        btn_load_list = ttk.Button(export_btn_box, text="Load Saved List", command=self._load_saved_list)
        btn_load_list.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=2)
        ToolTip(btn_load_list, "Loads a previously saved student list back into the table.")

        # Bind Delete / Backspace keys to Treeview for quick removal
        self.student_tree.bind("<Delete>", lambda e: self._remove_selected_student())
        self.student_tree.bind("<BackSpace>", lambda e: self._remove_selected_student())
        # Bind double-click to copy Student ID to clipboard (paste buffer)
        self.student_tree.bind("<Double-1>", self._on_student_double_click)
        # Bind Ctrl+C to copy all selected Student ID(s), one per line
        self.student_tree.bind("<Control-c>", self._copy_selected_students)
        self.student_tree.bind("<Control-C>", self._copy_selected_students)
        # Bind right-click to show context menu
        self.student_tree.bind("<Button-3>", self._show_tree_context_menu)

        # Right-click context menu
        self.tree_context_menu = tk.Menu(self.root, tearoff=0)
        self.tree_context_menu.add_command(label="📋 Copy Student ID(s)", command=self._copy_selected_students)
        self.tree_context_menu.add_command(label="🗑️ Remove Selected", command=self._remove_selected_student)
        self.tree_context_menu.add_command(label="✂️ Delete Prior", command=self._remove_prior_students)
        self.tree_context_menu.add_command(label="↩️ Restore Previous N Students", command=self._restore_previous_students)
        self.tree_context_menu.add_separator()
        self.tree_context_menu.add_command(label="⚠️ Clear Entire List", command=self._clear_entire_student_list)

        # Backward-compatibility alias
        self.student_listbox = self.student_tree

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
        ToolTip(btn_pick_search, "Captures mouse cursor coordinates over the StudentSearch input box (3 sec delay).")

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
        ToolTip(btn_pick_print, "Captures mouse cursor coordinates over the Print Card action button (3 sec delay).")

        # Card Type Location
        c_row = ttk.Frame(loc_frame)
        c_row.pack(fill=tk.X, pady=3)
        ttk.Label(c_row, text="Card Type:", width=15).pack(side=tk.LEFT)
        ttk.Label(c_row, text="X:").pack(side=tk.LEFT)
        self.ent_card_type_x = ttk.Entry(c_row, width=6)
        self.ent_card_type_x.pack(side=tk.LEFT, padx=2)
        ttk.Label(c_row, text="Y:").pack(side=tk.LEFT)
        self.ent_card_type_y = ttk.Entry(c_row, width=6)
        self.ent_card_type_y.pack(side=tk.LEFT, padx=2)
        btn_pick_card_type = ttk.Button(c_row, text="Select Location", command=lambda: self._capture_location("Card Type"))
        btn_pick_card_type.pack(side=tk.RIGHT)
        ToolTip(btn_pick_card_type, "Optional. Captures mouse cursor coordinates over the Card Type selector (3 sec delay). Only used when 'Required' is checked.")

        # 'Required' sits on its own line under the Card Type coordinates: the row above
        # is already at the full width of the right pane, so the label would be clipped.
        cr_row = ttk.Frame(loc_frame)
        cr_row.pack(fill=tk.X)
        ttk.Label(cr_row, text="", width=15).pack(side=tk.LEFT)
        self.var_card_type_required = tk.BooleanVar(value=getattr(self.config, 'card_type_required', False))
        chk_card_type_required = ttk.Checkbutton(cr_row, text="Required (click for every student)", variable=self.var_card_type_required)
        chk_card_type_required.pack(side=tk.LEFT)
        ToolTip(chk_card_type_required, "When checked, the Card Type location is clicked for every student, immediately before Print. When unchecked, Card Type is never clicked.")

        # --- SECTION 3: TIMING & CONFIG ---
        timing_frame = ttk.LabelFrame(right_pane, text="TIMING & OPTIONS", padding="8")
        timing_frame.pack(fill=tk.X, pady=5)

        t_grid = ttk.Frame(timing_frame)
        t_grid.pack(fill=tk.X)

        lbl_delay_start = ttk.Label(t_grid, text="Search Start Delay (s):")
        lbl_delay_start.grid(row=0, column=0, sticky=tk.W, pady=2)
        self.ent_delay_start = ttk.Entry(t_grid, width=8)
        self.ent_delay_start.grid(row=0, column=1, padx=5, pady=2)
        ToolTip(self.ent_delay_start, "Delay (in seconds) after clicking the StudentSearch box before pasting Student ID.")

        lbl_delay_wait = ttk.Label(t_grid, text="Max Search Wait (s):")
        lbl_delay_wait.grid(row=1, column=0, sticky=tk.W, pady=2)
        self.ent_delay_wait = ttk.Entry(t_grid, width=8)
        self.ent_delay_wait.grid(row=1, column=1, padx=5, pady=2)
        ToolTip(self.ent_delay_wait, "Maximum seconds to wait for StudentSearch to verify and locate the student record before timing out.")

        lbl_delay_print = ttk.Label(t_grid, text="Print Delay (s):")
        lbl_delay_print.grid(row=2, column=0, sticky=tk.W, pady=2)
        self.ent_delay_print = ttk.Entry(t_grid, width=8)
        self.ent_delay_print.grid(row=2, column=1, padx=5, pady=2)
        ToolTip(self.ent_delay_print, "Delay (in seconds) after clicking Print to allow card print job to queue in Windows.")

        lbl_delay_between = ttk.Label(t_grid, text="Between Student Delay (s):")
        lbl_delay_between.grid(row=3, column=0, sticky=tk.W, pady=2)
        self.ent_delay_between = ttk.Entry(t_grid, width=8)
        self.ent_delay_between.grid(row=3, column=1, padx=5, pady=2)
        ToolTip(self.ent_delay_between, "Buffer delay (in seconds) between completing one student card and starting the next.")

        lbl_print_hotkey = ttk.Label(t_grid, text="Print Hotkey (e.g. ctrl+p):")
        lbl_print_hotkey.grid(row=4, column=0, sticky=tk.W, pady=2)
        self.ent_print_hotkey = ttk.Entry(t_grid, width=8)
        self.ent_print_hotkey.grid(row=4, column=1, padx=5, pady=2)
        ToolTip(self.ent_print_hotkey, "Keyboard hotkey trigger to issue Print command (e.g. 'ctrl+p') if mouse click location is not used.")

        # Action Buttons Row (Load Defaults & Clear Fields)
        btn_action_row = ttk.Frame(timing_frame)
        btn_action_row.pack(fill=tk.X, pady=(5, 0))

        btn_load_defaults = ttk.Button(btn_action_row, text="Load Default Values", command=self._load_default_values)
        btn_load_defaults.pack(side=tk.LEFT, padx=(0, 4))
        ToolTip(btn_load_defaults, "Resets all timing delays and options back to recommended default values.")

        btn_clear_fields = ttk.Button(btn_action_row, text="Clear All Fields", command=self._clear_all_fields)
        btn_clear_fields.pack(side=tk.LEFT)
        ToolTip(btn_clear_fields, "Clears all location coordinates and timing entry boxes.")

        # Checkboxes
        self.var_mouse_trail = tk.BooleanVar(value=self.config.enable_mouse_trail)
        chk_trail = ttk.Checkbutton(timing_frame, text="Enable Visible Mouse Movement Trail", variable=self.var_mouse_trail)
        ToolTip(chk_trail, "Draws an on-screen arrow and target ring for every automated click, and moves the cursor slowly instead of jumping, so you can see exactly where each click lands. Useful for troubleshooting wrong coordinates.")
        chk_trail.pack(anchor=tk.W, pady=(5, 0))
        ToolTip(chk_trail, "Smoothly animates mouse cursor movements so you can see where clicks take place.")

        self.var_require_verification = tk.BooleanVar(value=self.config.require_verification)
        chk_verify = ttk.Checkbutton(timing_frame, text="Require Strict StudentSearch Verification", variable=self.var_require_verification)
        chk_verify.pack(anchor=tk.W, pady=(2, 0))
        ToolTip(chk_verify, "Verifies that StudentSearch successfully loads the student record before issuing Print.")

        self.var_dry_run = tk.BooleanVar(value=self.config.dry_run)
        chk_dry_run = ttk.Checkbutton(timing_frame, text="Dry Run (Do not click Print)", variable=self.var_dry_run)
        chk_dry_run.pack(anchor=tk.W, pady=(2, 0))
        ToolTip(chk_dry_run, "Simulates card search without actually clicking the Print button.")

        # --- SECTION 4: TEST BUTTONS ---
        test_frame = ttk.LabelFrame(right_pane, text="TESTING", padding="8")
        test_frame.pack(fill=tk.X, pady=5)

        test_btn_box = ttk.Frame(test_frame)
        test_btn_box.pack(fill=tk.X)
        
        btn_test_student = ttk.Button(test_btn_box, text="Test Current Student", command=self._test_current_student)
        btn_test_student.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ToolTip(btn_test_student, "Tests searching for the highlighted student ID without triggering a print job.")

        btn_test_print = ttk.Button(test_btn_box, text="Test Print", command=self._test_print_button)
        btn_test_print.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=2)
        ToolTip(btn_test_print, "Issues a single click on the configured Print Button location after 1 second.")

        # --- SECTION 4.5: PRINT QUEUE MONITOR ---
        queue_frame = ttk.LabelFrame(right_pane, text="PRINT QUEUE MONITOR", padding="8")
        queue_frame.pack(fill=tk.X, pady=5)

        q_top_box = ttk.Frame(queue_frame)
        q_top_box.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(q_top_box, text="Printer Queue:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(0, 4))
        
        self.combo_printers = ttk.Combobox(q_top_box, state="readonly")
        self.combo_printers.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.combo_printers.bind("<<ComboboxSelected>>", self._on_printer_selected)
        ToolTip(self.combo_printers, "Select the target Windows printer queue to monitor.")

        btn_refresh_printers = ttk.Button(q_top_box, text="🔄", width=3, command=self._refresh_printer_list)
        btn_refresh_printers.pack(side=tk.RIGHT)
        ToolTip(btn_refresh_printers, "Refreshes the list of installed local and network printers.")

        # Monitor container layout (Thermometer Gauge Left, Stats Info Right)
        q_body_box = ttk.Frame(queue_frame)
        q_body_box.pack(fill=tk.X, pady=2)

        self.thermometer = ThermometerGauge(q_body_box, width=120, height=220, max_val=20)
        self.thermometer.pack(side=tk.LEFT, padx=(5, 15))
        ToolTip(self.thermometer, "Thermometer gauge visualizer showing real-time active print jobs in queue.")

        q_info_frame = ttk.Frame(q_body_box)
        q_info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.lbl_queue_printer = ttk.Label(q_info_frame, text="Selected: --", font=("Arial", 9, "bold"))
        self.lbl_queue_printer.pack(anchor=tk.W, pady=2)

        self.lbl_queue_jobs = ttk.Label(q_info_frame, text="Active Queue Jobs: 0", font=("Arial", 10, "bold"), foreground="#0066cc")
        self.lbl_queue_jobs.pack(anchor=tk.W, pady=2)

        self.lbl_queue_status = ttk.Label(q_info_frame, text="Printer Status: Ready / Idle", font=("Arial", 9))
        self.lbl_queue_status.pack(anchor=tk.W, pady=2)

        self.lbl_queue_timing = ttk.Label(q_info_frame, text="⏱️ Job Timing: Min: -- | Max: -- | Avg: --", font=("Arial", 9, "bold"), foreground="#28a745")
        self.lbl_queue_timing.pack(anchor=tk.W, pady=(4, 2))
        ToolTip(self.lbl_queue_timing, "Real-time Minimum, Maximum, and Average completion duration for card jobs in this batch.")

        self.var_auto_poll_queue = tk.BooleanVar(value=True)
        chk_poll = ttk.Checkbutton(q_info_frame, text="Auto-Monitor Queue (1s)", variable=self.var_auto_poll_queue)
        chk_poll.pack(anchor=tk.W, pady=(4, 0))
        ToolTip(chk_poll, "Automatically queries Windows print queue depth every 1 second.")

        # --- Queue Batch Sync Throttling Controls ---
        q_sync_box = ttk.Frame(q_info_frame)
        q_sync_box.pack(anchor=tk.W, pady=(6, 0))

        self.var_queue_sync = tk.BooleanVar(value=getattr(self.config, 'enable_queue_sync', True))
        chk_sync = ttk.Checkbutton(q_sync_box, text="Sync Batch with Queue (Pause when full)", variable=self.var_queue_sync, command=self._save_queue_sync_settings)
        chk_sync.pack(anchor=tk.W)
        ToolTip(chk_sync, "Pauses batch card printing whenever active printer queue reaches your Max Running Jobs limit.")

        q_thresh_row = ttk.Frame(q_sync_box)
        q_thresh_row.pack(anchor=tk.W, pady=(2, 0))

        ttk.Label(q_thresh_row, text="Max Running Jobs: ", font=("Arial", 9)).pack(side=tk.LEFT)
        self.ent_max_jobs = ttk.Entry(q_thresh_row, width=5, justify="center", font=("Arial", 9, "bold"))
        self.ent_max_jobs.pack(side=tk.LEFT, padx=2)
        self.ent_max_jobs.bind("<KeyRelease>", lambda e: self._save_queue_sync_settings())
        ttk.Label(q_thresh_row, text="jobs", font=("Arial", 9)).pack(side=tk.LEFT)
        ToolTip(self.ent_max_jobs, "Maximum number of active jobs allowed in print queue before automation pauses.")

        btn_poll_now = ttk.Button(q_info_frame, text="Check Queue Now", command=self._poll_print_queue)
        btn_poll_now.pack(anchor=tk.W, pady=(5, 0))
        ToolTip(btn_poll_now, "Immediately checks active Windows printer job count and status.")

        # --- SECTION 5: CONTROL BUTTONS ---
        control_frame = ttk.LabelFrame(main_frame, text="CONTROL", padding="8")
        control_frame.pack(fill=tk.X, pady=5)

        ctrl_box = ttk.Frame(control_frame)
        ctrl_box.pack(fill=tk.X)

        self.btn_start = tk.Button(ctrl_box, text="START", bg="#28a745", fg="white", font=("Arial", 11, "bold"), command=self._start_automation)
        self.btn_start.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ToolTip(self.btn_start, "Starts batch card photo printing automation.")

        self.btn_pause = tk.Button(ctrl_box, text="PAUSE", bg="#ffc107", fg="black", font=("Arial", 11, "bold"), command=self._pause_automation)
        self.btn_pause.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ToolTip(self.btn_pause, "Pauses/Resumes card automation after current student completes.")

        self.btn_stop = tk.Button(ctrl_box, text="STOP", bg="#dc3545", fg="white", font=("Arial", 11, "bold"), command=self._stop_automation)
        self.btn_stop.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        ToolTip(self.btn_stop, "Halts batch automation immediately.")

        # Pause after N cards row (placed under PAUSE button)
        pause_cfg_row = ttk.Frame(control_frame)
        pause_cfg_row.pack(fill=tk.X, pady=(6, 2))

        pause_inner = ttk.Frame(pause_cfg_row)
        pause_inner.pack(anchor=tk.CENTER)

        ttk.Label(pause_inner, text="Pause after every", font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.ent_pause_after = ttk.Entry(pause_inner, width=5, justify="center", font=("Arial", 9, "bold"))
        self.ent_pause_after.pack(side=tk.LEFT, padx=2)
        self.ent_pause_after.bind("<KeyRelease>", lambda e: self._on_pause_setting_changed())
        ttk.Label(pause_inner, text="cards", font=("Arial", 9)).pack(side=tk.LEFT, padx=(4, 4))

        self.lbl_pause_countdown = ttk.Label(pause_inner, text="(No Auto-Pause)", font=("Arial", 9, "bold"), foreground="gray")
        self.lbl_pause_countdown.pack(side=tk.LEFT, padx=(4, 0))

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

        lbl_status_box = ttk.Frame(prog_frame)
        lbl_status_box.pack(fill=tk.X)

        self.lbl_status = ttk.Label(lbl_status_box, text="Status: Ready", font=("Arial", 9, "italic"), foreground="gray")
        self.lbl_status.pack(side=tk.LEFT)

        self.lbl_eta = ttk.Label(lbl_status_box, text="Estimated Time Remaining: --", font=("Arial", 9, "bold"), foreground="#0066cc")
        self.lbl_eta.pack(side=tk.RIGHT)

        lbl_timing_box = ttk.Frame(prog_frame)
        lbl_timing_box.pack(fill=tk.X, pady=(4, 0))

        self.lbl_timing_stats = ttk.Label(lbl_timing_box, text="⏱️ Job Timing: Min: -- | Max: -- | Avg: --", font=("Arial", 9, "bold"), foreground="#28a745")
        self.lbl_timing_stats.pack(anchor=tk.W)

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
        self.ent_card_type_x.insert(0, str(getattr(self.config, 'card_type_x', 0)))
        self.ent_card_type_y.insert(0, str(getattr(self.config, 'card_type_y', 0)))

        self.ent_delay_start.insert(0, str(self.config.search_start_delay))
        self.ent_delay_wait.insert(0, str(self.config.max_search_wait))
        self.ent_delay_print.insert(0, str(self.config.print_delay))
        self.ent_delay_between.insert(0, str(self.config.between_student_delay))
        pause_val = getattr(self.config, 'pause_after_cards', 0)
        self.ent_pause_after.insert(0, str(pause_val))
        self._update_pause_countdown(pause_val)

        if hasattr(self, 'ent_max_jobs'):
            self.ent_max_jobs.delete(0, tk.END)
            self.ent_max_jobs.insert(0, str(getattr(self.config, 'max_queue_jobs', 5)))

        self._refresh_printer_list()
        self._start_queue_polling_loop()

    def _on_pause_setting_changed(self):
        """Called when user edits the pause after cards entry box."""
        try:
            val_str = self.ent_pause_after.get().strip()
            val = int(val_str) if val_str else 0
            self._update_pause_countdown(val)
        except ValueError:
            pass

    def _update_pause_countdown(self, remaining: int):
        """Updates the live pause countdown label in the CONTROL section."""
        if not hasattr(self, 'lbl_pause_countdown'):
            return

        try:
            val_str = self.ent_pause_after.get().strip()
            pause_limit = int(val_str) if val_str else 0
        except ValueError:
            pause_limit = getattr(self.config, 'pause_after_cards', 0)

        if pause_limit <= 0:
            self.lbl_pause_countdown.config(text="(No Auto-Pause / 0 = All)", foreground="gray")
        elif remaining == 0:
            self.lbl_pause_countdown.config(text="(Remaining: 0 - PAUSED)", foreground="#cc6600")
        else:
            self.lbl_pause_countdown.config(text=f"(Remaining: {remaining})", foreground="#0066cc")

    def _load_default_values(self):
        """Loads recommended default timing values and option settings into GUI entry boxes."""
        default_cfg = AppConfig()

        self.ent_delay_start.delete(0, tk.END)
        self.ent_delay_start.insert(0, str(default_cfg.search_start_delay))

        self.ent_delay_wait.delete(0, tk.END)
        self.ent_delay_wait.insert(0, str(default_cfg.max_search_wait))

        self.ent_delay_print.delete(0, tk.END)
        self.ent_delay_print.insert(0, str(default_cfg.print_delay))

        self.ent_delay_between.delete(0, tk.END)
        self.ent_delay_between.insert(0, str(default_cfg.between_student_delay))

        self.ent_print_hotkey.delete(0, tk.END)
        self.ent_print_hotkey.insert(0, str(default_cfg.print_hotkey))

        self.ent_pause_after.delete(0, tk.END)
        self.ent_pause_after.insert(0, str(default_cfg.pause_after_cards))
        self._update_pause_countdown(default_cfg.pause_after_cards)

        self.var_mouse_trail.set(default_cfg.enable_mouse_trail)
        self.var_require_verification.set(default_cfg.require_verification)
        self.var_dry_run.set(default_cfg.dry_run)
        self.var_card_type_required.set(default_cfg.card_type_required)

        self.logger.log("Loaded default timing and option values into GUI.")

    def _clear_all_fields(self):
        """Clears all text entry fields in the GUI."""
        self.ent_search_x.delete(0, tk.END)
        self.ent_search_y.delete(0, tk.END)
        self.ent_print_x.delete(0, tk.END)
        self.ent_print_y.delete(0, tk.END)
        self.ent_card_type_x.delete(0, tk.END)
        self.ent_card_type_y.delete(0, tk.END)
        self.var_card_type_required.set(False)

        self.ent_delay_start.delete(0, tk.END)
        self.ent_delay_wait.delete(0, tk.END)
        self.ent_delay_print.delete(0, tk.END)
        self.ent_delay_between.delete(0, tk.END)
        self.ent_print_hotkey.delete(0, tk.END)
        self.ent_pause_after.delete(0, tk.END)
        self.ent_pause_after.insert(0, "0")
        self._update_pause_countdown(0)
        self.logger.log("Cleared all configuration input fields.")

    def _save_ui_to_config(self) -> bool:
        try:
            sx = self.ent_search_x.get().strip()
            sy = self.ent_search_y.get().strip()
            px = self.ent_print_x.get().strip()
            py = self.ent_print_y.get().strip()
            cx = self.ent_card_type_x.get().strip()
            cy = self.ent_card_type_y.get().strip()

            d_start = self.ent_delay_start.get().strip()
            d_wait = self.ent_delay_wait.get().strip()
            d_print = self.ent_delay_print.get().strip()
            d_between = self.ent_delay_between.get().strip()
            p_hk = self.ent_print_hotkey.get().strip()
            p_after = self.ent_pause_after.get().strip()

            self.config.search_x = int(sx) if sx else 0
            self.config.search_y = int(sy) if sy else 0
            self.config.print_x = int(px) if px else 0
            self.config.print_y = int(py) if py else 0
            self.config.card_type_x = int(cx) if cx else 0
            self.config.card_type_y = int(cy) if cy else 0

            self.config.search_start_delay = float(d_start) if d_start else 0.5
            self.config.max_search_wait = float(d_wait) if d_wait else 15.0
            self.config.print_delay = float(d_print) if d_print else 2.0
            self.config.between_student_delay = float(d_between) if d_between else 0.5
            self.config.print_hotkey = p_hk if p_hk else "ctrl+p"
            self.config.pause_after_cards = int(p_after) if p_after else 0
            self.config.require_verification = self.var_require_verification.get()
            self.config.enable_mouse_trail = self.var_mouse_trail.get()
            self.config.dry_run = self.var_dry_run.get()
            self.config.card_type_required = self.var_card_type_required.get()

            if hasattr(self, 'var_queue_sync'):
                self.config.enable_queue_sync = self.var_queue_sync.get()
            if hasattr(self, 'ent_max_jobs'):
                m_jobs = self.ent_max_jobs.get().strip()
                if m_jobs:
                    self.config.max_queue_jobs = max(1, int(m_jobs))

            # Validation
            if self.config.search_start_delay < 0 or self.config.max_search_wait < 0 or self.config.print_delay < 0 or self.config.between_student_delay < 0 or self.config.pause_after_cards < 0:
                raise ValueError("Delays and pause limits must be non-negative.")

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

    def _select_sync_zip_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Sync Zip File",
            filetypes=[("Zip Archives", "*.zip"), ("All Files", "*.*")]
        )
        if file_path:
            self._load_sync_zip_file(file_path)

    def _sort_treeview(self, col: str, reverse: bool):
        """Sorts the student Treeview by the clicked column header (ascending/descending)."""
        def _sort_key(item):
            val = item.get(col, '')
            if col == "grade":
                try:
                    return (0, float(val))
                except ValueError:
                    return (1, str(val).lower())
            return str(val).lower()

        self.student_records.sort(key=_sort_key, reverse=reverse)
        self.sort_reverse[col] = not reverse

        # Update column header indicator
        arrow = " ▲" if reverse else " ▼"
        header_labels = {
            "id": "Student ID",
            "first_name": "First Name",
            "last_name": "Last Name",
            "grade": "Grade"
        }
        for c in ("id", "first_name", "last_name", "grade"):
            lbl = header_labels[c] + (arrow if c == col else " ↕")
            self.student_tree.heading(c, text=lbl, command=lambda _c=c, _r=self.sort_reverse[c]: self._sort_treeview(_c, _r))

        self._refresh_treeview_from_records()

    def _clear_list_filter(self):
        """Clears the student list search filter entry."""
        if hasattr(self, 'ent_filter_list'):
            self.ent_filter_list.delete(0, tk.END)
        self.student_tree.selection_remove(self.student_tree.selection())

    def _on_filter_list_changed(self):
        """Searches for matching student ID, first name, last name, or grade in the full list and scrolls to highlight it without hiding other rows."""
        if not hasattr(self, 'ent_filter_list'):
            return

        raw_query = self.ent_filter_list.get().strip().lower()
        if not raw_query:
            return

        # Clean query terms (split by whitespace, remove commas/punctuation)
        query_terms = [term.strip(',;.') for term in raw_query.split() if term.strip(',;.')]
        if not query_terms:
            return

        # Find first matching student record and select/scroll to it
        for r in self.student_records:
            sid = str(r.get('id', '')).lower()
            fn = str(r.get('first_name', '')).lower()
            ln = str(r.get('last_name', '')).lower()
            gr = str(r.get('grade', '')).lower()

            full_searchable = f"{sid} {fn} {ln} {ln}, {fn} {fn} {ln} gr:{gr}".lower()

            # Check if all query terms match somewhere in the student's fields
            if all(term in full_searchable for term in query_terms):
                if self.student_tree.exists(r['id']):
                    self.student_tree.selection_set(r['id'])
                    self.student_tree.focus(r['id'])
                    self.student_tree.see(r['id'])
                break

    def _refresh_treeview_from_records(self):
        """Refreshes Treeview items displaying all loaded student records."""
        for row in self.student_tree.get_children():
            self.student_tree.delete(row)

        self.student_ids = []
        for r in self.student_records:
            sid = r['id']
            self.student_ids.append(sid)
            self.student_tree.insert("", tk.END, iid=sid, values=(sid, r['first_name'], r['last_name'], r['grade']))

        if hasattr(self, 'ent_filter_list'):
            query = self.ent_filter_list.get().strip().lower()
            if query:
                self._on_filter_list_changed()

    def _select_sync_zip_file(self):
        is_multiple = (getattr(self, 'var_import_mode', None) and self.var_import_mode.get() == "append")

        if is_multiple:
            file_paths = filedialog.askopenfilenames(
                title="Select Sync Zip File(s) to Append",
                filetypes=[("Zip Archives", "*.zip"), ("All Files", "*.*")]
            )
            if file_paths:
                for fp in file_paths:
                    self._load_sync_zip_file(fp, append=True)
        else:
            file_path = filedialog.askopenfilename(
                title="Select Sync Zip File",
                filetypes=[("Zip Archives", "*.zip"), ("All Files", "*.*")]
            )
            if file_path:
                self._load_sync_zip_file(file_path, append=False)

    def _load_sync_zip_file(self, file_path: str, append: bool = False):
        records, err = ExcelHandler.load_sync_zip(file_path)

        if err:
            if not append:
                self.student_records = []
                self.student_ids = []
                self._refresh_treeview_from_records()
                self.lbl_found_count.config(text="0 PHOTOGRAPHED STUDENTS FOUND", foreground="red")
            self.logger.error(err)
            messagebox.showerror("Sync Zip Error", err)
            return

        if append:
            existing_ids = {r['id'] for r in self.student_records}
            added_count = 0
            for r in records:
                if r['id'] not in existing_ids:
                    self.student_records.append(r)
                    existing_ids.add(r['id'])
                    added_count += 1
            self.lbl_file_path.config(text=f"Appended {os.path.basename(file_path)}")
            self.logger.log(f"Appended Sync Zip: {os.path.basename(file_path)} ({added_count} new students added, total {len(self.student_records)})")
        else:
            self.lbl_file_path.config(text=os.path.basename(file_path))
            self.student_records = records
            self.logger.log(f"Imported Sync Zip: {os.path.basename(file_path)} ({len(records)} photographed students loaded)")

        self._refresh_treeview_from_records()
        count = len(self.student_ids)
        self.initial_total_count = count
        self._update_progress_from_records()
        self.lbl_found_count.config(text=f"{count} PHOTOGRAPHED STUDENTS FOUND", foreground="#0066cc")

    def _select_excel_file(self):
        is_multiple = (getattr(self, 'var_import_mode', None) and self.var_import_mode.get() == "append")

        if is_multiple:
            file_paths = filedialog.askopenfilenames(
                title="Select Excel or CSV File(s) to Append",
                filetypes=[("Data Files", "*.xlsx *.xls *.csv"), ("Excel Files", "*.xlsx *.xls"), ("CSV Files", "*.csv"), ("All Files", "*.*")]
            )
            if file_paths:
                for fp in file_paths:
                    self._load_excel_file(fp, append=True)
        else:
            file_path = filedialog.askopenfilename(
                title="Select Excel or CSV File",
                filetypes=[("Data Files", "*.xlsx *.xls *.csv"), ("Excel Files", "*.xlsx *.xls"), ("CSV Files", "*.csv"), ("All Files", "*.*")]
            )
            if file_path:
                self._load_excel_file(file_path, append=False)

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
            records, err = ExcelHandler.load_student_list(file_path)
            if err:
                self.logger.error(err)
                messagebox.showerror("Load Error", err)
                return

            self.student_records = records
            self._refresh_treeview_from_records()

            count = len(self.student_ids)
            self.initial_total_count = count
            self._update_progress_from_records()
            self.lbl_file_path.config(text=os.path.basename(file_path))
            self.lbl_found_count.config(text=f"{count} SAVED STUDENTS LOADED", foreground="#0066cc")
            self.logger.log(f"Loaded saved student list: {file_path} ({count} students)")

    def _remove_selected_student(self):
        """Removes all currently selected student IDs from the listbox and queue."""
        selected_items = self.student_tree.selection()
        if not selected_items:
            messagebox.showinfo("Select Student", "Please select one or more students from the list to remove.")
            return

        removed_ids = []
        for item_id in selected_items:
            self.student_tree.delete(item_id)
            removed_ids.append(item_id)

        rem_set = set(removed_ids)

        # Store removed records into processed_history stack for Undo / Restore
        for sid in removed_ids:
            matching_rec = next((r for r in self.student_records if r['id'] == sid), {'id': sid})
            self.processed_history.append(matching_rec)

        # Update student_records and student_ids
        self.student_records = [r for r in self.student_records if r['id'] not in rem_set]
        self.student_ids = [sid for sid in self.student_ids if sid not in rem_set]

        # Update remaining count label
        count = len(self.student_ids)
        self.lbl_found_count.config(text=f"{count} PHOTOGRAPHED STUDENTS REMAINING", foreground="#0066cc")
        self.logger.log(f"Removed {len(removed_ids)} student ID(s) from list: {', '.join(removed_ids)}")

    def _show_tree_context_menu(self, event):
        """Displays right-click context menu over student Treeview."""
        item_id = self.student_tree.identify_row(event.y)
        if item_id:
            if item_id not in self.student_tree.selection():
                self.student_tree.selection_set(item_id)
        if hasattr(self, 'tree_context_menu'):
            try:
                self.tree_context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.tree_context_menu.grab_release()

    def _clear_entire_student_list(self):
        """Clears all student records and resets list GUI state after user confirmation."""
        if not self.student_records:
            return

        if messagebox.askyesno("Clear Entire List", f"Are you sure you want to clear all {len(self.student_records)} student(s) from the list?"):
            # Store all cleared records into history
            self.processed_history.extend(self.student_records)
            self.student_records = []
            self.student_ids = []
            self._refresh_treeview_from_records()
            self.lbl_file_path.config(text="No file selected")
            self.lbl_found_count.config(text="0 PHOTOGRAPHED STUDENTS FOUND", foreground="#0066cc")
            self.initial_total_count = 0
            self._update_progress_from_records()
            self.logger.log("Cleared entire student list.")

    def _on_student_double_click(self, event=None):
        """Copies the double-clicked student ID directly into the system clipboard / paste buffer."""
        if event:
            item_id = self.student_tree.identify_row(event.y)
        else:
            item_id = None
        if not item_id:
            selected = self.student_tree.selection()
            if selected:
                item_id = selected[0]
        if item_id:
            pyperclip.copy(item_id)
            self.logger.log(f"Copied Student ID '{item_id}' to clipboard.")
            self.lbl_status.config(text=f"Status: Copied Student ID '{item_id}' to clipboard")

    def _copy_selected_students(self, event=None):
        """Copies all selected Treeview rows (ID, First Name, Last Name, Grade) to the
        clipboard as tab-separated lines, one per selected row, so pasting into a
        spreadsheet reproduces the full highlighted line(s)."""
        selected = self.student_tree.selection()
        if not selected:
            return
        lines = ["\t".join(str(v) for v in self.student_tree.item(iid, 'values')) for iid in selected]
        pyperclip.copy("\n".join(lines))
        if len(selected) == 1:
            self.logger.log(f"Copied line for Student ID '{selected[0]}' to clipboard.")
            self.lbl_status.config(text=f"Status: Copied line for Student ID '{selected[0]}' to clipboard")
        else:
            self.logger.log(f"Copied {len(selected)} student lines to clipboard.")
            self.lbl_status.config(text=f"Status: Copied {len(selected)} student lines to clipboard")

    def _remove_prior_students(self):
        """Removes all students preceding (or up to) the currently selected student in the list."""
        selected = self.student_tree.selection()
        if not selected:
            messagebox.showinfo("Select Student", "Please select a student in the list first (e.g. the last successfully printed student ID).")
            return

        target_id = selected[0]
        if target_id not in self.student_ids:
            return

        idx = self.student_ids.index(target_id)
        if idx == 0:
            if messagebox.askyesno("Remove Student", f"Student '{target_id}' is already at the top of the list.\nDo you want to remove this student?"):
                self._remove_selected_student()
            return

        msg = (
            f"Selected Student ID: {target_id} (Item #{idx + 1} of {len(self.student_ids)})\n\n"
            f"Would you like to remove all {idx + 1} students up to and including '{target_id}'?\n\n"
            f"• Click YES to remove all students up to '{target_id}' (the next student will become #1).\n"
            f"• Click NO to remove only the {idx} students BEFORE '{target_id}' (so '{target_id}' becomes #1)."
        )
        choice = messagebox.askyesnocancel("Remove Prior Students", msg)
        if choice is None:
            return

        remove_count = idx + 1 if choice else idx
        removed_ids = self.student_ids[:remove_count]

        # Store removed records into processed_history stack for Undo / Restore
        for sid in removed_ids:
            matching_rec = next((r for r in self.student_records if r['id'] == sid), {'id': sid})
            self.processed_history.append(matching_rec)

        # Update student_tree, student_records, student_ids
        rem_set = set(removed_ids)
        for item_id in removed_ids:
            if self.student_tree.exists(item_id):
                self.student_tree.delete(item_id)

        self.student_records = [r for r in self.student_records if r['id'] not in rem_set]
        self.student_ids = [sid for sid in self.student_ids if sid not in rem_set]

        count = len(self.student_ids)
        self.lbl_found_count.config(text=f"{count} PHOTOGRAPHED STUDENTS REMAINING", foreground="#0066cc")
        self.logger.log(f"Removed {len(removed_ids)} prior student ID(s) up to {target_id}.")

    def _pop_student(self, student_id: str):
        """Removes a processed student from student_records, student_ids, and Treeview UI synchronously in memory."""
        # Find record before popping
        matching_rec = next((r for r in self.student_records if r['id'] == student_id), {'id': student_id})
        self.processed_history.append(matching_rec)

        if self.student_ids and self.student_ids[0] == student_id:
            self.student_ids.pop(0)
        elif student_id in self.student_ids:
            self.student_ids.remove(student_id)
        self.student_records = [r for r in self.student_records if r['id'] != student_id]

        def _do_ui_pop():
            if self.student_tree.exists(student_id):
                self.student_tree.delete(student_id)
            count = len(self.student_ids)
            self.lbl_found_count.config(text=f"{count} PHOTOGRAPHED STUDENTS REMAINING", foreground="#0066cc")
            self._update_progress_from_records()

        self.root.after(0, _do_ui_pop)

    def _restore_previous_students(self):
        """Displays interactive modal dialog with checkboxes, Select All, and Clear All to restore selected students."""
        if not self.processed_history:
            messagebox.showinfo("Undo / Restore Students", "No previously processed students are available in the history stack to restore.")
            return

        # Unique records from history (latest first)
        history_records = list(reversed(self.processed_history))
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Restore Previous Students")
        dialog.geometry("560x540")
        dialog.minsize(450, 380)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(
            dialog, text="Select Previous Students to Restore to Print Queue",
            font=("Arial", 10, "bold"), foreground="#0066cc"
        ).pack(pady=(10, 4))

        # Toolbar row: Select All & Clear All buttons
        tool_bar = ttk.Frame(dialog)
        tool_bar.pack(fill=tk.X, padx=15, pady=4)

        vars_map = {}

        def _select_all():
            for var in vars_map.values():
                var.set(True)

        def _clear_all():
            for var in vars_map.values():
                var.set(False)

        btn_select_all = ttk.Button(tool_bar, text="☑ Select All", command=_select_all)
        btn_select_all.pack(side=tk.LEFT, padx=(0, 4))

        btn_clear_all = ttk.Button(tool_bar, text="☐ Clear All", command=_clear_all)
        btn_clear_all.pack(side=tk.LEFT)

        lbl_avail = ttk.Label(tool_bar, text=f"{len(history_records)} Available", font=("Arial", 8, "italic"), foreground="#6c757d")
        lbl_avail.pack(side=tk.RIGHT)

        # Bottom Action Buttons Row packed FIRST (with side=tk.BOTTOM) so it is always visible even if resized
        action_bar = ttk.Frame(dialog)
        action_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=12)

        restored_result = []

        def _on_confirm():
            selected_ids = [sid for sid, var in vars_map.items() if var.get()]
            if not selected_ids:
                messagebox.showwarning("No Selection", "Please select at least one student checkbox to restore.", parent=dialog)
                return
            restored_result.extend(selected_ids)
            dialog.destroy()

        def _on_cancel():
            dialog.destroy()

        btn_confirm = tk.Button(action_bar, text="RESTORE SELECTED", bg="#28a745", fg="white", font=("Arial", 9, "bold"), command=_on_confirm)
        btn_confirm.pack(side=tk.RIGHT, padx=4)

        btn_cancel = tk.Button(action_bar, text="Cancel", bg="#6c757d", fg="white", font=("Arial", 9), command=_on_cancel)
        btn_cancel.pack(side=tk.RIGHT, padx=4)

        # Scrollable Frame containing student Checkbuttons (occupies remaining middle space)
        list_container = ttk.Frame(dialog, padding=5)
        list_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=15, pady=5)

        canvas = tk.Canvas(list_container, highlightthickness=1, highlightbackground="#ced4da")
        scroll = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)

        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Populate Checkbuttons for each student record in history
        for rec in history_records:
            sid = rec['id']
            fn = rec.get('first_name', '')
            ln = rec.get('last_name', '')
            gr = rec.get('grade', '')

            label_str = f"Student ID: {sid}"
            if fn or ln:
                label_str += f" | {fn} {ln}".strip()
            if gr:
                label_str += f" (Grade {gr})"

            var = tk.BooleanVar(value=True)  # Checked by default
            vars_map[sid] = var

            chk = ttk.Checkbutton(scroll_frame, text=label_str, variable=var)
            chk.pack(anchor=tk.W, pady=2, padx=5)

        dialog.wait_window()

        if not restored_result:
            return

        # Separate chosen records vs remaining unchosen history while preserving exact original chronological order
        chosen_set = set(restored_result)
        restored_records = [r for r in self.processed_history if r['id'] in chosen_set]
        self.processed_history = [r for r in self.processed_history if r['id'] not in chosen_set]

        restored_ids = [r['id'] for r in restored_records]
        # Prepend back to student_ids and student_records in exact original chronological order
        existing_set = set(self.student_ids)
        new_ids = [r['id'] for r in restored_records if r['id'] not in existing_set]

        self.student_ids = new_ids + self.student_ids
        self.student_records = restored_records + [r for r in self.student_records if r['id'] not in set(new_ids)]

        self._refresh_treeview_from_records()
        count = len(self.student_ids)
        self._update_progress_from_records()
        self.lbl_found_count.config(text=f"{count} PHOTOGRAPHED STUDENTS REMAINING", foreground="#0066cc")

        # Build formatted list with Name and Grade details
        restored_details = []
        for r in restored_records:
            sid = r['id']
            fn = r.get('first_name', '')
            ln = r.get('last_name', '')
            gr = r.get('grade', '')

            item_str = f"• ID: {sid}"
            if fn or ln:
                item_str += f" | {fn} {ln}".strip()
            if gr:
                item_str += f" (Grade {gr})"
            restored_details.append(item_str)

        log_msg = f"Restored {len(restored_records)} previous student(s) back to top of list: {', '.join(restored_ids)}"
        self.logger.log(log_msg)

        details_str = "\n".join(restored_details)
        messagebox.showinfo(
            "Students Restored",
            f"Successfully restored {len(restored_records)} student(s) back to the top of the print queue:\n\n{details_str}"
        )

    def _load_excel_file(self, file_path: str, append: bool = False):
        records, err = ExcelHandler.load_photographed_students(file_path)

        if err:
            if not append:
                self.student_records = []
                self.student_ids = []
                self._refresh_treeview_from_records()
                self.lbl_found_count.config(text="0 PHOTOGRAPHED STUDENTS FOUND", foreground="red")
            self.logger.error(err)
            messagebox.showerror("Excel Error", err)
            return

        if append:
            existing_ids = {r['id'] for r in self.student_records}
            added_count = 0
            for r in records:
                if r['id'] not in existing_ids:
                    self.student_records.append(r)
                    existing_ids.add(r['id'])
                    added_count += 1
            self.lbl_file_path.config(text=f"Appended {os.path.basename(file_path)}")
            self.logger.log(f"Appended list: {os.path.basename(file_path)} ({added_count} new students added, total {len(self.student_records)})")
        else:
            self.lbl_file_path.config(text=os.path.basename(file_path))
            self.student_records = records
            self.logger.log(f"Loaded Excel file: {file_path} ({len(records)} students loaded)")

        self._refresh_treeview_from_records()
        count = len(self.student_ids)
        self.initial_total_count = count
        self._update_progress_from_records()
        self.lbl_found_count.config(text=f"{count} PHOTOGRAPHED STUDENTS FOUND", foreground="#0066cc")
        
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
            ent_x, ent_y = self.ent_search_x, self.ent_search_y
        elif target_name == "Card Type":
            ent_x, ent_y = self.ent_card_type_x, self.ent_card_type_y
        else:
            ent_x, ent_y = self.ent_print_x, self.ent_print_y

        ent_x.delete(0, tk.END)
        ent_x.insert(0, str(x))
        ent_y.delete(0, tk.END)
        ent_y.insert(0, str(y))

        self.lbl_status.config(text=f"Status: Captured {target_name} at ({x}, {y})")
        self.logger.log(f"Captured {target_name} Location: X={x}, Y={y}")
        self._save_ui_to_config()

    def _test_current_student(self):
        if not self._save_ui_to_config():
            return

        sel = self.student_tree.selection()
        if sel:
            student_id = sel[0]
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

        if self.is_processing:
            if self.automation_thread and not self.automation_thread.is_alive():
                # Previous thread finished or exited cleanly, reset state flag
                self.is_processing = False
            else:
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
            pause_limit = getattr(self.config, 'pause_after_cards', 0)
            if pause_limit > 0:
                self._update_pause_countdown(pause_limit)

    def _stop_automation(self):
        if not self.is_processing:
            return

        self.automation.stop_event.set()
        self.automation.pause_event.set()
        self.logger.log("STOP requested by user.")
        self.lbl_status.config(text="Status: Stopping...")

    def _trigger_auto_pause(self, limit: int):
        """Updates GUI pause button and status on main thread when card batch limit is reached."""
        if self.automation.pause_event.is_set():
            self.automation.pause_event.clear()
            self.btn_pause.config(text="RESUME", bg="#17a2b8")
            self.lbl_status.config(text=f"Status: AUTO-PAUSED (Processed batch of {limit} cards)", foreground="#003366")
            self._update_pause_countdown(0)

    def _run_automation_loop(self):
        total = len(self.student_ids)
        printed = 0
        skipped = 0
        errors = 0
        batch_counter = 0
        start_time = time.time()
        self.automation.reset_job_durations()

        while self.student_ids:
            if self.automation.stop_event.is_set():
                break

            sid = self.student_ids[0]
            start_total = max(1, getattr(self, 'initial_total_count', len(self.student_ids)))
            completed_so_far = max(0, start_total - len(self.student_ids))
            pause_limit = getattr(self.config, 'pause_after_cards', 0)

            if pause_limit > 0:
                rem_pause = max(0, pause_limit - batch_counter)
                self.root.after(0, lambda r=rem_pause: self._update_pause_countdown(r))

            # Compute dynamic ETA based on average job completion duration
            min_t, max_t, avg_t = self.automation.get_job_timing_stats()
            remaining_cards = len(self.student_ids)

            if avg_t > 0:
                est_remaining_sec = int(avg_t * remaining_cards)
                hours = est_remaining_sec // 3600
                minutes = (est_remaining_sec % 3600) // 60
                seconds = est_remaining_sec % 60

                if hours > 0:
                    eta_str = f"Estimated Time Remaining: {hours}h {minutes}m {seconds}s (Avg {avg_t:.1f}s/card)"
                elif minutes > 0:
                    eta_str = f"Estimated Time Remaining: {minutes}m {seconds}s (Avg {avg_t:.1f}s/card)"
                else:
                    eta_str = f"Estimated Time Remaining: {seconds}s (Avg {avg_t:.1f}s/card)"
            elif completed_so_far > 0:
                elapsed_sec = time.time() - start_time
                avg_sec = elapsed_sec / completed_so_far
                est_remaining_sec = int(avg_sec * remaining_cards)
                minutes = est_remaining_sec // 60
                seconds = est_remaining_sec % 60
                eta_str = f"Estimated Time Remaining: {minutes}m {seconds}s"
            else:
                eta_str = f"Estimated Time Remaining: Calibrating..."

            min_t, max_t, avg_t = self.automation.get_job_timing_stats()
            self._update_progress_ui(sid, eta_str, min_t, max_t, avg_t)
            self.logger.log(f"Processing student {sid} ({completed_so_far + 1}/{start_total})")

            success, msg = self.automation.process_single_student(sid)

            if success:
                printed += 1
                batch_counter += 1
                self._pop_student(sid)

                # Update live timing stats after job completion
                new_min, new_max, new_avg = self.automation.get_job_timing_stats()
                last_duration = self.automation.job_durations[-1] if self.automation.job_durations else 0.0
                self.logger.log(f"Completed student {sid} in {last_duration:.1f}s | Stats: Min {new_min:.1f}s, Max {new_max:.1f}s, Avg {new_avg:.1f}s")
                self._update_progress_ui(sid, eta_str, new_min, new_max, new_avg)

                # Check auto-pause condition
                if pause_limit > 0:
                    rem_pause = max(0, pause_limit - batch_counter)
                    self.root.after(0, lambda r=rem_pause: self._update_pause_countdown(r))

                    if batch_counter >= pause_limit and self.student_ids:
                        batch_counter = 0
                        self.logger.log(f"AUTO-PAUSED: Batch limit of {pause_limit} cards reached. Click RESUME to continue.")
                        self.root.after(0, lambda _l=pause_limit: self._trigger_auto_pause(_l))
                        if not self.automation.wait_if_paused_or_stopped():
                            break
                        self.root.after(0, lambda _l=pause_limit: self._update_pause_countdown(_l))
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
                        self._pop_student(sid)
                    else:
                        errors += 1
                        self._pop_student(sid)
                elif user_choice == "skip":
                    self.logger.log(f"User chose SKIP for student {sid}")
                    skipped += 1
                    self._pop_student(sid)
                else:  # stop
                    self.logger.log(f"User chose STOP on student {sid}")
                    self.automation.stop_event.set()
                    break

        elapsed = time.strftime("%H:%M:%S", time.gmtime(time.time() - start_time))
        
        self.root.after(0, lambda: self._show_summary(total, printed, skipped, errors, elapsed))
        self.is_processing = False

    def _update_progress_from_records(self):
        """Updates overall session progress label and progress bar based on initial total vs remaining students."""
        total = max(0, getattr(self, 'initial_total_count', 0))
        remaining = len(self.student_ids) if hasattr(self, 'student_ids') else 0

        if total < remaining:
            total = remaining
            self.initial_total_count = total

        completed = max(0, total - remaining)
        pct = (completed / total) * 100.0 if total > 0 else 0.0

        if hasattr(self, 'lbl_prog_stats'):
            self.lbl_prog_stats.config(text=f"Progress: {completed} / {total} ({pct:.1f}%)")
        if hasattr(self, 'progress_bar'):
            self.progress_bar['value'] = pct

    def _update_progress_ui(self, student_id: str, eta_str: str = "", min_t: float = 0.0, max_t: float = 0.0, avg_t: float = 0.0):
        def _upd():
            self.lbl_curr_student.config(text=f"Current Student: {student_id}")
            self._update_progress_from_records()
            self.lbl_status.config(text=f"Status: Processing {student_id}...")
            if eta_str:
                self.lbl_eta.config(text=eta_str)
            if hasattr(self, 'lbl_timing_stats'):
                if min_t > 0 or max_t > 0 or avg_t > 0:
                    timing_txt = f"⏱️ Job Timing: Min: {min_t:.1f}s | Max: {max_t:.1f}s | Avg: {avg_t:.1f}s"
                else:
                    timing_txt = "⏱️ Job Timing: Min: -- | Max: -- | Avg: --"
                self.lbl_timing_stats.config(text=timing_txt)
                if hasattr(self, 'lbl_queue_timing'):
                    self.lbl_queue_timing.config(text=timing_txt)
        self.root.after(0, _upd)

    def _prompt_timeout_dialog(self, student_id: str, error_msg: str) -> str:
        res_var = tk.StringVar(value="stop")

        def _ask():
            dialog = tk.Toplevel(self.root)
            dialog.title("Automation Timeout / Application Error")
            dialog.geometry("540x280")
            dialog.minsize(460, 240)
            dialog.grab_set()

            # Dock Bottom Action Buttons Row FIRST (side=tk.BOTTOM) so buttons are guaranteed visible
            btn_box = ttk.Frame(dialog)
            btn_box.pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=15)

            def _choose(val):
                res_var.set(val)
                dialog.destroy()

            btn_stop = tk.Button(btn_box, text="STOP", bg="#dc3545", fg="white", font=("Arial", 10, "bold"), width=10, command=lambda: _choose("stop"))
            btn_stop.pack(side=tk.RIGHT, padx=5)

            btn_skip = tk.Button(btn_box, text="SKIP", bg="#ffc107", fg="black", font=("Arial", 10, "bold"), width=10, command=lambda: _choose("skip"))
            btn_skip.pack(side=tk.RIGHT, padx=5)

            btn_retry = tk.Button(btn_box, text="RETRY", bg="#28a745", fg="white", font=("Arial", 10, "bold"), width=10, command=lambda: _choose("retry"))
            btn_retry.pack(side=tk.RIGHT, padx=5)

            # Top Content Header & Details
            top_frame = ttk.Frame(dialog, padding=15)
            top_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

            ttk.Label(top_frame, text="⚠️ Application / Search Warning", font=("Arial", 11, "bold"), foreground="#dc3545").pack(anchor=tk.W, pady=(0, 6))
            ttk.Label(top_frame, text=f"Student ID: {student_id}", font=("Arial", 10, "bold"), foreground="#0066cc").pack(anchor=tk.W, pady=(0, 6))

            msg_label = ttk.Label(top_frame, text=error_msg, font=("Arial", 10), wraplength=490, justify=tk.LEFT)
            msg_label.pack(anchor=tk.W, fill=tk.BOTH, expand=True)

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

    def _show_help_guide(self):
        """Displays interactive User Guide dialog explaining all options and buttons."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Student Photo Print Automator - User Guide & Reference")
        dialog.geometry("780x600")
        dialog.minsize(600, 450)
        dialog.transient(self.root)

        # Header Title Bar
        header = ttk.Frame(dialog, padding=(15, 12, 15, 8))
        header.pack(fill=tk.X)
        ttk.Label(header, text="STUDENT PHOTO PRINT AUTOMATOR - USER GUIDE", font=("Arial", 12, "bold"), foreground="#0066cc").pack(anchor=tk.W)
        ttk.Label(header, text="Comprehensive operational instructions, timing options, and queue controls", font=("Arial", 9, "italic"), foreground="#6c757d").pack(anchor=tk.W, pady=(2, 0))

        # Main content container with outer padding margins
        content_frame = ttk.Frame(dialog, padding=(15, 5, 15, 15))
        content_frame.pack(fill=tk.BOTH, expand=True)

        txt_box = tk.Text(content_frame, font=("Segoe UI", 10), wrap=tk.WORD, bg="#ffffff", fg="#212529", relief=tk.SOLID, borderwidth=1, padx=15, pady=12)
        scroll = ttk.Scrollbar(content_frame, orient=tk.VERTICAL, command=txt_box.yview)
        txt_box.config(yscrollcommand=scroll.set)

        # Configure styled text tags for headings and bold labels
        txt_box.tag_config("h1", font=("Segoe UI", 11, "bold"), foreground="#0066cc", spacing1=12, spacing3=4)
        txt_box.tag_config("bullet", lmargin1=15, lmargin2=30, spacing1=3, spacing3=3)
        txt_box.tag_config("bold", font=("Segoe UI", 10, "bold"))

        sections = [
            ("1. IMPORT MODES & FILE HANDLING", [
                ("Single Mode", "Selects a single file (.xlsx / .csv / .zip sync archive) to load a new student list."),
                ("Multiple Mode", "Allows selecting multiple files to merge/append into your active student list."),
                ("Save Remaining List", "Exports unprinted students to a CSV/XLSX file if you stop early."),
                ("Restore Previous N", "Opens an interactive checkbox dialog to restore deleted or printed cards back to top of queue."),
                ("Right-Click Menu", "Right-click anywhere inside the list to Copy ID, Remove Selected, Delete Prior, or Clear All.")
            ]),
            ("2. AUTOMATION LOCATIONS (SELECT LOCATION)", [
                ("Student Search", "Position mouse over the StudentSearch input box. Click 'Select Location' and wait 3s."),
                ("Print Button", "Position mouse over the target Print Button. Click 'Select Location' and wait 3s."),
                ("Card Type", "Optional. Position mouse over the Card Type selector and click 'Select Location'. Tick 'Required' to have that location clicked for every student, right before Print; leave it unticked to never click it.")
            ]),
            ("3. TIMING & CONFIGURATION OPTIONS", [
                ("Search Start Delay (s)", "Delay (in seconds) after clicking the search box before pasting Student ID."),
                ("Max Search Wait (s)", "Maximum seconds to wait for StudentSearch verification to complete."),
                ("Print Delay (s)", "Delay after clicking Print to allow Windows printer queue to register the job."),
                ("Between Student Delay (s)", "Pause duration before advancing to the next student in sequence."),
                ("Print Hotkey", "Alternative keyboard shortcut (e.g. 'ctrl+p') used if mouse click location is bypassed."),
                ("Pause after every N cards", "Automatically pauses batch execution after processing N cards.")
            ]),
            ("4. PRINT QUEUE MONITORING & THROTTLING", [
                ("Printer Queue Dropdown", "Select your target Windows printer (e.g. 'NullPrinter' or card printer)."),
                ("Thermometer Gauge", "Color-coded real-time visualizer showing active print jobs in queue."),
                ("Sync Batch with Queue", "When checked, batch automation automatically pauses whenever queue depth reaches 'Max Running Jobs' and resumes as soon as jobs clear.")
            ]),
            ("5. SAFETY & EMERGENCY CONTROLS", [
                ("Emergency Stop", "Press ESC key anytime or move mouse cursor to the upper-left screen corner."),
                ("Dry Run", "Simulates card search and verification without clicking the final Print button.")
            ])
        ]

        for sec_title, items in sections:
            txt_box.insert(tk.END, f"{sec_title}\n", "h1")
            for label, desc in items:
                idx_start = txt_box.index(tk.END)
                txt_box.insert(tk.END, f"• {label}: ", "bullet")
                txt_box.tag_add("bold", idx_start, f"{idx_start}+{len(label)+4}c")
                txt_box.insert(tk.END, f"{desc}\n", "bullet")

        txt_box.config(state=tk.DISABLED)

        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        txt_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _show_summary(self, total: int, printed: int, skipped: int, errors: int, elapsed: str):
        self.btn_start.config(state=tk.NORMAL)
        self.btn_pause.config(text="PAUSE", bg="#ffc107")
        self.lbl_status.config(text="Status: Complete")
        self.lbl_curr_student.config(text="Current Student: None")

        min_t, max_t, avg_t = self.automation.get_job_timing_stats()
        timing_summary = f"Job Durations:        Min: {min_t:.1f}s | Max: {max_t:.1f}s | Avg: {avg_t:.1f}s" if min_t > 0 else "Job Durations:        N/A"

        summary_msg = (
            f"Printing Complete\n\n"
            f"Total Students:       {total}\n"
            f"Successfully Printed: {printed}\n"
            f"Skipped:              {skipped}\n"
            f"Errors:               {errors}\n"
            f"{timing_summary}\n\n"
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

    def _refresh_printer_list(self):
        """Populates the printer queue drop-down list from Windows win32print."""
        printers = []
        if win32print:
            try:
                flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                printer_info = win32print.EnumPrinters(flags)
                printers = sorted([p[2] for p in printer_info])
            except Exception as e:
                self.logger.log(f"Error enumerating printers: {e}")

        if not printers:
            printers = ["NullPrinter"]

        self.combo_printers['values'] = printers

        # Default selection: preference order -> config -> NullPrinter -> first printer
        target_printer = self.config.selected_printer or "NullPrinter"
        if target_printer in printers:
            self.combo_printers.set(target_printer)
        elif "NullPrinter" in printers:
            self.combo_printers.set("NullPrinter")
        else:
            self.combo_printers.set(printers[0])

        self._on_printer_selected()

    def _on_printer_selected(self, event=None):
        selected = self.combo_printers.get().strip()
        if selected:
            self.config.selected_printer = selected
            self.config.save()
            self.lbl_queue_printer.config(text=f"Selected: {selected}")
            self._poll_print_queue()

    def _save_queue_sync_settings(self):
        """Saves Queue Sync toggle state and Max Running Jobs threshold to AppConfig."""
        if hasattr(self, 'var_queue_sync'):
            self.config.enable_queue_sync = self.var_queue_sync.get()

        if hasattr(self, 'ent_max_jobs'):
            try:
                val_str = self.ent_max_jobs.get().strip()
                if val_str:
                    self.config.max_queue_jobs = max(1, int(val_str))
            except ValueError:
                pass

        self.config.save()

    # --- Visible mouse movement trail ---------------------------------------
    # A transparent, always-on-top, click-through window spanning the whole virtual
    # desktop. Click-through is essential: automation drives raw screen coordinates,
    # so an overlay that swallowed clicks would break every run.

    TRAIL_BG = "#0a0b0c"      # treated as transparent by Windows
    TRAIL_HOLD_MS = 2500      # how long each drawn segment stays on screen

    def _ensure_trail_overlay(self):
        """Creates the trail overlay on first use and returns its canvas."""
        if self._trail_canvas is not None:
            return self._trail_canvas

        user32 = ctypes.windll.user32
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        self._trail_origin = (vx, vy)

        overlay = tk.Toplevel(self.root)
        overlay.title("Trail Overlay")   # deliberately keyword-free: find_uiautomation_control
                                         # scans window names for 'print' / 'search'
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.geometry(f"{vw}x{vh}+{vx}+{vy}")
        try:
            overlay.attributes("-transparentcolor", self.TRAIL_BG)
        except tk.TclError:
            overlay.attributes("-alpha", 0.45)

        canvas = tk.Canvas(overlay, bg=self.TRAIL_BG, highlightthickness=0, borderwidth=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        overlay.update_idletasks()

        # WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        try:
            hwnd = user32.GetParent(overlay.winfo_id()) or overlay.winfo_id()
            ex_style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, ex_style | 0x00080000 | 0x00000020 | 0x08000000 | 0x00000080)
        except Exception as e:
            self.logger.log(f"Mouse trail overlay could not be made click-through: {e}")

        overlay.withdraw()
        self._trail_overlay = overlay
        self._trail_canvas = canvas
        return canvas

    def _show_mouse_trail(self, x1: int, y1: int, x2: int, y2: int, label: str = ""):
        """Called from the automation thread; hands the draw back to the Tk thread."""
        self.root.after(0, lambda: self._draw_trail_segment(x1, y1, x2, y2, label))

    def _draw_trail_segment(self, x1: int, y1: int, x2: int, y2: int, label: str = ""):
        if not self.var_mouse_trail.get():
            return
        try:
            canvas = self._ensure_trail_overlay()
            ox, oy = self._trail_origin
            ax, ay, bx, by = x1 - ox, y1 - oy, x2 - ox, y2 - oy

            items = [
                canvas.create_line(ax, ay, bx, by, fill="#00e5ff", width=3,
                                   arrow=tk.LAST, arrowshape=(18, 22, 7)),
                canvas.create_oval(ax - 6, ay - 6, ax + 6, ay + 6, outline="#00e5ff", width=2),
                canvas.create_oval(bx - 16, by - 16, bx + 16, by + 16, outline="#ff3b30", width=3),
                canvas.create_line(bx - 24, by, bx + 24, by, fill="#ff3b30", width=1),
                canvas.create_line(bx, by - 24, bx, by + 24, fill="#ff3b30", width=1),
            ]
            if label:
                items.append(canvas.create_text(bx + 24, by - 26, text=f"{label}  ({x2}, {y2})",
                                                anchor=tk.W, fill="#ffd400",
                                                font=("Arial", 11, "bold")))

            self._trail_overlay.deiconify()
            self._trail_overlay.lift()
            self.root.after(self.TRAIL_HOLD_MS, lambda: self._erase_trail_items(items))
        except Exception as e:
            self.logger.log(f"Mouse trail could not be drawn: {e}")

    def _erase_trail_items(self, items):
        canvas = self._trail_canvas
        if canvas is None:
            return
        for item in items:
            try:
                canvas.delete(item)
            except Exception:
                pass
        try:
            if not canvas.find_all() and self._trail_overlay is not None:
                self._trail_overlay.withdraw()
        except Exception:
            pass

    def _get_current_queue_job_count(self) -> int:
        """Returns active printer queue job count synchronously for AutomationController gating."""
        if not win32print:
            return 0
        printer_name = self.config.selected_printer or "NullPrinter"
        try:
            h_printer = win32print.OpenPrinter(printer_name)
            try:
                p_info = win32print.GetPrinter(h_printer, 2)
                return p_info.get('cJobs', 0)
            finally:
                win32print.ClosePrinter(h_printer)
        except Exception:
            return 0

    def _poll_print_queue(self):
        """Polls the active printer queue job count and status using win32print."""
        printer_name = self.combo_printers.get().strip()
        if not printer_name or not win32print:
            self.lbl_queue_jobs.config(text="Active Queue Jobs: N/A", foreground="gray")
            self.lbl_queue_status.config(text="Printer Status: win32print unavailable")
            self.thermometer.set_value(0)
            return

        def _worker():
            job_count = 0
            status_str = "Ready / Idle"
            try:
                h_printer = win32print.OpenPrinter(printer_name)
                try:
                    p_info = win32print.GetPrinter(h_printer, 2)
                    job_count = p_info.get('cJobs', 0)
                    status_flag = p_info.get('Status', 0)

                    status_parts = []
                    if status_flag & 0x00000001: status_parts.append("Paused")
                    if status_flag & 0x00000002: status_parts.append("Error")
                    if status_flag & 0x00000004: status_parts.append("Pending Deletion")
                    if status_flag & 0x00000008: status_parts.append("Paper Jam")
                    if status_flag & 0x00000010: status_parts.append("Out of Paper")
                    if status_flag & 0x00000020: status_parts.append("Manual Feed")
                    if status_flag & 0x00000400: status_parts.append("Printing")
                    if status_flag & 0x00000200: status_parts.append("Offline")

                    if status_parts:
                        status_str = ", ".join(status_parts)
                    elif job_count > 0:
                        status_str = f"Active ({job_count} jobs pending)"
                    else:
                        status_str = "Ready / Idle"
                finally:
                    win32print.ClosePrinter(h_printer)
            except Exception as ex:
                status_str = f"Unable to query ({ex})"

            def _update_ui():
                self.lbl_queue_jobs.config(text=f"Active Queue Jobs: {job_count}")
                self.lbl_queue_status.config(text=f"Status: {status_str}")
                self.thermometer.set_value(job_count)

            self.root.after(0, _update_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _start_queue_polling_loop(self):
        """Starts regular periodic polling for print queue monitoring."""
        if hasattr(self, 'var_auto_poll_queue') and self.var_auto_poll_queue.get():
            self._poll_print_queue()
        self.root.after(1000, self._start_queue_polling_loop)
