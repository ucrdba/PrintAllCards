import sys
import os
import ctypes

def set_dpi_awareness():
    """Sets high DPI awareness on Windows to prevent coordinate scaling mismatch."""
    if sys.platform == 'win32':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-monitor DPI aware
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

def main():
    set_dpi_awareness()
    import tkinter as tk
    from gui import AppGUI

    root = tk.Tk()
    app = AppGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main()
