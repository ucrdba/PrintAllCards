import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

class AppLogger:
    def __init__(self, gui_callback: Optional[Callable[[str], None]] = None):
        self.gui_callback = gui_callback
        self.logger = logging.getLogger("StudentPrintAutomator")
        self.logger.setLevel(logging.INFO)
        
        # Avoid duplicate handlers if re-initialized
        if not self.logger.handlers:
            log_dir = Path(os.getenv('LOCALAPPDATA', os.path.expanduser('~'))) / 'StudentPhotoPrintAutomator' / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_file = log_dir / f"print_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            
            file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
            file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"{timestamp} - {message}"
        if level.upper() == "ERROR":
            self.logger.error(message)
            formatted = f"{timestamp} - ERROR - {message}"
        else:
            self.logger.info(message)

        if self.gui_callback:
            self.gui_callback(formatted)

    def error(self, message: str):
        self.log(message, level="ERROR")
