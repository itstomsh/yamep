# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtWidgets import QComboBox, QMenu, QToolBar, QToolButton
from PySide6.QtGui import QIcon
from yamep.core.utils import load_icon


class ToolbarManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self._buttons = []

        # Separate references
        self.app_toolbar = QToolBar("App Toolbar")
        self.format_toolbar = QToolBar("Formatting Toolbar")

        # Store references to special buttons
        self.delete_button = None
        self.reload_button = None

    def create_app_toolbar(self):
        self.app_toolbar.setObjectName("AppToolbar")
        self._add_app_buttons()
        return self.app_toolbar

    def create_format_toolbar(self):
        self.format_toolbar.setObjectName("FormatToolbar")
        self._add_formatting_buttons()
        self._add_header_combo()
        return self.format_toolbar

    def _add_app_buttons(self):
        actions = [
            ("folder_open_24dp", "Open Folder", self.main_window.open_folder),
            ("save_24dp", "Save", self.main_window.save_file),
            ("create_24dp", "New File", self.main_window.create_new_file),
            ("delete_24dp", 
                "Delete File",
                self.main_window.pick_file_to_delete),
            ("sync_24dp", "Refresh", self.main_window.refresh_tree),
            ("settings_24dp", "Settings", self.main_window.show_settings)
        ]

        for icon_base, tooltip, callback in actions:
            btn = QToolButton()
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            self.app_toolbar.addWidget(btn)
            self._buttons.append((btn, icon_base, tooltip))

            if tooltip == "Save":
                # Save As shares the button, behind its drop-down arrow.
                menu = QMenu(btn)
                menu.addAction(
                    "Save As...", self.main_window.save_file_as)
                btn.setMenu(menu)
                btn.setPopupMode(QToolButton.MenuButtonPopup)
            if tooltip == "Delete File":
                btn.setEnabled(False)
                self.delete_button = btn
            if tooltip == "Refresh":
                self.reload_button = btn

        preview_toggle_btn = QToolButton()
        preview_toggle_btn.setToolTip("Toggle Preview Panel")
        preview_toggle_btn.setCheckable(True)
        preview_toggle_btn.setChecked(True)

        # Set default icon
        suffix = self.main_window._get_theme_icon_suffix()
        icon_path = load_icon(f"visibility_off_24dp_{suffix}.png")
        preview_toggle_btn.setIcon(QIcon(icon_path))

        # Connect signal
        preview_toggle_btn.clicked.connect(
            self.main_window.toggle_preview_visibility)

        # Store reference so App can update icon
        self.preview_toggle_button = preview_toggle_btn

        self.app_toolbar.addWidget(preview_toggle_btn)

        self.app_toolbar.addSeparator()

    def _add_formatting_buttons(self):
        formatting = [
            ("format_bold_24dp", "Bold", self.main_window.editor.make_bold),
            ("format_italic_24dp",
                "Italic",
                self.main_window.editor.make_italics),
            ("code_24dp", "Inline Code", self.main_window.editor.make_code),
            ("data_object_24dp",
                "Fenced Code",
                self.main_window.editor.make_fenced_code),
            ("format_quote_24dp", "Quote",
                self.main_window.editor.make_quote),
            ("link_24dp", "Link",
                self.main_window.editor.make_link),
            ("image_24dp", "Image",
                self.main_window.editor.make_image),
            ("format_list_bulleted_24dp", "Unordered List",
                self.main_window.editor.make_unordered_list),
            ("format_list_numbered_24dp", "Ordered List",
                self.main_window.editor.make_ordered_list),
            ("table_rows_24dp", "Table", 
                self.main_window.editor.make_table),
            ("checklist_24dp", "Task List",
                self.main_window.editor.make_task_list),
            ("file_present_24dp", "Footnote",
                self.main_window.editor.make_footnote),
            ("horizontal_rule_24dp", "Horizontal Rule",
                self.main_window.editor.make_horizontal_rule),
            ("superscript_24dp", "Superscript",
                self.main_window.editor.make_superscript),
            ("subscript_24dp", "Subscript",
                self.main_window.editor.make_subscript),
        ]

        for icon_base, tooltip, callback in formatting:
            btn = QToolButton()
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            self.format_toolbar.addWidget(btn)
            self._buttons.append((btn, icon_base, tooltip))

    def _add_header_combo(self):
        header_combo = QComboBox()
        header_combo.addItems(['H1', 'H2', 'H3', 'H4', 'H5', 'H6'])
        header_combo.setToolTip("Headers")
        header_combo.activated.connect(
            lambda index: self.main_window.editor.make_header(index + 1)
        )
        self.format_toolbar.addWidget(header_combo)

    def update_icons(self, suffix):
        for btn, icon_base, _ in self._buttons:
            try:
                icon_path = f"{icon_base}_{suffix}.png"
                btn.setIcon(QIcon(load_icon(icon_path)))
            except FileNotFoundError:
                btn.setIcon(QIcon(load_icon(f"{icon_base}_5F6368.png")))
