# Student Photo Print Automator

A Windows desktop application that prints student ID cards in bulk through **Schoolhouse Smiles**. It loads a roster of photographed students, then for each student it searches Schoolhouse Smiles, confirms the right record loaded, selects the card type and clicks Print, repeating until the batch is done.

## Features

- **DOM Control (recommended)**: Drives Schoolhouse Smiles through its page, finding Student Search, Card Type and Print by name rather than by screen position. Each student record is confirmed loaded (the `Student ID` field must match) before Print is clicked, and students that Schoolhouse Smiles cannot find are skipped and listed at the end of the run.
- **Screen-Location Fallback**: If DOM control is off or unavailable, clicks configured X/Y locations picked with a 3-second countdown, and verifies the search box contents before searching.
- **Roster Import**: Reads `.xlsx`, `.xls` and `.csv` files (case-insensitive `studentId`, `firstName`, `lastName`, `grade`, `status` columns, keeping rows where `status` is `PHOTOGRAPHED`), or sync-archive `.zip` files (students with a photo). Leading zeros in IDs are preserved. **Export Template** writes a blank file with the expected columns.
- **Queue Management**: Search, sort, remove, restore and save/reload the remaining list if you stop early.
- **Print Queue Throttling**: Monitors the selected Windows printer queue and can pause the batch while it is full.
- **Dry Run Mode**: Runs every step for real except the final Print click.
- **Emergency Stops**: Press **ESC**, or move the mouse to the upper-left corner of the screen `(0, 0)`, to stop instantly.
- **Settings & Logs**: Settings are saved to `%APPDATA%\StudentPhotoPrintAutomator\config.json`; timestamped logs are shown live and written to `%LOCALAPPDATA%\StudentPhotoPrintAutomator\logs\`.

---

## Installation

**For end users**: run `StudentPhotoPrintAutomator_Setup_v<version>.exe`. It installs the app and a Start-menu **User Guide & Reference**.

**From source** (Python **3.11+** on Windows):

```bash
pip install -r requirements.txt
python main.py
```

---

## Step-by-Step Operating Guide

The full reference for every button and option is in [`User_Guide.txt`](User_Guide.txt), also available in the app via **❓ Help & Guide**.

### 1. Start Schoolhouse Smiles in DOM mode
1. Close Schoolhouse Smiles if it is already open.
2. In **Automation Locations**, leave **Use DOM Control** ticked and click **Launch in DOM Mode**. The first time, you may be asked to locate `schoolhouse-smiles.exe`.
3. The status line should read **DOM: connected to Schoolhouse Smiles**.

### 2. Load the student list
1. Click **Import Excel/CSV** or **Import Sync File(s)**. Choose **Multiple** mode to merge several files.
2. The count of photographed students appears above the list.

### 3. Choose the Card Type (optional)
Open any student in Schoolhouse Smiles, click the 🔄 button next to **Card Type Name**, pick the card, and tick **Required** to have it selected for every student.

### 4. Screen locations (fallback only)
Only needed without DOM control: click **Select Location** next to **Student Search**, **Print Button** and optionally **Card Type**, then hold the mouse over that control in Schoolhouse Smiles during the 3-second countdown.

### 5. Timing options
- **Search Start Delay**: Pause after clicking the search box before entering the ID.
- **Max Search Wait**: How long to wait for the student record to load before the student fails.
- **Print Delay**: Wait after clicking Print so the job reaches the Windows queue.
- **Between Student Delay**: Pause before starting the next student.
- **Load Default Values**: Fills in recommended defaults for card printers.

### 6. Test
- **Test Current Student**: Searches for the highlighted student and confirms the record loads, without printing.
- **Test Print**: Clicks Print once for the student currently open. This prints a real card.
- **Dry Run**: Tick it to run a whole batch without clicking Print. Searching and Card Type selection still happen for real.

### 7. Print the batch
1. Click **START** and confirm the number of students.
2. Watch progress, the ETA and the log. Use **PAUSE** or **STOP** as needed. If a student fails you are offered **RETRY**, **SKIP** or **STOP**.
3. For an emergency, press **ESC** or move the mouse to the **upper-left corner** of the screen.
4. Keep this window from covering Schoolhouse Smiles, since screen-location clicks land on whatever window is on top.

---

## Building the EXE and Installer

Run from the repository root:

```bash
# Standalone one-file EXE -> dist\StudentPhotoPrintAutomator.exe
build_exe.bat

# Inno Setup installer (needs Inno Setup 6 or 7)
# -> installer_setup\Output\StudentPhotoPrintAutomator_Setup_v<version>.exe
build_installer.bat

# Both in one step
build_all.cmd
```

PyInstaller is invoked as `python -m PyInstaller` using `StudentPhotoPrintAutomator.spec`, so it works even when the `pyinstaller` command is not on your PATH. Download Inno Setup from <https://jrsoftware.org/isdl.php>.

To release a new version, update `APP_VERSION` in `version.py` **and** `MyAppVersion` in `installer_setup/setup_builder.iss`.
