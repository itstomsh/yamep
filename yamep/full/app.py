# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import shutil
import sys
import traceback
import importlib.resources

from PySide6.QtGui import QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QTreeView, QFileSystemModel, QFileDialog,
    QMessageBox, QLabel, QProgressBar, QMenu
)
from PySide6.QtCore import Qt, QDir, QTimer, QModelIndex

from .editor import MarkdownEditor
from .preview import MarkdownPreview
from .settings import SettingsDialog
from .shortcuts import ShortcutManager
from yamep.core.utils import load_icon, load_theme, get_valid_dir
from .toolbar import ToolbarManager
from yamep.core.config_manager import ConfigManager
from yamep.core.file_io import (
    DocumentFileGuard, atomic_write_text, document_text, markdown_save_path,
)
from yamep.core.line_anchors import editor_top_line, scroll_editor_to_line
from yamep.core.markdown_utils import set_task_checked


class Yamep(QMainWindow):
    """
    Main application window rewritten to use Qt's built-in QFileSystemModel/QTreeView
    instead of the custom FileTree.
    """
    def __init__(self, file_to_open=None):
        super().__init__()
        # A file named on the command line, from the desktop entry's %f.
        self._file_to_open = file_to_open

        # Initialize core properties first
        self.themes = ["default", "dark_theme.qss", "light_theme.qss", "blue_theme.qss"]
        self.current_theme_index = 0
        self.is_reloading = False
        self.loading_dialog = None
        self.toolbar_manager = None
        self.current_file_path = None
        self.show_hidden_files = False
        self.force_show_preview_loading = False
        self.preview_enabled = True
        self.current_root = QDir.homePath()

        # Load config early
        self.config_manager = ConfigManager("full")
        self.show_hidden_files = self.config_manager.get_show_hidden()

        last_folder = self.config_manager.get_last_folder()
        self.current_root = get_valid_dir(last_folder)

        # Initialize core widgets BEFORE UI setup
        self.editor = MarkdownEditor()
        self.preview = MarkdownPreview()

        # Built-in file system model and tree view
        self.file_model = QFileSystemModel()
        self.tree_view = QTreeView()

        # Set window attributes
        self.setAttribute(Qt.WA_DeleteOnClose)

        # Configure exception handling
        sys.excepthook = self._exception_handler

        # Set Window Icon
        icon = QIcon.fromTheme('yamep')
        if not icon.isNull():
            self.setWindowIcon(icon)
        else:
            # Fallback to packaged icon
            icon_data = importlib.resources.read_binary('yamep.core.resources', 'io.github.itstomsh.yamep.png')
            pixmap = QPixmap()
            pixmap.loadFromData(icon_data)
            icon = QIcon(pixmap)
            self.setWindowIcon(icon)

        # Build UI components
        self.setup_ui()

        # Restore state AFTER UI is built
        self._apply_initial_theme()
        self._open_initial_file()

        self.restoreState(self.config_manager.get_toolbar_state())

        # Schedule initial load
        QTimer.singleShot(100, self.initial_load)

    def _exception_handler(self, exc_type, exc_value, exc_tb):
        """Handle uncaught exceptions"""
        traceback.print_exception(exc_type, exc_value, exc_tb)
        QMessageBox.critical(None, "Critical Error",
                             f"{exc_type.__name__}: {exc_value}\n\nSee console for details")

    def _apply_initial_theme(self):
        """Apply saved theme from config"""
        if saved_theme := self.config_manager.get_theme():
            self.apply_theme(saved_theme)

    def _open_initial_file(self):
        """Open the file given on the command line, else the last one used."""
        if self._file_to_open and not os.path.exists(self._file_to_open):
            # A new note, as with any editor: created by the first save.
            self.current_file_path = os.path.abspath(self._file_to_open)
            self.file_guard.track(self.current_file_path)
            self.preview.set_base_path(
                os.path.dirname(self.current_file_path))
            self.update_window_title()
            return
        initial = self._file_to_open or self.config_manager.get_value(
            'last_opened_file')
        if initial and os.path.isfile(initial):
            self.open_file_in_editor(os.path.abspath(initial))

    def setup_ui(self):
        """
        Initialize the window, splitters, toolbar, editor, preview, and file model/tree.
        """
        self.setWindowTitle("yamep - Yet Another Markdown Editor & Preview")

        # Restore window geometry. saveGeometry()/restoreGeometry() round-trip
        # the window frame; setGeometry(self.geometry()) loses it, which made
        # the window drift down-right on every start.
        if window_state := self.config_manager.get_window_state():
            self.restoreGeometry(window_state)
        elif geometry := self.config_manager.get_window_geometry():
            self.setGeometry(*geometry)
        else:
            self.setGeometry(100, 100, 1200, 800)

        # Set up the file-system model to list directories and files
        filter_flags = QDir.NoDotAndDotDot | QDir.Files | QDir.AllDirs 
        if self.show_hidden_files:
            filter_flags |= QDir.Hidden
        self.file_model.setFilter(filter_flags)
        # If you want to display only Markdown files plus folders, you could do:
        self.file_model.setNameFilters(["*.md"])
        self.file_model.setNameFilterDisables(False)

        # Configure the tree view
        self.file_model.setRootPath(self.current_root)
        self.tree_view.setModel(self.file_model)
        self.tree_view.setRootIndex(self.file_model.index(self.current_root))

        # QFileSystemModel lists a directory only when it is needed, so the
        # saved folders are expanded as they become known, one level per
        # directoryLoaded.
        self.paths_to_expand = {
            path for path in self.config_manager.get_expanded_paths()
            if self._is_inside_root(path)
        }
        self.file_model.directoryLoaded.connect(self.restore_expanded_paths)

        # Connect signals for selection/double-click
        self.tree_view.doubleClicked.connect(self.on_tree_double_clicked)
        self.tree_view.selectionModel().selectionChanged.connect(
            lambda *_: self.update_delete_button_state()
        )

        # Splitters for layout
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.editor_preview_splitter = QSplitter(Qt.Vertical)
        self.editor_preview_splitter.addWidget(self.editor)
        self.editor_preview_splitter.addWidget(self.preview)

        self.main_splitter.addWidget(self.tree_view)
        self.main_splitter.addWidget(self.editor_preview_splitter)
        self.setCentralWidget(self.main_splitter)

        # Restore splitter states
        self.restore_splitter_states()

        # Settings dialog
        self.settings_dialog = SettingsDialog(self)

        self.toolbar_manager = ToolbarManager(self)
        self.app_toolbar = self.toolbar_manager.create_app_toolbar()
        self.format_toolbar = self.toolbar_manager.create_format_toolbar()

        self.addToolBar(Qt.LeftToolBarArea, self.app_toolbar)
        self.addToolBar(Qt.RightToolBarArea, self.format_toolbar)

        self.restoreState(self.config_manager.get_toolbar_state())

        # Connect signals. The preview is debounced: rendering on every
        # keystroke reloaded the entire web view once per character.
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.refresh_preview)
        self.editor.text_updated.connect(
            lambda _text: self.preview_timer.start(300)
        )
        # Set while the editor follows a preview scroll, so that move is not
        # sent straight back to the preview.
        self._following_preview = False
        self.editor.verticalScrollBar().valueChanged.connect(self.sync_preview_scroll)
        self.preview.setup_scroll_channel()
        self.preview.scrollSync.previewLineChanged.connect(self.on_preview_line_changed)
        self.preview.taskBridge.taskToggled.connect(self.on_task_toggled)
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.show_tree_context_menu)

        # Shortcuts
        self.shortcut_manager = ShortcutManager(self)

        # Editor mod-changed => update window title
        self.editor.document().modificationChanged.connect(self.on_document_modified)

        # Atomic saves, and changes other programs make to the open file.
        self.file_guard = DocumentFileGuard(self, self.editor)
        self.file_guard.notice.connect(self.show_temporary_status_message)

        # Preview loading label/progress
        self.preview_loading_label = QLabel("Loading preview...")
        self.preview_progress = QProgressBar()
        self.preview_progress.setRange(0, 0)  # Indeterminate spinner style
        self.statusBar().addPermanentWidget(self.preview_loading_label)
        self.statusBar().addPermanentWidget(self.preview_progress)

        self.preview_loading_label.hide()
        self.preview_progress.hide()

        # Set preview visibility from config
        preview_visible = bool(
            self.config_manager.get_value('preview_visible', True))
        self.preview.setVisible(preview_visible)
        self.preview_enabled = preview_visible
        self.update_preview_toggle()

        #self.tree_view.header().setSectionResizeMode(0, QHeaderView.Interactive)
        QTimer.singleShot(0, lambda: self.tree_view.setColumnWidth(0, self.tree_view.viewport().width()))
        #self.tree_view.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree_view.setColumnHidden(2, True)
        self.tree_view.setFocusPolicy(Qt.NoFocus)
        self.main_splitter.setHandleWidth(3)
        self.editor_preview_splitter.setHandleWidth(3)

    def refresh_preview(self):
        """Re-render the preview from the editor's current content."""
        if not self.preview_enabled:
            return
        self.preview.update_preview(
            document_text(self.editor),
            self.themes[self.current_theme_index]
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Adjust the first column's width to match the tree view's viewport width
        self.tree_view.setColumnWidth(0, self.tree_view.viewport().width())

    def show_tree_context_menu(self, pos):
        # Map the position to an index in the tree view
        index = self.tree_view.indexAt(pos)
        menu = QMenu(self.tree_view)

        if index.isValid():
            # Get the file path from the model
            file_path = self.file_model.filePath(index)
            if self.file_model.isDir(index):
                # If it’s a directory, offer a “New File” action
                new_action = menu.addAction("New File")
                new_action.triggered.connect(lambda: self.create_new_file(file_path))
            else:
                # For a file, offer Open and Delete actions
                open_action = menu.addAction("Open")
                open_action.triggered.connect(lambda: self.open_file_in_editor(file_path))
                delete_action = menu.addAction("Delete")
                delete_action.triggered.connect(lambda: self.delete_file(file_path))
        else:
            # If no valid index, assume the user clicked in blank area of the tree:
            # Optionally offer a “New File” action in the current root directory.
            folder = self.current_root or QDir.homePath()
            new_action = menu.addAction("New File")
            new_action.triggered.connect(lambda: self.create_new_file(folder))

        menu.exec_(self.tree_view.viewport().mapToGlobal(pos))

    def sync_preview_scroll(self, value):
        # By source line rather than by ratio: a ratio drifts as soon as an
        # image or a heading renders taller than its line in the editor.
        if self._following_preview:
            return
        self.preview.scroll_to_line(editor_top_line(self.editor))

    def on_preview_line_changed(self, line):
        # Signals must stay live: QAbstractScrollArea moves the text through
        # the scroll bar's valueChanged. Blocking them moved only the handle,
        # and the editor was not repainted until the mouse reached it.
        self._following_preview = True
        try:
            scroll_editor_to_line(self.editor, line)
        finally:
            self._following_preview = False

    def on_tree_double_clicked(self, index: QModelIndex):
        """
        If a file (not a directory) was double-clicked in the tree, open it in the editor.
        """
        if not self.file_model.isDir(index):
            file_path = self.file_model.filePath(index)
            self.open_file_in_editor(file_path)

    def get_selected_file_in_tree(self):
        """
        Return the selected file path in the tree if it is a file, or None if selection is invalid/dir.
        """
        index = self.tree_view.selectionModel().currentIndex()
        if index.isValid() and not self.file_model.isDir(index):
            return self.file_model.filePath(index)
        return None

    def confirm_discard_changes(self):
        """
        Ask about unsaved edits before replacing the editor's content.
        Returns False if the user cancelled.
        """
        if not self.editor.document().isModified():
            return True

        reply = QMessageBox.question(
            self, "Unsaved Changes",
            "The document has been modified. Do you want to save changes?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save
        )
        if reply == QMessageBox.Save:
            return bool(self.save_file())
        return reply == QMessageBox.Discard

    def open_file_in_editor(self, file_path):
        """
        Load a file's contents into the editor.
        """
        if os.path.isfile(file_path):
            if not self.confirm_discard_changes():
                return
            try:
                self.editor.setPlainText(self.file_guard.open(file_path))
                self.current_file_path = file_path
                self.preview.set_base_path(file_path)
                self.config_manager.set_value('last_opened_file', file_path)
                self.config_manager.save()
                self.editor.document().setModified(False)
                self.update_window_title()
                self.update_delete_button_state()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to open file: {e}")

    def initial_load(self):
        """
        In the old code, we showed a loading dialog and scanned in the background.
        Here, the QFileSystemModel does that automatically. Just trigger the preview.
        """
        self.load_preview()

    def load_preview(self, markdown_text=None, theme=None):
        """
        Load and render the markdown preview.
        Shows a loading spinner until rendering is finished (optional).
        """
        # If user turned off preview, skip. This checks the flag rather than
        # isVisible() because the method hides the widget while it renders -
        # an overlapping call would otherwise be dropped and never restored.
        if not self.preview_enabled:
            return

        markdown_text = markdown_text or document_text(self.editor)
        theme = theme or self.themes[self.current_theme_index]

        self.preview.hide()
        self.preview_loading_label.show()
        self.preview_progress.show()
        self.statusBar().show()

        def on_preview_ready():
            self.preview_loading_label.hide()
            self.preview_progress.hide()
            self.statusBar().hide()
            if self.preview_enabled:
                self.preview.show()

        self.preview.update_preview(markdown_text, theme, on_finished=on_preview_ready)

    def toggle_preview_visibility(self):
        # The flag, not isVisible(): load_preview() hides the widget while it
        # renders, which is not the user turning the preview off.
        now_visible = not self.preview_enabled
        self.preview.setVisible(now_visible)
        self.preview_enabled = now_visible
        self.update_preview_toggle()

        if now_visible:
            self.load_preview()
        else:
            self.preview.hide()
            self.preview_loading_label.hide()
            self.preview_progress.hide()
            self.statusBar().hide()

    def update_preview_toggle(self):
        """Show the preview button's state in the current theme's colours."""
        button = self.toolbar_manager and self.toolbar_manager.preview_toggle_button
        if not button:
            return
        state = "visibility_off" if self.preview_enabled else "visibility"
        suffix = self._get_theme_icon_suffix()
        button.setIcon(QIcon(load_icon(f"{state}_24dp_{suffix}.png")))
        button.setChecked(self.preview_enabled)

    def on_document_modified(self, changed: bool):
        self.update_window_title()

    def update_window_title(self):
        if self.current_file_path:
            filename = os.path.basename(self.current_file_path)
        else:
            filename = "Untitled"

        if self.editor.document().isModified():
            self.setWindowTitle(f"{filename} * - yamep")
        else:
            self.setWindowTitle(f"{filename} - yamep")

    def show_temporary_status_message(self, message: str, timeout=3000):
        """
        Show a temporary message in the status bar, then hide the bar.
        """
        self.statusBar().show()
        self.statusBar().showMessage(message, timeout)
        QTimer.singleShot(timeout, self.statusBar().hide)

    def open_folder(self):
        """
        Allow the user to select a folder and load it into the tree view.
        """
        folder = QFileDialog.getExistingDirectory(self, "Open Folder")
        if folder:
            self.current_root = folder
            # A different folder: nothing left to reopen from the old one.
            self.paths_to_expand = set()
            self.file_model.setRootPath(folder)
            self.tree_view.setRootIndex(self.file_model.index(folder))

    def refresh_tree(self):
        """
        Re-load the current folder in the file tree.
        (QFileSystemModel automatically updates for changes, but let's mimic old behavior.)
        """
        if self.current_root:
            self.file_model.setRootPath(self.current_root)
            self.tree_view.setRootIndex(self.file_model.index(self.current_root))
            self.show_temporary_status_message("Reload completed")

    def get_current_folder(self):
        """
        Return the folder currently shown as the root in the tree.
        """
        return self.current_root if self.current_root and isinstance(self.current_root, str) else os.path.expanduser("~")

    def pick_file_to_delete(self):
        """
        Delete either the currently opened file or the file selected in the tree,
        or ask the user if they differ.
        """
        selected_file = self.get_selected_file_in_tree()
        opened_file = getattr(self, "current_file_path", None)

        if not selected_file and not opened_file:
            QMessageBox.information(self, "Nothing to delete", "No file is selected or opened.")
            return

        if selected_file and opened_file and (selected_file != opened_file):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Delete File")
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setText(
                f"You have selected '{os.path.basename(selected_file)}' in the tree,\n"
                f"but '{os.path.basename(opened_file)}' is opened in the editor.\n\n"
                "Which file do you want to delete?"
            )

            delete_selected = msg_box.addButton("Delete Selected", QMessageBox.AcceptRole)
            delete_opened = msg_box.addButton("Delete Opened", QMessageBox.AcceptRole)
            cancel_button = msg_box.addButton("Cancel", QMessageBox.RejectRole)

            msg_box.setDefaultButton(cancel_button)
            msg_box.exec()

            if msg_box.clickedButton() == delete_selected:
                file_to_delete = selected_file
            elif msg_box.clickedButton() == delete_opened:
                file_to_delete = opened_file
            else:
                return
        else:
            file_to_delete = selected_file or opened_file

        if not file_to_delete:
            return
        else:
            self.delete_file(file_to_delete)

    def delete_file(self, file_to_delete):
        """
        Delete the given file. If it’s open in the editor, clear the editor.
        """
        confirm = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete:\n{file_to_delete}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            if os.path.isdir(file_to_delete):
                # Deleting a whole tree deserves its own confirmation - the
                # dialog above only mentioned deleting a file.
                confirm_dir = QMessageBox.question(
                    self,
                    "Confirm Deletion",
                    f"{file_to_delete}\nis a folder. "
                    "Delete it and everything inside it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if confirm_dir != QMessageBox.Yes:
                    return
                shutil.rmtree(file_to_delete)
            else:
                os.remove(file_to_delete)
        except Exception as e:
            QMessageBox.warning(self, "Delete Error", f"Could not delete:\n{e}")
            return

        self.show_temporary_status_message("File deleted")

        # If the deleted file was open in the editor, clear it
        if file_to_delete == self.current_file_path:
            self.file_guard.forget()
            self.editor.clear()
            self.current_file_path = None
            self.editor.document().setModified(False)
            self.update_window_title()

        # If the deleted file was selected, clear that selection
        if file_to_delete == self.get_selected_file_in_tree():
            self.tree_view.setCurrentIndex(QModelIndex())

        self.update_delete_button_state()

    def update_delete_button_state(self):
        """
        Enable 'Delete File' button if there's either:
         - A valid (non-directory) file selected in the tree, OR
         - A currently opened file.
        Disable otherwise.
        """
        enable = False
        selected_file_in_tree = self.get_selected_file_in_tree()
        opened_file = getattr(self, "current_file_path", None)

        if selected_file_in_tree or opened_file:
            enable = True

        if self.toolbar_manager and self.toolbar_manager.delete_button:
            self.toolbar_manager.delete_button.setEnabled(enable)

    def save_file(self):
        """
        Save changes to the current file if it exists, otherwise prompt 'Save As'.
        """
        if self.current_file_path:
            try:
                if not self.file_guard.save(
                        self.current_file_path, document_text(self.editor)):
                    return False

                self.editor.document().setModified(False)
                self.update_window_title()
                self.show_temporary_status_message("File saved")
                return True
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save file: {e}")
                return False
        else:
            return self.save_file_as()

    def save_file_as(self):
        """
        Prompt the user to save the current file to a new location.
        Returns True only if the file was actually written - closeEvent()
        relies on that to decide whether it may close the window.
        """
        start_dir = (
            os.path.dirname(self.current_file_path)
            if self.current_file_path else self.get_current_folder()
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save File As", start_dir, "Markdown Files (*.md)")
        file_path = file_path and markdown_save_path(self, file_path)
        if not file_path:
            return False

        previous_path = self.current_file_path
        self.current_file_path = file_path
        if self.save_file():
            self.preview.set_base_path(file_path)
            self.config_manager.set_value('last_opened_file', file_path)
            self.config_manager.save()
            self.update_window_title()
            # Saving changes no text, so nothing else would re-render, and
            # relative images have just moved.
            self.refresh_preview()
            return True

        self.current_file_path = previous_path
        return False

    def create_new_file(self, folder=None):
        """
        Prompt the user for a file name, create it, and open it in the editor.
        """
        if not folder:
            default_dir = self.get_current_folder()
        else:
            default_dir = folder

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "New File",
            default_dir,
            "Markdown Files (*.md)"
        )
        file_path = file_path and markdown_save_path(self, file_path)
        if file_path:
            # Before anything reaches the disk: cancelling here has to leave
            # the chosen file exactly as it was.
            if not self.confirm_discard_changes():
                return
            self.editor.document().setModified(False)

            try:
                atomic_write_text(file_path, "")
                self.open_file_in_editor(file_path)

                # If newly created file is in the current tree folder, select it:
                if self._is_inside_root(os.path.dirname(file_path)):
                    self.file_model.setRootPath(self.current_root)  # Force refresh
                    self.tree_view.setRootIndex(self.file_model.index(self.current_root))
                    # Attempt to select the new file
                    idx = self.file_model.index(file_path)
                    if idx.isValid():
                        self.tree_view.setCurrentIndex(idx)

            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to create file: {e}")

    def on_task_toggled(self, line, checked):
        """Apply a checkbox ticked in the preview to the line it came from."""
        document = self.editor.document()
        if not 0 <= line < document.blockCount():
            return
        block = document.findBlockByNumber(line)
        updated = set_task_checked(block.text(), checked)
        # The preview can be one render behind the editor, so only touch a
        # line that really still carries a task marker.
        if updated is None or updated == block.text():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        cursor.insertText(updated)

    def expanded_tree_paths(self):
        """The folders currently open in the tree, deepest ones included."""
        paths = []
        self._collect_expanded(self.tree_view.rootIndex(), paths)
        return paths

    def _collect_expanded(self, parent, paths):
        for row in range(self.file_model.rowCount(parent)):
            index = self.file_model.index(row, 0, parent)
            if self.tree_view.isExpanded(index):
                paths.append(self.file_model.filePath(index))
                self._collect_expanded(index, paths)

    def restore_expanded_paths(self, _loaded_directory=''):
        """Reopen a saved folder as soon as the model knows about it."""
        for path in list(self.paths_to_expand):
            index = self.file_model.index(path)
            if index.isValid():
                self.tree_view.expand(index)
                self.paths_to_expand.discard(path)

    def _is_inside_root(self, directory):
        """
        True if `directory` is the tree root or below it. commonprefix() is a
        string operation, so it matched '/home/u/document' against a
        '/home/u/doc' root.
        """
        if not self.current_root or not directory:
            return False
        try:
            root = os.path.abspath(self.current_root)
            return os.path.commonpath([os.path.abspath(directory), root]) == root
        except ValueError:      # e.g. different drives on Windows
            return False

    def show_settings(self):
        """
        Open the settings dialog when the 'Settings' toolbar button is clicked.
        """
        self.settings_dialog.exec_()

    def toggle_theme(self):
        """
        Cycle through all themes and apply them, then update config.
        """
        self.current_theme_index = (self.current_theme_index + 1) % len(self.themes)
        new_theme = self.themes[self.current_theme_index]
        self.apply_theme(new_theme)
        self.config_manager.set_value('current_theme', new_theme)
        self.config_manager.save()

    def apply_theme(self, theme_name):
        try:
            self.current_theme_index = self.themes.index(theme_name)
        except ValueError:
            logging.error(f"Theme {theme_name} not found in available themes")
            return

        self.setStyleSheet("" if theme_name == "default" else load_theme(theme_name))

        if hasattr(self, 'toolbar_manager') and self.toolbar_manager:
            self.toolbar_manager.update_icons(self._get_theme_icon_suffix())
            self.update_preview_toggle()
        else:
            logging.warning("Toolbar manager not initialized when applying theme")

        # A single render per theme change; this used to run two or three
        # times, and the extra calls were silently dropped anyway.
        self.force_show_preview_loading = True
        self.load_preview(theme=theme_name)
        QTimer.singleShot(1000, lambda: setattr(self, "force_show_preview_loading", False))

        self.config_manager.set_value('current_theme', theme_name)
        self.config_manager.save()

    def restore_splitter_states(self):
        """
        Restore splitter orientations and sizes from config.
        """
        orientation = self.config_manager.get_value('editor_preview_orientation', 'vertical')
        self.editor_preview_splitter.setOrientation(
            Qt.Vertical if orientation == 'vertical' else Qt.Horizontal
        )

        if editor_state := self.config_manager.get_splitter_state('editor_preview'):
            self.editor_preview_splitter.restoreState(editor_state)
        else:
            total = self.editor_preview_splitter.size().height()
            if total == 0:
                QTimer.singleShot(0, lambda: self.editor_preview_splitter.setSizes([1, 1]))
            else:
                self.editor_preview_splitter.setSizes([total // 2, total // 2])

        if main_state := self.config_manager.get_splitter_state('main_splitter'):
            self.main_splitter.restoreState(main_state)
        else:
            QTimer.singleShot(0, lambda: self.main_splitter.setSizes([int(self.width() * 0.20), int(self.width() * 0.80)]))

    def toggle_editor_preview_layout(self):
        """
        Switch the orientation of the editor-preview splitter.
        """
        current_orientation = self.editor_preview_splitter.orientation()
        new_orientation = Qt.Horizontal if current_orientation == Qt.Vertical else Qt.Vertical
        sizes = self.editor_preview_splitter.sizes()
        self.editor_preview_splitter.setOrientation(new_orientation)
        if sum(sizes) > 0:
            self.editor_preview_splitter.setSizes(sizes)

    def toggle_show_hidden(self, show_hidden: bool):
        """
        Called when the user toggles 'Show hidden files' in Settings.
        Reapply the filter on QFileSystemModel and reload.
        """
        self.show_hidden_files = show_hidden
        self.config_manager.set_value('show_hidden_files', show_hidden)
        self.config_manager.save()

        filter_flags = QDir.NoDotAndDotDot | QDir.Files | QDir.AllDirs
        if self.show_hidden_files:
            filter_flags |= QDir.Hidden
        self.file_model.setFilter(filter_flags)

        # Re-root so the updated filter is applied
        if self.current_root:
            self.file_model.setRootPath(self.current_root)
            self.tree_view.setRootIndex(self.file_model.index(self.current_root))

    def closeEvent(self, event):
        """
        Before closing, prompt to save unsaved changes, save config, etc.
        """
        if self.editor.document().isModified():
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "The document has been modified. Do you want to save changes?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )
            if reply == QMessageBox.Save:
                if not self.save_file():
                    event.ignore()
                    return
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return

        self.config_manager.save_window_geometry(self.geometry())
        self.config_manager.save_window_state(self.saveGeometry())

        try:
            if self.main_splitter:
                self.config_manager.save_splitter_state(
                    'main_splitter',
                    self.main_splitter.saveState()
                )
            if self.editor_preview_splitter:
                self.config_manager.save_splitter_state(
                    'editor_preview',
                    self.editor_preview_splitter.saveState()
                )
                orientation = "vertical" if self.editor_preview_splitter.orientation() == Qt.Vertical else "horizontal"
                self.config_manager.set_value('editor_preview_orientation', orientation)
        except Exception as e:
            logging.error(f"Error saving splitter states: {e}")

        self.config_manager.set_value(
            'last_folder', self.current_root or os.path.expanduser("~")
        )
        self.config_manager.set_value('show_hidden_files', self.show_hidden_files)
        self.config_manager.save_file_tree_state(
            self.expanded_tree_paths(),
            self.tree_view.verticalScrollBar().value())
        self.config_manager.set_value(
            'toolbar_state', self.saveState().toBase64().data().decode()
        )
        self.config_manager.set_value('preview_visible', self.preview_enabled)

        self.config_manager.save()

        # No change dialogs for a window that is going away.
        self.file_guard.forget()
        event.accept()

    def _get_theme_icon_suffix(self):
        theme = self.themes[self.current_theme_index]
        if theme == "default":
            # Follow the system palette, as the preview does.
            return "FFFFFF" if self.preview.is_system_dark_mode() else "5F6368"
        return "FFFFFF" if "dark" in theme or "blue" in theme else "5F6368"
