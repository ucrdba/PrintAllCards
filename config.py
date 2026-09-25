import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict, field

@dataclass
class AppConfig:
    search_x: int = 0
    search_y: int = 0
    print_x: int = 0
    print_y: int = 0
    card_type_x: int = 0
    card_type_y: int = 0
    card_type_required: bool = False
    search_start_delay: float = 0.5
    max_search_wait: float = 15.0
    print_delay: float = 4.0
    between_student_delay: float = 1.5
    require_verification: bool = False
    enable_mouse_trail: bool = True
    print_hotkey: str = "ctrl+p"
    dry_run: bool = False
    pause_after_cards: int = 0
    last_excel_path: str = ""
    selected_printer: str = "NullPrinter"
    enable_queue_sync: bool = False
    max_queue_jobs: int = 5
    # DOM control: drive Schoolhouse Smiles through its DevTools port instead of
    # screen coordinates (requires it to run with --remote-debugging-port)
    use_dom_control: bool = True
    dom_debug_port: int = 9222
    card_type_name: str = ""
    # ID Card options last read from Schoolhouse Smiles, so the Card Type Name list
    # is filled at startup (the options only exist on the page while a student is open)
    card_type_options: list = field(default_factory=list)
    target_exe_path: str = r"C:\Program Files\schoolhouse-smiles\schoolhouse-smiles.exe"

    @classmethod
    def get_config_path(cls) -> Path:
        app_dir = Path(os.getenv('APPDATA', os.path.expanduser('~'))) / 'StudentPhotoPrintAutomator'
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir / 'config.json'

    @classmethod
    def load(cls) -> 'AppConfig':
        config_path = cls.get_config_path()
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception:
                return cls()
        return cls()

    def save(self):
        config_path = self.get_config_path()
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(self), f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
