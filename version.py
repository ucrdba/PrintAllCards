"""
Single source of truth for the application version.

Bump APP_VERSION here and everything that displays a version follows: the header
banner, the main window title bar, the splash screen and the Windows
AppUserModelID.

Note that installer_setup/setup_builder.iss keeps its own MyAppVersion, because
the Inno Setup preprocessor cannot import Python. When releasing, change both.
"""

APP_VERSION = "1.1"
