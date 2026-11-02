# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import shutil
import sys
from pathlib import Path
from importlib.resources import files

# Which variant is running. argv[0] alone is not enough: `python -m
# yamep.lite.main` makes it "main", which used to register Lite as full Yamep
# with a broken Exec= line.
exe_name = Path(sys.argv[0]).stem.lower()
IS_LITE = "lite" in exe_name or any(
    mod.startswith("yamep.lite") for mod in sys.modules
)

if IS_LITE:
    APP_ID = "io.github.itstomsh.yamep.lite.desktop"
    # Distinct icon file names: both variants used to install and remove the
    # same yamep.png, so uninstalling one broke the other's icon.
    ICON_NAME = "io.github.itstomsh.yamep.lite.png"
    SOURCE_ICON = "io.github.itstomsh.yamep.lite.png"
    APP_DISPLAY_NAME = "Yamep Lite"
    WM_CLASS = "YamepLite"
    FALLBACK_EXE = "yamep-lite"
else:
    APP_ID = "io.github.itstomsh.yamep.desktop"
    ICON_NAME = "io.github.itstomsh.yamep.png"
    SOURCE_ICON = "io.github.itstomsh.yamep.png"
    APP_DISPLAY_NAME = "Yamep"
    WM_CLASS = "Yamep"
    FALLBACK_EXE = "yamep"


def install_desktop_entry():
    applications_dir = Path.home() / ".local/share/applications"
    icons_dir = Path.home() / ".local/share/icons"

    applications_dir.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)

    exec_path = (
        shutil.which(exe_name)
        or shutil.which(FALLBACK_EXE)
        or FALLBACK_EXE
    )
    icon_target_path = icons_dir / ICON_NAME

    desktop_content = f"""[Desktop Entry]
Type=Application
Name={APP_DISPLAY_NAME}
GenericName=Markdown Editor
Comment=Write Markdown notes with a live preview
Exec={exec_path} %f
Icon={icon_target_path}
Terminal=false
Categories=Utility;TextEditor;
Keywords=Markdown;Notes;Editor;Preview;md;
MimeType=text/markdown;text/x-markdown;
StartupWMClass={WM_CLASS}
StartupNotify=true
"""

    (applications_dir / APP_ID).write_text(desktop_content)

    try:
        icon_source = files("yamep.core.resources").joinpath(SOURCE_ICON)
        with open(icon_source, "rb") as src, \
                open(icon_target_path, "wb") as dst:
            dst.write(src.read())
        print("✅ Desktop entry installed at:", applications_dir / APP_ID)
    except Exception as e:
        print("⚠️ Failed to install icon:", e)


def remove_desktop_entry():
    applications_dir = Path.home() / ".local/share/applications"
    icons_dir = Path.home() / ".local/share/icons"

    try:
        (applications_dir / APP_ID).unlink(missing_ok=True)
        (icons_dir / ICON_NAME).unlink(missing_ok=True)
        print(f"🧹 Removed desktop entry and icon for {APP_DISPLAY_NAME}")
    except Exception as e:
        print("⚠️ Could not remove desktop files:", e)


def parse_args_and_run_integration():
    """
    Run the desktop-integration flags, and return the file to open.

    The desktop entry's Exec line ends with %f, so a Markdown file opened with
    Yamep arrives here as a positional argument.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "file", nargs="?", help="Markdown file to open")
    parser.add_argument(
        "--setup-desktop", action="store_true",
        help="Install .desktop file for Yamep")
    parser.add_argument(
        "--remove-desktop", action="store_true",
        help="Remove .desktop file and icon")
    args, _ = parser.parse_known_args()

    if args.setup_desktop:
        install_desktop_entry()
        sys.exit(0)
    if args.remove_desktop:
        remove_desktop_entry()
        sys.exit(0)

    return args.file
