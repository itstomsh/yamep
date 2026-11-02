# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import json
import os
from pathlib import Path
from platformdirs import user_config_dir
from PySide6.QtCore import QRect, QByteArray

from yamep.core.file_io import atomic_write_text


class ConfigManager:
    """
    Handles loading/saving application configuration and UI state.
    Supports separate config files for Yamep Lite and Full versions.
    """

    def __init__(self, app_variant: str = "full"):
        self.config = {}
        self.app_variant = app_variant
        self.config_path = Path(
            user_config_dir("yamep")) / f"config_{app_variant}.json"
        self.load()

    def load(self):
        """Load config from disk."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
                logging.info("Config loaded.")
        except (FileNotFoundError, json.JSONDecodeError):
            logging.info("Config file doesn't exist.")
            self.config = {}
        except Exception as e:
            logging.error(f"Error loading config: {e}")
            self.config = {}

    def save(self):
        """
        Save current config to disk, atomically: a crash midway through a
        plain write leaves truncated JSON behind, and load() then silently
        discards every setting.
        """
        os.makedirs(self.config_path.parent, exist_ok=True)
        atomic_write_text(self.config_path, json.dumps(self.config, indent=4))

    # Window state management
    def save_window_state(self, state: QByteArray):
        """Store the result of QWidget.saveGeometry() (frame included)."""
        self.config['window_state'] = state.toBase64().data().decode()

    def get_window_state(self):
        if state_str := self.config.get('window_state'):
            return QByteArray.fromBase64(state_str.encode())
        return None

    def save_window_geometry(self, geometry: QRect):
        self.config['window_geometry'] = [
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height()
        ]

    def get_window_geometry(self):
        return self.config.get('window_geometry')

    # Splitter state management
    def save_splitter_state(self, name: str, state: QByteArray):
        self.config[f'{name}_state'] = state.toBase64().data().decode()

    def get_splitter_state(self, name: str):
        if state_str := self.config.get(f'{name}_state'):
            return QByteArray.fromBase64(state_str.encode())
        return None

    # File tree state management
    def save_file_tree_state(self, expanded_paths: list, scroll_pos: int):
        self.config['expanded_paths'] = expanded_paths
        self.config['tree_scroll_pos'] = scroll_pos

    def get_expanded_paths(self):
        return self.config.get('expanded_paths', [])

    def get_tree_scroll_pos(self):
        return self.config.get('tree_scroll_pos', 0)

    # Application settings
    def get_value(self, key, default=None):
        return self.config.get(key, default)

    def set_value(self, key, value):
        self.config[key] = value

    def get_last_folder(self):
        return self.config.get('last_folder', os.path.expanduser("~"))

    def get_theme(self):
        return self.config.get('current_theme', 'default')

    def get_show_hidden(self):
        return self.config.get('show_hidden_files', False)

    # Toolbar position
    def save_toolbar_state(self, state: QByteArray):
        self.config['toolbar_state'] = state.toBase64().data().decode()

    def get_toolbar_state(self):
        if state_str := self.config.get('toolbar_state'):
            return QByteArray.fromBase64(state_str.encode())
        return QByteArray()
