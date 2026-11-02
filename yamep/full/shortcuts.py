# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtGui import QKeySequence, QShortcut


class ShortcutManager:
    """
    Manages keyboard shortcuts for the application.
    """

    def __init__(self, parent):
        self.parent = parent
        self.setup_shortcuts()

    def setup_shortcuts(self):
        """
        Set up keyboard shortcuts.
        """
        # Open Folder (Ctrl+O)
        open_folder_shortcut = QShortcut(QKeySequence("Ctrl+O"), self.parent)
        open_folder_shortcut.activated.connect(self.parent.open_folder)

        # Save (Ctrl+S)
        save_file_shortcut = QShortcut(QKeySequence("Ctrl+S"), self.parent)
        save_file_shortcut.activated.connect(self.parent.save_file)

        # New File (Ctrl+N)
        new_file_shortcut = QShortcut(QKeySequence("Ctrl+N"), self.parent)
        new_file_shortcut.activated.connect(self.parent.create_new_file)

        # Toggle Theme (Ctrl+T)
        toggle_theme_shortcut = QShortcut(QKeySequence("Ctrl+T"), self.parent)
        toggle_theme_shortcut.activated.connect(self.parent.toggle_theme)

        # Show Settings (Ctrl+,)
        settings_shortcut = QShortcut(QKeySequence("Ctrl+,"), self.parent)
        settings_shortcut.activated.connect(self.parent.show_settings)
