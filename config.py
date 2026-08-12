import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass
class AppConfig:
    search_x: int = 0
    search_y: int = 0
    print_x: int = 0
    print_y: int = 0
    search_start_delay: float = 0.5
    max_search_wait: float = 15.0
    print_delay: float = 2.0
    between_student_delay: float = 0.5
    require_verification: bool = False
    dry_run: bool = False
    last_excel_path: str = ""

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
