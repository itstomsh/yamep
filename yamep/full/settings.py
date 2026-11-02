# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QGroupBox, QCheckBox)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = parent
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(300)

        # ----------------------------
        # File View group
        # ----------------------------
        file_view_group = QGroupBox("File View")
        file_view_layout = QVBoxLayout()

        self.show_hidden_checkbox = QCheckBox("Show hidden files/folders")
        # Default to unchecked (False)
        self.show_hidden_checkbox.setChecked(False)
        # If we want to reflect the current state from config or from the App:
        if hasattr(self.app, 'show_hidden_files'):
            self.show_hidden_checkbox.setChecked(self.app.show_hidden_files)

        # Connect to a method that applies this setting
        self.show_hidden_checkbox.stateChanged.connect(
            self.on_show_hidden_toggled)

        file_view_layout.addWidget(self.show_hidden_checkbox)
        file_view_group.setLayout(file_view_layout)
        layout.addWidget(file_view_group)

        # Theme Section
        theme_group = QGroupBox("Appearance")
        theme_layout = QVBoxLayout()

        # Theme Toggle Button
        self.theme_button = QPushButton("Toggle Theme")
        self.theme_button.clicked.connect(self.toggle_theme)
        theme_layout.addWidget(self.theme_button)

        # Add layout toggle button
        self.layout_button = QPushButton("Toggle Editor/Preview Layout")
        self.layout_button.clicked.connect(self.toggle_layout)
        theme_layout.addWidget(self.layout_button)

        self.theme_label = QLabel()
        theme_layout.addWidget(self.theme_label)

        theme_group.setLayout(theme_layout)
        layout.addWidget(theme_group)

        # About Section
        about_group = QGroupBox("About")
        about_layout = QVBoxLayout()
        about_label = QLabel(
            "yamep - Yet Another Markdown Editor & Preview\n"
            "Version 1.2.0\n\n"
            "Created by tomsh\n"
            "Website: github.com/itstomsh/yamep\n"
            "License: GPL-3.0-or-later"
        )
        about_layout.addWidget(about_label)
        about_group.setLayout(about_layout)
        layout.addWidget(about_group)

    def toggle_layout(self):
        """Toggle the editor/preview layout orientation"""
        if hasattr(self.app, 'toggle_editor_preview_layout'):
            self.app.toggle_editor_preview_layout()

    def on_show_hidden_toggled(self, state):
        """
        Called when the user toggles the 'Show hidden files' checkbox.
        """
        is_checked = (state == 2)
        self.parent().toggle_show_hidden(is_checked)

    def toggle_theme(self):
        """
        Toggle between available themes.
        """
        self.parent().toggle_theme()
