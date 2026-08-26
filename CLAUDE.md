# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Windows desktop Tkinter application (Python 3.11+) that automates printing student ID cards through a third-party GUI application ("schoolhouse-smiles", an Electron card-printer app) by driving the mouse/keyboard: it loads a roster of photographed students from Excel/CSV/sync-zip, then for each student ID clicks the target app's search box, pastes the ID, presses Enter, optionally verifies, and triggers Print — repeating until the batch is done.

There is no test suite, linter, or CI config in this repo, and no build system beyond PyInstaller/Inno Setup packaging.

## Commands

Run from the repo root (Windows).

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py

# Build the standalone one-file EXE -> dist\StudentPhotoPrintAutomator.exe
build_exe.bat
# or, from a shell without .bat support:
pyinstaller --clean StudentPhotoPrintAutomator.spec

# Build the Inno Setup installer (the script probes for Inno Setup 7 then 6,
# in both Program Files locations, then PATH)
# -> installer_setup\Output\StudentPhotoPrintAutomator_Setup_v<version>.exe
build_installer.bat

# Build EXE + installer in one step
build_all.cmd

# Regenerate a sample test workbook (test_students.xlsx)
python generate_test_excel.py
```

There are no automated tests. The `test_*.xlsx` / `test_*.csv` / `test_*.zip` files in the repo root are hand-made fixtures for ad hoc manual testing of `ExcelHandler`, not a pytest suite.

A release means editing the version in exactly two places: `APP_VERSION` in `version.py` (header banner, window title, splash, AppUserModelID) and `MyAppVersion` in `installer_setup/setup_builder.iss` (installer metadata, and the installer's filename via `OutputBaseFilename`). The Inno Setup preprocessor cannot import Python, which is why the two are not one. `dist/` and `build/` are gitignored, but installers under `installer_setup/Output/` **are** tracked in git, so a rebuild shows up as a large binary diff.

## Architecture

Six top-level modules wired together by `main.py`:

- **`main.py`** — entry point. Sets Windows per-monitor DPI awareness and an explicit AppUserModelID (so the taskbar shows the custom icon), shows a 5-second splash `Toplevel`, then constructs `gui.AppGUI` on a withdrawn Tk root and runs the mainloop. Asset paths resolve through `sys._MEIPASS` when frozen by PyInstaller — keep that pattern for any new bundled asset (and add it to `datas` in the `.spec`).
- **`gui.py`** (`AppGUI`, ~1900 lines) — the entire UI plus the orchestration layer. One large class whose `_build_ui()` composes numbered sections (student list, automation locations, timing config, test buttons, print-queue monitor, controls, progress, log window) inside a scrollable canvas. Owns the Treeview roster, coordinate pickers, config load/save, the batch loop `_run_automation_loop` (run on a background thread), and direct `win32print` polling of the live printer queue rendered in the custom `ThermometerGauge` canvas widget.
- **`automation.py`** (`AutomationController`) — the input-automation engine (pyautogui + pyperclip + pynput). Owns `stop_event`/`pause_event`, the emergency stops, per-job duration stats (`job_durations`, used for the GUI's ETA), and the `get_queue_job_count` callback the GUI injects.
- **`excel_handler.py`** (`ExcelHandler`, classmethods only, keeps the loaded frame in class state `_current_df`) — loads rosters from `.xlsx`/`.xls`/`.csv` (case-insensitive matching of `studentId`/`firstName`/`lastName`/`grade`/`status`, filtering `status == PHOTOGRAPHED`) or from a "sync zip" (`index.json` + photos; a student is included only if a photo is associated with them, checked both via a top-level `photos` array and per-student photo fields). Also exports the remaining/un-printed students back to CSV/Excel, preserving original columns where possible.
- **`config.py`** (`AppConfig`, a dataclass) — all persisted settings (coordinates, timing delays, verification/queue-sync toggles, selected printer, last file path), serialized to `%APPDATA%/StudentPhotoPrintAutomator/config.json`.
- **`version.py`** — a single `APP_VERSION` string, the source of truth for the version shown in the header banner, the window title and the splash screen, and used to build the AppUserModelID. `installer_setup/setup_builder.iss` keeps its own `MyAppVersion` (Inno Setup's preprocessor cannot import Python), so a release means editing both.
- **`logger.py`** (`AppLogger`) — timestamped lines to `%LOCALAPPDATA%/StudentPhotoPrintAutomator/logs/print_log_<timestamp>.log`, forwarded to a GUI callback for the live log panel.

### Student data model

Three parallel structures in `AppGUI` must stay in sync — touching one without the others is the most common source of bugs:

- `student_records: List[dict]` — full records (`id`, `first_name`, `last_name`, `grade`, `meta_str`); backs the Treeview and sorting/filtering.
- `student_ids: List[str]` — the work queue. `_run_automation_loop` always processes `student_ids[0]` and calls `_pop_student(sid)` on success, so the queue shrinks destructively as the batch runs; `initial_total_count` is what progress is measured against.
- `processed_history: List[dict]` — an undo stack. Every removal (printed, manually removed, "remove prior students", list clear) pushes the record here so `_restore_previous_students` can put it back.

### Per-student automation flow (`_execute_single_student`)

Queue-sync gate (block while the printer's `cJobs` >= `max_queue_jobs`) → click search box → `Ctrl+A`/Backspace → clipboard copy + `Ctrl+V` (falling back to `pyautogui.write` if the clipboard round-trip shows nothing) → Enter → optional verification → Print. The Print trigger has a three-way fallback: a UIAutomation-located element, else the configured fixed coordinates, else `config.print_hotkey`. Card Type is handled by `click_card_type()` immediately before the Print step: it clicks the configured location for **every** student when the GUI's "Required" checkbox (`config.card_type_required`) is ticked, and is a complete no-op when it is not (there is no once-per-batch click).

### Key behaviors to preserve when editing

- **Two independent emergency stops** must both keep working: moving the mouse to screen corner `(0,0)` (polled in `check_emergency_stop`, plus pyautogui's own `FAILSAFE`) and the global ESC listener (`pynput`). Both set `stop_event` and `emergency_stop_triggered`. All waits go through `safe_sleep`/`wait_if_paused_or_stopped` so a stop is honored within ~50ms — never use a bare `time.sleep` for a user-configured delay.
- **Dry run suppresses only the Print action.** Every other step (clicking, clearing, pasting, Enter, Card Type selection) still executes for real against the live target app.
- **Coordinate-based automation is fragile by nature** — most click targets try `find_uiautomation_control` first and override the configured fixed coordinates when a match is found. Keep both paths working. `uiautomation`/`pywin32` are Windows-only and imported defensively (`HAS_UIAUTOMATION`, and `win32print` is likewise guarded in `gui.py`).
- **The mouse-trail overlay must stay click-through.** "Enable Visible Mouse Movement Trail" draws each pending click (arrow, target ring, label) on a transparent always-on-top `Toplevel` spanning the virtual desktop, created lazily in `_ensure_trail_overlay`. Because automation clicks raw screen coordinates, that overlay is given `WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` so input passes through to the target app; drop those styles and every run clicks the overlay instead. Its window title is deliberately keyword-free, since `find_uiautomation_control` matches window/control names against words like "print" and "search".
- **Student IDs are always strings** to preserve leading zeros; loaders force `dtype=str` on the ID column and strip the trailing `.0` pandas sometimes appends.
- **GUI thread safety**: the automation loop and the queue poller run on background threads; every UI update from them must be marshaled back with `self.root.after(0, ...)`, matching the existing pattern in `_poll_print_queue`/`_run_automation_loop`/`_update_progress_ui`.
- **Config round-trips** through `AppConfig.load()`/`.save()` — a new persisted setting must be a dataclass field with a default so older `config.json` files still load through the `k in cls.__dataclass_fields__` filter.
- `verify_target_app_active()` (the pre-flight check that the click target belongs to `schoolhouse-smiles.exe`) is currently a stub that always returns `True`; the real implementation is in git history. Don't "fix" it back on without checking whether that was intentional.
- `gui.py` defines `_select_sync_zip_file` twice (~line 793 and ~line 882); only the second definition is live. Edit the later one.
