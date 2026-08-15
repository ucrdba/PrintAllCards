import sys
import os
import ctypes
import tkinter as tk

def set_dpi_awareness():
    """Sets high DPI awareness and process AppUserModelID on Windows for custom taskbar icons."""
    if sys.platform == 'win32':
        try:
            # Register explicit AppUserModelID so Windows Taskbar pins and displays the custom icon
            myappid = 'Schoolhouse.StudentPhotoPrintAutomator.App.2.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-monitor DPI aware
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

def show_splash_screen(root, duration_ms=5000):
    """Displays a modern 5-second splash screen with the application logo before opening main GUI."""
    splash = tk.Toplevel(root)
    splash.overrideredirect(True) # Frameless splash window
    
    # Splash dimensions & centering
    s_width, s_height = 520, 360
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w - s_width) // 2
    y = (screen_h - s_height) // 2
    splash.geometry(f"{s_width}x{s_height}+{x}+{y}")
    splash.configure(bg="#1e222d")

    # Main container frame with subtle border
    frame = tk.Frame(splash, bg="#1e222d", highlightbackground="#0066cc", highlightthickness=2)
    frame.pack(fill=tk.BOTH, expand=True)

    # Logo image setup (supports both script execution and PyInstaller single-file bundle)
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(__file__)

    logo_path = os.path.join(base_path, 'app_icon.png')
    logo_img = None
    if os.path.exists(logo_path):
        try:
            from PIL import Image, ImageTk
            pil_img = Image.open(logo_path).resize((180, 180), Image.Resampling.LANCZOS)
            logo_img = ImageTk.PhotoImage(pil_img)
        except Exception:
            pass

    if logo_img:
        lbl_img = tk.Label(frame, image=logo_img, bg="#1e222d")
        lbl_img.image = logo_img # Prevent garbage collection
        lbl_img.pack(pady=(25, 10))
    else:
        lbl_placeholder = tk.Label(frame, text="🖨️", font=("Arial", 64), bg="#1e222d", fg="#0066cc")
        lbl_placeholder.pack(pady=(25, 10))

    # Titles & Taglines
    lbl_title = tk.Label(frame, text="STUDENT PHOTO PRINT AUTOMATOR", font=("Arial", 14, "bold"), bg="#1e222d", fg="#ffffff")
    lbl_title.pack(pady=(0, 4))

    lbl_sub = tk.Label(frame, text="Card Printing & Queue Management System", font=("Arial", 9), bg="#1e222d", fg="#9aa0a6")
    lbl_sub.pack(pady=(0, 15))

    # Loading status text
    lbl_loading = tk.Label(frame, text="Initializing environment...", font=("Arial", 9, "italic"), bg="#1e222d", fg="#ffc107")
    lbl_loading.pack(pady=(0, 10))

    splash.update()

    # Smooth dismiss timer callback
    def _close_splash():
        splash.destroy()
        root.deiconify()

    root.after(duration_ms, _close_splash)


def main():
    set_dpi_awareness()
    from gui import AppGUI

    root = tk.Tk()
    root.withdraw()  # Hide main window during splash screen
    
    # Show splash screen for 5 seconds (5000ms)
    show_splash_screen(root, duration_ms=5000)
    
    app = AppGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main()
