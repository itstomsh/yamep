# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import importlib.resources as pkg_resources
import os


def load_theme(theme_name):
    """
    Load a theme from the `themes` directory.
    """
    try:
        theme_data = pkg_resources.read_text(
            "yamep.core.resources.themes", theme_name)
        return theme_data
    except FileNotFoundError:
        logging.error(f"Theme {theme_name} not found.")
        return ""


def load_icon(icon_name):
    """
    Load an icon from the `resources/icons` directory.

    Returns None when the icon is missing. importlib.resources.path() happily
    hands back a path that does not exist, so the file has to be checked
    explicitly - otherwise a typo silently yields a blank toolbar button.
    """
    try:
        with pkg_resources.path(
                    "yamep.core.resources.icons",
                    icon_name
                ) as icon_path:
            if not os.path.isfile(icon_path):
                logging.error(f"Icon {icon_name} not found.")
                return None
            return str(icon_path)
    except (FileNotFoundError, ModuleNotFoundError):
        logging.error(f"Icon {icon_name} not found.")
        return None


def is_valid_dir(path):
    """Returns True if path is a non-empty string that
    exists, is a directory, and is writable."""
    return (
        isinstance(path, str)
        and path.strip() != ""
        and os.path.isdir(path)
        and os.access(path, os.W_OK)
    )


def get_valid_dir(path):
    """Returns path if it is valid; otherwise,
    returns the user's home directory."""
    return path if is_valid_dir(path) else os.path.expanduser("~")
