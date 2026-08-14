# Student Photo Printing Automation App

A Windows desktop application in Python for automated student photo printing based on data from an Excel spreadsheet.

## Features

- **Excel Parsing & String Preservation**: Reads `.xlsx` and `.xls` files, matches `studentId` and `status` columns case-insensitively, filters `status = PHOTOGRAPHED` (case-insensitive, trimmed), and preserves leading zeros (e.g., `001234`).
- **Coordinate Pickers**: Interactive 3-second countdown to select mouse coordinates for **Student Search** and **Print** buttons.
- **Safety Verification**: Verifies `StudentSearch` input via UIAutomation or clipboard copy verification before clicking Print.
- **Dry Run Mode**: Test full workflow without actually triggering print clicks.
- **Thread-safe Controls**: Fully responsive Tkinter GUI during automation with non-blocking **START**, **PAUSE**, and **STOP** controls.
- **Emergency Corner Stop**: Move the mouse to the upper-left corner of the screen `(0, 0)` at any time to instantly stop execution.
- **Configuration Persistence**: Automatically saves X/Y coordinates, timing values, and dry run options to `%APPDATA%/StudentPhotoPrintAutomator/config.json`.
- **Log Management**: Displays live timestamped logs in GUI and writes logs to `%LOCALAPPDATA%/StudentPhotoPrintAutomator/logs/`.

---

## Installation Instructions

1. Ensure Python **3.11+** is installed on your Windows system.
2. Clone or extract this repository into a folder.
3. Open PowerShell or Command Prompt in the application directory and install required packages:

```bash
pip install -r requirements.txt
```

---

## How to Run the Application

Run the python script directly:

```bash
python main.py
```

---

## Step-by-Step Operating Guide

### 1. Select Photographed List
1. Click **Photographed List**.
2. Choose your `.xlsx` or `.xls` spreadsheet containing `studentId` and `status` columns.
3. The app will filter all rows where `status` is `PHOTOGRAPHED` and display the ID list and count.

### 2. Configure Locations
1. Click **Select Location** under **Student Search**.
2. You will have a 3-second countdown. Position your mouse cursor directly over the Student Search textbox in your target app.
3. Repeat the step for the **Print Button** location.

### 3. Configure Timing Options
- **Search Start Delay**: Pause after clicking the search box before pasting ID (Default: `0.5s`).
- **Maximum Search Wait**: Max wait time for search verification (Default: `15.0s`).
- **Print Delay**: Wait time after clicking print to allow physical spooling/duplex rendering (Default: `4.0s`).
- **Between Student Delay**: Pause before starting next student (Default: `1.5s`).
- **Load Default Values**: Click to reset/fill timing fields with recommended defaults optimized for card printers.

### 4. Using Dry Run Mode
Check the **Dry Run** box to execute search box selection, clearing, pasting, and student verification without clicking the Print button.

### 5. Test Functions
- **Test Current Student**: Tests pasting and verifying the currently selected student ID in the listbox without clicking Print.
- **Test Print**: Prompts for confirmation and clicks the configured Print button coordinates once.

### 6. Start Printing Batch
1. Click **START**.
2. Confirm the prompt displaying the number of students to process.
3. Monitor progress and live logs. Use **PAUSE** or **STOP** as needed.
4. If an emergency occurs, move your mouse to the **upper-left corner** of the screen.

---

## Standalone Executable (.exe) Creation with PyInstaller

To package the application into a single executable for distribution:

1. Install PyInstaller (included in `requirements.txt`):
   ```bash
   pip install pyinstaller
   ```

2. Build the single-file executable:
   ```bash
   pyinstaller --noconfirm --onedir --windowed --hidden-import=numpy --collect-all=pandas --collect-all=openpyxl --name "StudentPhotoPrintAutomator" main.py
   ```

3. The generated standalone folder will be available inside `dist/StudentPhotoPrintAutomator/StudentPhotoPrintAutomator.exe`.

