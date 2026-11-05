# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import re
import importlib.resources

import urllib.parse
import xml.etree.ElementTree as etree

import markdown
from markdown import Extension
from markdown.treeprocessors import Treeprocessor
from PySide6.QtCore import (
    QEvent, QPointF, QRectF, QSize, Qt, QTimer, QUrl
)
from PySide6.QtGui import (
    QColor, QIcon, QKeySequence, QMovie, QPainter,
    QPainterPath, QPalette, QPen, QPixmap, QShortcut, QTextCursor
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSplitter, QTabWidget, QTextBrowser, QTextEdit,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
)

from yamep.core import markdown_insert
from yamep.core.config_manager import ConfigManager
from yamep.core.file_io import (
    DocumentFileGuard, atomic_write_text, document_text, markdown_save_path,
)
from yamep.core.line_anchors import (
    ANCHOR_MARKER, add_line_markers, anchor_line_for_y, anchor_y_for_line,
    document_line_anchors, editor_top_line, scroll_editor_to_line,
)
from yamep.core.markdown_utils import (
    TasklistExtension, set_task_checked, task_lines, task_states,
)
from yamep.core.utils import load_theme, open_external

APP_NAME = "yamep lite"


# The shared markdown stylesheets are written for a browser engine, where a
# 1.6 line-height and roomy paragraph margins look airy. QTextBrowser turns
# both into real vertical space around every block - every paragraph, list item
# and soft-wrapped line - so the preview reads as a stack of separate rows
# instead of one document.
#
# The spacing has to be edited into the stylesheet itself rather than appended
# as an override: Qt's rich text engine parses only the first <style> element,
# and within one sheet a later rule does not reliably beat an earlier one.
# Only this widget is affected; the full variant renders the same stylesheets
# in QtWebEngine, which lays them out as intended.
LINE_HEIGHT_DECL = re.compile(r'\s*line-height\s*:[^;}]*;?', re.IGNORECASE)
CSS_RULE = re.compile(r'([^{}]+)\{([^}]*)\}')
EM_MARGIN = re.compile(
    r'(margin(?:-top|-bottom)?\s*:\s*)([\d.]+)em', re.IGNORECASE)
BLOCK_TAGS = re.compile(r'\b(p|ul|ol|li|blockquote)\b', re.IGNORECASE)
MAX_BLOCK_MARGIN_EM = 0.3

IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp')

# Marks a folder in the file tree whose contents are not listed yet.
UNLISTED_ROLE = Qt.UserRole + 1

URI_SCHEME = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]+:')


def image_link_target(source, base_dir):
    """Where a Markdown image points: its URI, or a file:// URL."""
    if URI_SCHEME.match(source):
        return source
    path = urllib.parse.unquote(source)
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)
    return QUrl.fromLocalFile(os.path.abspath(path)).toString()


class ImageLinkTreeprocessor(Treeprocessor):
    """
    Turn images into links to the viewer: Qt's rich text would lay them out
    at full size in the middle of the text.

    Done on the parsed tree rather than on the source, so that an image shown
    as an example in a code block stays an example, and titles, reference
    style images and images inside a link all work.
    """

    def __init__(self, md, base_dir):
        super().__init__(md)
        self.base_dir = base_dir

    def run(self, root):
        for parent in root.iter():
            for index, child in enumerate(list(parent)):
                if child.tag != 'img':
                    continue
                label = f"Image: {child.get('alt', '')}"
                if parent.tag == 'a':
                    # Already a link, and links do not nest.
                    replacement = etree.Element('span')
                else:
                    replacement = etree.Element('a', {
                        'href': image_link_target(
                            child.get('src', ''), self.base_dir),
                        'style': 'text-decoration:none;',
                    })
                replacement.text = label
                replacement.tail = child.tail
                parent.remove(child)
                parent.insert(index, replacement)
        return root


class ImageLinkExtension(Extension):
    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir

    def extendMarkdown(self, md):
        # After the inline patterns, which is what creates the images.
        md.treeprocessors.register(
            ImageLinkTreeprocessor(md, self.base_dir), 'yamep_images', 14)

# QTextBrowser ignores `a { color }` from the document's stylesheet, and
# setting the palette's link colour does not reach it either - measured, both
# leave the anchor in the default link blue, which is unreadable on the dark
# themes. An inline style on the tag is the one thing it honours, so the
# colour is read out of the stylesheet and written into each link.
CSS_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
LINK_RULE = re.compile(r'(?:^|[};])\s*a\s*\{([^}]*)\}')
COLOR_DECLARATION = re.compile(r'(?:^|;)\s*color\s*:\s*([^;]+)', re.IGNORECASE)


def link_color_from_css(css):
    """The colour a stylesheet gives links, or None if it names none."""
    rule = LINK_RULE.search(CSS_COMMENT.sub('', css))
    if not rule:
        return None
    declaration = COLOR_DECLARATION.search(rule.group(1))
    if not declaration:
        return None
    color = QColor(declaration.group(1).strip())
    return color if color.isValid() else None


ANCHOR_TAG = re.compile(r'<a(\s[^>]*)?>', re.IGNORECASE)


def color_links(html, color):
    """Write `color` into every link, so QTextBrowser actually uses it."""
    if color is None:
        return html

    def paint(match):
        attributes = match.group(1) or ''
        if 'style="' in attributes:
            return match.group(0).replace(
                'style="', f'style="color:{color.name()};', 1)
        return f'<a style="color:{color.name()}"{attributes}>'

    return ANCHOR_TAG.sub(paint, html)

# The copy affordance is a small tile that sits on the code surface itself,
# inset from its corner rather than flush with the edge.
COPY_TILE_SIZE = 24
COPY_ICON_SIZE = 16
COPY_TILE_INSET = 10
COPY_CONFIRM_MS = 1600


def compact_css(css):
    """Tighten a markdown stylesheet for rendering inside QTextBrowser."""
    def tighten(match):
        selector, body = match.group(1), match.group(2)
        if BLOCK_TAGS.search(selector):
            body = EM_MARGIN.sub(
                lambda m: '{}{:g}em'.format(
                    m.group(1), min(float(m.group(2)), MAX_BLOCK_MARGIN_EM)),
                body)
        return f'{selector}{{{body}}}'

    # Comments first: the rule pattern treats everything before a brace as the
    # selector, so a comment above the first rule ends up inside it and Qt
    # then drops that rule. A licence header at the top of the file was
    # enough to lose the code block styling.
    css = CSS_COMMENT.sub('', css)
    return CSS_RULE.sub(tighten, LINE_HEIGHT_DECL.sub('', css))


def code_group_geometry(layout, group):
    """Collapse a run of <pre> text blocks into one code block's geometry."""
    first = layout.blockBoundingRect(group[0])
    last = layout.blockBoundingRect(group[-1])
    code = '\n'.join(block.text() for block in group).rstrip('\n')
    background = group[0].blockFormat().background().color()
    return first.top(), first.right(), last.bottom(), code, background


def blend(color, towards, amount):
    """Mix `color` towards another colour by `amount` (0..1)."""
    return QColor(
        round(color.red() + (towards.red() - color.red()) * amount),
        round(color.green() + (towards.green() - color.green()) * amount),
        round(color.blue() + (towards.blue() - color.blue()) * amount),
    )


def contrasting(color):
    """Black or white, whichever stays readable on `color`."""
    return QColor('#000000') if color.lightness() > 140 else QColor('#ffffff')


def paint_glyph(kind, color, backdrop, size, ratio):
    """
    Draw the copy or confirmation glyph.

    The icon set that ships with the app has no copy symbol, and a character
    like U+29C9 depends on fonts that may not be installed, so the two glyphs
    are drawn directly: two offset sheets for copy, a tick for the confirmation.
    """
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.5)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    unit = size / 16.0

    if kind == 'check':
        path = QPainterPath(QPointF(3.2 * unit, 8.6 * unit))
        path.lineTo(QPointF(6.4 * unit, 11.8 * unit))
        path.lineTo(QPointF(12.8 * unit, 4.6 * unit))
        painter.drawPath(path)
    else:
        # Back sheet first, then the front one filled with the tile colour so
        # it masks the overlap instead of showing crossing outlines.
        painter.drawRoundedRect(
            QRectF(2.2 * unit, 2.2 * unit, 8.4 * unit, 10.4 * unit),
            1.6 * unit, 1.6 * unit)
        painter.setBrush(backdrop)
        painter.drawRoundedRect(
            QRectF(5.4 * unit, 5.4 * unit, 8.4 * unit, 10.4 * unit),
            1.6 * unit, 1.6 * unit)

    painter.end()
    return QIcon(pixmap)


class YamepLite(QWidget):
    """Main application class for the Markdown Editor."""
    AVAILABLE_THEMES = [
        'default', 'dark_theme.qss', 'light_theme.qss', 'blue_theme.qss'
    ]

    def __init__(self, file_to_open=None):
        """Initialize the Markdown Editor application."""
        super().__init__()
        # A file named on the command line, from the desktop entry's %f.
        self._file_to_open = file_to_open
        self.config_manager = ConfigManager("lite")
        self.config = self.config_manager.config
        self.current_file_path = None
        self.settings_dialog = None
        self.initUI()
        self.live_preview.anchorClicked.connect(self.open_image)

    def initUI(self):
        """Set up the UI components and layout."""
        self.setWindowTitle(APP_NAME)
        self.setObjectName(APP_NAME)

        # Restore window geometry. saveGeometry()/restoreGeometry() round-trip
        # the window frame; setGeometry(self.geometry()) loses it, which made
        # the window drift down-right on every start.
        window_state = self.config_manager.get_window_state()
        geometry = self.config_manager.get_window_geometry()
        if window_state:
            self.restoreGeometry(window_state)
        elif geometry:
            self.setGeometry(*geometry)
        else:
            self.setGeometry(100, 100, 1200, 800)

        # Main Splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setLayout(QVBoxLayout())
        self.layout().addWidget(self.main_splitter)

        # Left Panel - Folder Tree
        folder_layout = QVBoxLayout()
        folder_widget = QWidget()
        folder_widget.setLayout(folder_layout)

        # Horizontal layout for folder and refresh buttons
        button_layout = QHBoxLayout()

        # Browse Folder Button
        folder_button = QPushButton('Browse Folder')
        folder_button.clicked.connect(self.browse_folder)
        button_layout.addWidget(folder_button)

        # Refresh Button (Only icon, no label)
        self.refresh_button = QToolButton()
        self.refresh_button.setToolTip("Refresh Folder Tree")
        self.refresh_button.clicked.connect(self.refresh_folder_tree)
        self.refresh_button.setVisible(False)
        button_layout.addWidget(self.refresh_button)

        folder_layout.addLayout(button_layout)

        # File Tree View
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabel('Files and Folders')
        self.file_tree.itemDoubleClicked.connect(self.open_file_in_editor)
        folder_layout.addWidget(self.file_tree)
        self.file_tree.itemExpanded.connect(self.on_item_expanded)
        self.file_tree.itemCollapsed.connect(self.save_expanded_state)

        # Action Buttons
        buttons = [
            ('New File', self.create_new_file),
            ('Delete File', self.delete_file),
            ('Save', self.save_file),
            ('Save As', self.save_file_as),
            ('Settings', self.open_settings_window)
        ]
        for text, callback in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            folder_layout.addWidget(btn)

        self.main_splitter.addWidget(folder_widget)

        # Splitter for Editor and Preview
        self.editor_preview_splitter = QSplitter(Qt.Orientation.Vertical)

        # Markdown Editor Panel with Tabs
        self.editor_tabs = QTabWidget()
        editor_tab = QWidget()
        editor_layout = QVBoxLayout()
        editor_tab.setLayout(editor_layout)

        self.editor = QTextEdit()
        # The file is plain text: formatting pasted from a web page would only
        # show here, and images would come out as U+FFFC.
        self.editor.setAcceptRichText(False)
        editor_layout.addWidget(self.editor)
        self.editor_scrollbar = self.editor.verticalScrollBar()

        # IDE Buttons for Markdown Formatting
        ide_buttons_layout = QHBoxLayout()

        self.button_icons = {
            'bold_button': 'format_bold_24dp',
            'italics_button': 'format_italic_24dp',
            'code_button': 'code_24dp',
            'fenced_code_button': 'data_object_24dp',
            'quote_button': 'format_quote_24dp',
            'link_button': 'link_24dp',
            'image_button': 'image_24dp',
            'unordered_list_button': 'format_list_bulleted_24dp',
            'ordered_list_button': 'format_list_numbered_24dp',
            'table_button': 'table_rows_24dp',
            'task_list_button': 'checklist_24dp',
            'footnote_button': 'file_present_24dp',
            'horizontal_rule_button': 'horizontal_rule_24dp',
            'superscript_button': 'superscript_24dp',
            'subscript_button': 'subscript_24dp',
            'refresh_button': 'sync_24dp',
        }

        # Create formatting buttons
        buttons = [
            ('bold_button', "Bold", self.make_bold),
            ('italics_button', "Italic", self.make_italics),
            ('code_button', "Code", self.make_code),
            ('fenced_code_button', "Fenced Code", self.make_fenced_code),
            ('quote_button', "Quote", self.make_quote),
            ('link_button', "Insert Link", self.make_link),
            ('image_button', "Insert Image", self.make_image),
            ('unordered_list_button', "Unordered List",
             self.make_unordered_list),
            ('ordered_list_button', "Ordered List", self.make_ordered_list),
            ('table_button', "Table", self.make_table),
            ('task_list_button', "Task List", self.make_task_list),
            ('footnote_button', "Footnote", self.make_footnote),
            ('horizontal_rule_button', "Horizontal Rule",
             self.make_horizontal_rule),
            ('superscript_button', "Superscript", self.make_superscript),
            ('subscript_button', "Subscript", self.make_subscript)
        ]

        for btn_name, tooltip, callback in buttons:
            btn = QToolButton()
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            setattr(self, btn_name, btn)
            ide_buttons_layout.addWidget(btn)

        # Header Dropdown
        header_dropdown = QComboBox()
        header_dropdown.addItems([
            'Header 1', 'Header 2', 'Header 3',
            'Header 4', 'Header 5', 'Header 6'
        ])
        header_dropdown.setToolTip("Headers")
        header_dropdown.activated.connect(self.make_header)
        ide_buttons_layout.addWidget(header_dropdown)

        editor_layout.addLayout(ide_buttons_layout)
        self.editor_tabs.addTab(editor_tab, 'Untitled')

        # Preview Panel using QTabWidget
        self.preview_tabs = QTabWidget()
        live_preview_tab = QWidget()
        live_preview_layout = QVBoxLayout()
        live_preview_tab.setLayout(live_preview_layout)
        self.live_preview = QTextBrowser()
        # Never let the browser follow a link itself: setSource() would replace
        # the rendered document with the raw target file, which for an image
        # means the preview fills up with binary data. anchorClicked does it.
        self.live_preview.setOpenLinks(False)
        self.preview_scrollbar = self.live_preview.verticalScrollBar()
        self.setup_code_copy_buttons()
        live_preview_layout.addWidget(self.live_preview)
        self.preview_tabs.addTab(live_preview_tab, 'Live Preview')

        self.editor_preview_splitter.addWidget(self.editor_tabs)
        self.editor_preview_splitter.addWidget(self.preview_tabs)
        self.editor_preview_splitter.setStretchFactor(0, 1)
        self.editor_preview_splitter.setStretchFactor(1, 1)
        self.main_splitter.addWidget(self.editor_preview_splitter)

        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setCollapsible(0, True)
        self.main_splitter.setCollapsible(1, False)

        orientation = self.config_manager.get_value(
            'editor_preview_orientation', 'vertical'
        )
        self.editor_preview_splitter.setOrientation(
            Qt.Horizontal if orientation == 'horizontal' else Qt.Vertical
        )

        # Restore splitter states
        main_splitter_state = self.config_manager.get_splitter_state(
            'main_splitter'
        )
        if main_splitter_state:
            self.main_splitter.restoreState(main_splitter_state)
        else:
            total_width = self.width()
            folder_width = int(total_width * 0.2)
            self.main_splitter.setSizes(
                [folder_width, total_width - folder_width])

        editor_preview_splitter_state = self.config_manager.get_splitter_state(
            'editor_preview_splitter')
        if editor_preview_splitter_state:
            self.editor_preview_splitter.restoreState(
                editor_preview_splitter_state)

        # Setup preview update timer
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.update_preview)
        # Atomic saves, and changes other programs make to the open file.
        # Lite has no status bar, so notices appear beside the file tab.
        self.file_guard = DocumentFileGuard(self, self.editor)
        # Source line anchors of the rendered preview, rebuilt per render.
        self.preview_anchors = [(0, 0.0)]
        self.notice_label = QLabel()
        self.notice_label.setContentsMargins(8, 0, 8, 0)
        self.editor_tabs.setCornerWidget(self.notice_label, Qt.TopRightCorner)
        self.notice_label.hide()
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.notice_label.hide)
        self.file_guard.notice.connect(self.show_notice)

        self.editor.textChanged.connect(self.schedule_preview_update)
        self.editor.textChanged.connect(self.update_window_title)
        self.editor.document().modificationChanged.connect(
            self.on_modification_changed
        )

        # Set Window Icon
        icon = QIcon.fromTheme('yamep')
        if not icon.isNull():
            self.setWindowIcon(icon)
        else:
            icon_data = importlib.resources.read_binary(
                'yamep.core.resources',
                'io.github.itstomsh.yamep.lite.png')
            pixmap = QPixmap()
            pixmap.loadFromData(icon_data)
            icon = QIcon(pixmap)
            self.setWindowIcon(icon)

        # Restore last working folder
        last_folder = self.config_manager.get_value('last_working_folder', '')
        if last_folder:
            self.populate_file_tree(last_folder)
            self.refresh_button.setVisible(True)
        else:
            self.refresh_button.setVisible(False)

        # Open last opened file
        if self._file_to_open and not os.path.exists(self._file_to_open):
            # A new note, as with any editor: created by the first save.
            self.current_file_path = os.path.abspath(self._file_to_open)
            self.file_guard.track(self.current_file_path)
            self.editor_tabs.setTabText(
                0, os.path.basename(self.current_file_path))
            self.update_window_title()
        else:
            initial_file = self._file_to_open or self.config_manager.get_value(
                'last_opened_file', '')
            if initial_file and os.path.isfile(initial_file):
                self.open_file_in_editor(
                    file_path=os.path.abspath(initial_file))

        # Apply theme. 'default' is kept as-is: rewriting it to a concrete
        # theme here meant the app started up in a different look than the one
        # the user last saw, while the config still said 'default'.
        self.current_theme = self.config_manager.get_value(
            'current_theme', 'dark_theme.qss')
        if self.current_theme not in self.AVAILABLE_THEMES:
            self.current_theme = 'dark_theme.qss'
        logging.info(f"Theme: {self.current_theme}")

        self.apply_theme()
        self.update_icon_suffix()
        self.update_icons()

        # Set font size
        font = self.font()
        font.setPointSize(14)
        self.setFont(font)
        self.update_preview()

        # Scrollbar synchronization
        self.syncing_scrollbars = False
        self.editor_scrollbar.valueChanged.connect(self.sync_editor_to_preview)
        self.preview_scrollbar.valueChanged.connect(
            self.sync_preview_to_editor)

        # Keyboard shortcuts
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.save_file)
        save_as_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        save_as_shortcut.activated.connect(self.save_file_as)
        new_file_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        new_file_shortcut.activated.connect(self.create_new_file)

        self.editor.cursorPositionChanged.connect(
            self.ensure_cursor_visibility)

    def is_system_dark_mode(self):
        """Check if system is in dark mode."""
        palette = QApplication.palette()
        base_color = palette.color(QPalette.ColorRole.Base)
        text_color = palette.color(QPalette.ColorRole.Text)
        return base_color.value() < text_color.value()

    def update_icon_suffix(self):
        """Update the icon suffix based on the current theme."""
        if self.current_theme == 'default':
            # Follow the system palette rather than always picking dark icons.
            self.icon_suffix = (
                'FFFFFF' if self.is_system_dark_mode() else '5F6368'
            )
        else:
            self.icon_suffix = (
                '5F6368' if 'light' in self.current_theme else 'FFFFFF'
            )

    def update_icons(self):
        """Update the icons of the buttons based on the current theme."""
        for button_name, icon_base in self.button_icons.items():
            icon_filename = f'{icon_base}_{self.icon_suffix}.png'
            try:
                with importlib.resources.path(
                    'yamep.core.resources.icons', icon_filename
                ) as icon_path:
                    icon = QIcon(str(icon_path))
                    button = getattr(self, button_name)
                    button.setIcon(icon)
            except FileNotFoundError:
                print(f"Icon not found: {icon_filename}")

    def ensure_cursor_visibility(self):
        """Ensure cursor is visible when text is being written."""
        # cursorRect() is in viewport coordinates, so adding its top() to the
        # scrollbar value scrolled by the wrong amount in both directions.
        self.editor.ensureCursorVisible()

    def open_image(self, url):
        """
        Handle a link clicked in the preview.

        Images open in a viewer dialog; everything else is handed to the
        desktop. The widget does no navigation of its own, so the rendered
        document stays on screen either way.
        """
        if url.toString().startswith('#'):
            # A footnote or a heading in this same note.
            self.live_preview.scrollToAnchor(url.fragment())
            return

        # Relative links are relative to the note, not to the working folder.
        url = self.live_preview.document().baseUrl().resolved(url)

        # Only local images have a viewer; the desktop handles the rest.
        image_path = url.toLocalFile()
        if not image_path.lower().endswith(IMAGE_EXTENSIONS):
            open_external(url)
            return

        # Check if the file actually exists on disk
        if not os.path.isfile(image_path):
            QMessageBox.warning(
                self, "Error", f"Image not found: {image_path}"
            )
            return

        # Temporarily block the preview timer signals, so we don't update the preview behind the dialog
        try:
            self.preview_timer.blockSignals(True)

            # Create a dialog to display the image
            image_dialog = QDialog(self)
            image_dialog.setWindowTitle(
                f"Image Viewer - {os.path.basename(image_path)}"
            )
            layout = QVBoxLayout(image_dialog)
            image_label = QLabel()
            image_label.setScaledContents(True)
            layout.addWidget(image_label)

            main_width = self.width()
            main_height = self.height()
            dialog_width = int(main_width * 0.5)
            dialog_height = int(main_height * 0.5)

            # If it's a GIF, use QMovie; otherwise load as QPixmap
            if image_path.lower().endswith(".gif"):
                gif = QMovie(image_path)
                if gif.isValid():
                    image_label.setMovie(gif)
                    gif.start()
                    gif_width = gif.frameRect().width()
                    gif_height = gif.frameRect().height()
                    dialog_width = min(dialog_width, gif_width)
                    dialog_height = min(dialog_height, gif_height)
                else:
                    QMessageBox.warning(
                        self, "Error", f"Failed to load GIF: {image_path}"
                    )
                    return
            else:
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    QMessageBox.warning(
                        self, "Error", f"Failed to load image: {image_path}"
                    )
                    return
                image_width = pixmap.width()
                image_height = pixmap.height()
                dialog_width = min(dialog_width, image_width)
                dialog_height = min(dialog_height, image_height)
                scaled_pixmap = pixmap.scaled(
                    dialog_width, dialog_height,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                image_label.setPixmap(scaled_pixmap)

            image_dialog.setLayout(layout)
            image_dialog.resize(dialog_width, dialog_height)
            image_dialog.setMinimumSize(200, 150)

            # Launch the dialog modally
            image_dialog.exec_()

        finally:
            # Important to unblock signals so the preview can resume updating
            self.preview_timer.blockSignals(False)

    def schedule_preview_update(self):
        """Schedule the update of the preview with debounce."""
        self.preview_timer.start(300)

    def sync_editor_to_preview(self, _value):
        """
        Put the source line at the top of the editor at the top of the preview.

        By line rather than by ratio: a heading or a code block renders taller
        than its line in the editor, and a ratio drifts further apart the
        longer the note gets.
        """
        if self.syncing_scrollbars:
            return
        self.syncing_scrollbars = True
        try:
            line = editor_top_line(self.editor)
            self.preview_scrollbar.setValue(
                round(anchor_y_for_line(self.preview_anchors, line)))
        finally:
            self.syncing_scrollbars = False

    def sync_preview_to_editor(self, value):
        """Put the source line at the top of the preview at the top of the editor."""
        if self.syncing_scrollbars:
            return
        self.syncing_scrollbars = True
        try:
            scroll_editor_to_line(
                self.editor, anchor_line_for_y(self.preview_anchors, value))
        finally:
            self.syncing_scrollbars = False

    def apply_theme(self):
        """Apply the current theme, update icons and preview."""
        if self.current_theme == 'default':
            # No stylesheet of our own: follow the system palette.
            self.setStyleSheet('')
        else:
            self.setStyleSheet(load_theme(self.current_theme))

        self.update_icon_suffix()
        self.update_icons()
        self.update_preview()

    def toggle_theme(self):
        """Toggle between available themes."""
        try:
            current_index = self.AVAILABLE_THEMES.index(self.current_theme)
        except ValueError:
            current_index = 0
        next_index = (current_index + 1) % len(self.AVAILABLE_THEMES)
        self.current_theme = self.AVAILABLE_THEMES[next_index]
        self.config_manager.set_value('current_theme', self.current_theme)
        self.config_manager.save()
        self.apply_theme()

    def toggle_look(self):
        """Toggle orientation of editor and preview panels."""
        if self.editor_preview_splitter.orientation() == Qt.Vertical:
            self.editor_preview_splitter.setOrientation(Qt.Horizontal)
            orientation = 'horizontal'
        else:
            self.editor_preview_splitter.setOrientation(Qt.Vertical)
            orientation = 'vertical'

        self.config_manager.set_value(
            'editor_preview_orientation', orientation)
        self.config_manager.save_splitter_state(
            'editor_preview_splitter',
            self.editor_preview_splitter.saveState()
        )
        self.config_manager.save()

    def update_preview(self):
        """Update the live preview with current markdown text."""
        if self.preview_timer.signalsBlocked():
            return
        editor_scroll_position = self.editor_scrollbar.value()
        preview_scroll_position = self.preview_scrollbar.value()

        markdown_text = add_line_markers(
            document_text(self.editor), ANCHOR_MARKER)
        base_dir = (os.path.dirname(self.current_file_path)
                    if self.current_file_path else os.getcwd())

        html = markdown.markdown(
            markdown_text,
            extensions=[
                'markdown.extensions.extra',
                'markdown.extensions.nl2br',
                'markdown.extensions.tables',
                'pymdownx.superfences',
                'pymdownx.tilde',
                'pymdownx.caret',
                TasklistExtension(),
                ImageLinkExtension(base_dir),
                'markdown.extensions.sane_lists',
                # Ids on headings, so that [see](#setup) has somewhere to go.
                'markdown.extensions.toc',
            ],
        )

        if self.current_theme == 'default':
            css_file = (
                'markdown_style_dark.css' if self.is_system_dark_mode()
                else 'markdown_style_light.css'
            )
        else:
            theme_css_mapping = {
                'dark_theme.qss': 'markdown_style_dark.css',
                'light_theme.qss': 'markdown_style_light.css',
                'blue_theme.qss': 'markdown_style_blue.css',
            }
            css_file = theme_css_mapping.get(
                self.current_theme, 'markdown_style.css')

        try:
            css = importlib.resources.read_text(
                'yamep.core.resources.themes', css_file)
        except FileNotFoundError:
            css = ''

        html = color_links(html, link_color_from_css(css))

        html_with_css = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>{compact_css(css)}</style>
        </head>
        <body>
            {html}
        </body>
        </html>
        """

        base_url = QUrl.fromLocalFile(
            os.path.dirname(self.current_file_path) + '/'
        ) if self.current_file_path else QUrl.fromLocalFile(os.getcwd() + '/')

        self.live_preview.document().setBaseUrl(base_url)
        self.live_preview.setHtml(html_with_css)
        self.preview_anchors = document_line_anchors(
            self.live_preview.document())

        self.editor_scrollbar.setValue(editor_scroll_position)
        self.preview_scrollbar.setValue(preview_scroll_position)
        self.rebuild_code_copy_buttons()

    def setup_code_copy_buttons(self):
        """Prepare the copy tiles that float over the preview's code blocks."""
        self.code_copy_buttons = []
        self.preview_scrollbar.valueChanged.connect(
            self.position_code_copy_buttons)
        self.live_preview.viewport().installEventFilter(self)

        # Measuring is deferred: an event filter sees the resize before the
        # widget itself does, so the text has not been rewrapped yet. The
        # delay also coalesces the stream of resizes from a splitter drag.
        self.code_geometry_timer = QTimer(self)
        self.code_geometry_timer.setSingleShot(True)
        self.code_geometry_timer.setInterval(50)
        self.code_geometry_timer.timeout.connect(
            self.refresh_code_copy_geometry)

    def eventFilter(self, watched, event):
        """Keep the copy tiles with their code blocks when the preview is resized."""
        if watched is self.live_preview.viewport():
            if event.type() == QEvent.Resize:
                # A change in width rewraps the text, so the blocks end up
                # somewhere else entirely: measure again, once the reflow has
                # actually happened, rather than move the tiles by stale
                # numbers.
                self.code_geometry_timer.start()
            elif event.type() == QEvent.MouseButtonRelease:
                self.toggle_task_at(event.position().toPoint())
        return super().eventFilter(watched, event)

    def task_line_for_block(self, block):
        """
        The source line a rendered task came from.

        Found by counting rather than by anchor: the checkboxes in the preview
        and the task lines in the text come out in the same order, while a
        nested item is indented and indented lines carry no anchor, since they
        might be code. Returns None if the two counts disagree, which means
        the preview is out of step and guessing would edit the wrong line.
        """
        rendered = []
        ticked = []
        candidate = self.live_preview.document().begin()
        while candidate.isValid():
            text = candidate.text().lstrip()
            if text.startswith(('☐', '☑')):
                rendered.append(candidate.position())
                ticked.append(text.startswith('☑'))
            candidate = candidate.next()
        source = document_text(self.editor)
        lines = task_lines(source)
        if (len(rendered) != len(lines) or block.position() not in rendered
                or ticked != task_states(source)):
            return None
        return lines[rendered.index(block.position())]

    def toggle_task_at(self, position):
        """Tick the task whose checkbox was clicked in the preview."""
        if self.live_preview.textCursor().hasSelection():
            return
        cursor = self.live_preview.cursorForPosition(position)
        block = cursor.block()
        rendered = block.text()
        # The checkbox is the first character of the item, so only a click on
        # it counts; clicking the text of a task does nothing.
        if cursor.positionInBlock() > 1 or not rendered.startswith(('☐', '☑')):
            return
        line = self.task_line_for_block(block)
        if line is None:
            return
        document = self.editor.document()
        if not 0 <= line < document.blockCount():
            return
        source = document.findBlockByNumber(line)
        updated = set_task_checked(source.text(), rendered.startswith('☐'))
        # The preview can be a render behind: only touch a line that really
        # still carries a task marker.
        if updated is None or updated == source.text():
            return
        edit = QTextCursor(source)
        edit.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        edit.insertText(updated)

    def refresh_code_copy_geometry(self):
        """Re-measure what moved when the preview reflowed."""
        # Rewrapping moves the anchors as well as the code blocks.
        self.preview_anchors = document_line_anchors(
            self.live_preview.document())
        ranges = [r for r in self.code_block_ranges() if r[3].strip()]
        if len(ranges) != len(self.code_copy_buttons):
            # The document itself changed: start from scratch.
            self.rebuild_code_copy_buttons()
            return
        self.code_copy_buttons = [
            (button, top, right, bottom)
            for (button, *_), (top, right, bottom, _text, _background)
            in zip(self.code_copy_buttons, ranges)
        ]
        self.position_code_copy_buttons()

    def code_block_ranges(self):
        """
        Yield the geometry of every code block in the preview.

        Qt has no notion of <pre> once the HTML is parsed, but it marks the
        text blocks that came from one with nonBreakableLines(); a code block
        is a run of consecutive such blocks.
        """
        document = self.live_preview.document()
        layout = document.documentLayout()
        group = []
        block = document.begin()
        while block.isValid():
            if block.blockFormat().nonBreakableLines():
                group.append(block)
            elif group:
                yield code_group_geometry(layout, group)
                group = []
            block = block.next()
        if group:
            yield code_group_geometry(layout, group)

    def style_copy_tile(self, button, background):
        """
        Dress a copy tile so it reads as part of the code block it sits on.

        The tile is tinted from the block's own background rather than the
        toolbar palette, so it stays legible on every theme, and the app-wide
        QToolButton rules are overridden to keep it borderless.
        """
        if not background.isValid() or background.alpha() == 0:
            background = self.live_preview.palette().base().color()
        ink = contrasting(background)
        tile = blend(background, ink, 0.16)
        hover = blend(background, ink, 0.30)

        ratio = self.devicePixelRatioF()
        button.copy_icon = paint_glyph(
            'copy', ink, tile, COPY_ICON_SIZE, ratio)
        button.done_icon = paint_glyph(
            'check', ink, hover, COPY_ICON_SIZE, ratio)
        button.setIcon(button.copy_icon)
        button.setIconSize(QSize(COPY_ICON_SIZE, COPY_ICON_SIZE))
        button.setStyleSheet(f"""
            QToolButton {{
                background-color: {tile.name()};
                border: none;
                border-radius: 5px;
                padding: 0px;
            }}
            QToolButton:hover {{ background-color: {hover.name()}; }}
        """)

    def rebuild_code_copy_buttons(self):
        """Recreate one copy tile per code block after a re-render."""
        for button, _top, _right, _bottom in self.code_copy_buttons:
            # Hide before scheduling: deferred deletion only runs once the
            # event loop regains control, and a re-render happens on every
            # pause in typing.
            button.hide()
            button.deleteLater()
        self.code_copy_buttons = []

        for top, right, bottom, text, background in self.code_block_ranges():
            if not text.strip():
                continue
            button = QToolButton(self.live_preview.viewport())
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip('Copy code')
            button.setFixedSize(COPY_TILE_SIZE, COPY_TILE_SIZE)
            self.style_copy_tile(button, background)
            button.clicked.connect(
                lambda _checked=False, code=text, btn=button:
                    self.copy_code_block(code, btn))
            self.code_copy_buttons.append((button, top, right, bottom))

        self.position_code_copy_buttons()

    def position_code_copy_buttons(self):
        """
        Inset each tile into the top right corner of its code block.

        The tile slides down a long listing rather than scrolling out of
        reach, and hides once its block leaves the viewport.
        """
        viewport = self.live_preview.viewport()
        offset = self.preview_scrollbar.value()

        for button, top, right, bottom in self.code_copy_buttons:
            if bottom - offset < 0 or top - offset > viewport.height():
                button.hide()
                continue
            highest = top - offset + COPY_TILE_INSET
            lowest = bottom - offset - button.height() - COPY_TILE_INSET
            y = max(highest, COPY_TILE_INSET)
            y = min(y, lowest) if lowest >= highest else highest
            x = min(right, viewport.width()) - button.width() - COPY_TILE_INSET
            button.move(int(x), int(y))
            button.show()

    def copy_code_block(self, code, button):
        """Put a code block on the clipboard and confirm it on the tile."""
        QApplication.clipboard().setText(code)
        button.setIcon(button.done_icon)
        QTimer.singleShot(
            COPY_CONFIRM_MS, lambda: self.reset_copy_button(button))

    def reset_copy_button(self, button):
        """Restore the glyph unless a re-render replaced the tile first."""
        try:
            button.setIcon(button.copy_icon)
        except RuntimeError:
            pass

    def browse_folder(self):
        """Open dialog to select folder and populate file tree."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.populate_file_tree(folder)
            self.config_manager.set_value('last_working_folder', folder)
            self.config_manager.save()
            self.refresh_button.setVisible(True)

    def refresh_folder_tree(self):
        """Manually refresh the folder tree."""
        last_folder = self.config_manager.get_value('last_working_folder', '')
        if last_folder:
            self.populate_file_tree(last_folder)

    def populate_file_tree(self, folder):
        """Populate file tree with contents of selected folder."""
        expanded_items = set(self.config_manager.get_list('expanded_items'))
        self.file_tree.clear()

        root_item = QTreeWidgetItem(self.file_tree, [os.path.basename(folder)])
        root_item.setData(0, Qt.UserRole, folder)
        self.add_items(root_item, folder)
        root_item.setExpanded(True)

        self.restore_expanded_items(expanded_items)

    def add_items(self, parent_item, path):
        """
        List one folder in the file tree: its sub-folders and Markdown files.

        Sub-folders are filled in only when they are opened. Walking the whole
        tree up front froze the window for half a minute on a home folder,
        and went on through symlinks into folders outside it, such as /run.
        """
        try:
            item_names = sorted(os.listdir(path))
        except OSError as e:
            logging.warning(f"Cannot list {path}: {e}")
            return

        for item_name in item_names:
            item_path = os.path.join(path, item_name)
            if os.path.isdir(item_path):
                item = QTreeWidgetItem(parent_item, [item_name])
                item.setData(0, Qt.UserRole, item_path)
                # Shown as expandable until opening it shows otherwise.
                item.setData(0, UNLISTED_ROLE, True)
                item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            elif item_name.lower().endswith('.md'):
                item = QTreeWidgetItem(parent_item, [item_name])
                item.setData(0, Qt.UserRole, item_path)

    def list_folder_item(self, item):
        """Fill in a folder of the tree the first time it is opened."""
        if not item.data(0, UNLISTED_ROLE):
            return
        item.setData(0, UNLISTED_ROLE, False)
        self.add_items(item, item.data(0, Qt.UserRole))
        item.setChildIndicatorPolicy(
            QTreeWidgetItem.DontShowIndicatorWhenChildless)

    def on_item_expanded(self, item):
        self.list_folder_item(item)
        self.save_expanded_state()

    def get_expanded_items(self):
        """Get expanded state of all items in file tree."""
        expanded_items = set()

        def traverse_items(item):
            if item.isExpanded():
                expanded_items.add(item.data(0, Qt.UserRole))
            for i in range(item.childCount()):
                traverse_items(item.child(i))

        root_item = self.file_tree.topLevelItem(0)
        if root_item:
            traverse_items(root_item)

        return expanded_items

    def restore_expanded_items(self, expanded_items):
        """Restore expanded state of items in file tree."""
        def traverse_and_restore(item):
            if item.data(0, Qt.UserRole) in expanded_items:
                # Listed first, so that its own open folders are found.
                self.list_folder_item(item)
                item.setExpanded(True)
            for i in range(item.childCount()):
                traverse_and_restore(item.child(i))

        root_item = self.file_tree.topLevelItem(0)
        if root_item:
            traverse_and_restore(root_item)

    def save_expanded_state(self):
        """Save expanded state of folder tree to config file."""
        expanded_items = self.get_expanded_items()
        self.config_manager.set_value('expanded_items', list(expanded_items))
        self.config_manager.save()

    def current_working_folder(self):
        """The folder shown as the root of the file tree."""
        root_item = self.file_tree.topLevelItem(0)
        if root_item:
            return root_item.data(0, Qt.UserRole)
        return self.config_manager.get_value('last_working_folder', '')

    def show_notice(self, message, timeout=4000):
        """Show a short message beside the file tab, then clear it."""
        self.notice_label.setText(message)
        self.notice_label.show()
        self.notice_timer.start(timeout)

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

    def create_new_file(self):
        """Create new markdown file in selected directory."""
        current_item = self.file_tree.currentItem()
        if current_item:
            current_path = current_item.data(0, Qt.UserRole)
            initial_dir = (
                current_path if os.path.isdir(current_path)
                else os.path.dirname(current_path))
        else:
            root_item = self.file_tree.topLevelItem(0)
            if root_item:
                initial_dir = root_item.data(0, Qt.UserRole)
            else:
                QMessageBox.warning(
                    self, "Warning",
                    "No working folder is set. Please select a folder."
                )
                return

        file_name, _ = QFileDialog.getSaveFileName(
            self, "New File", initial_dir, "Markdown Files (*.md)"
        )
        file_name = file_name and markdown_save_path(self, file_name)
        if file_name:
            if not self.confirm_discard_changes():
                return
            try:
                signature = atomic_write_text(file_name, '')
                # Refresh the tree at its existing root: re-rooting it at the
                # new file's folder silently changed the working folder.
                self.populate_file_tree(
                    self.current_working_folder() or initial_dir)
                self.current_file_path = file_name
                self.editor.setPlainText('')
                self.editor_tabs.setTabText(0, os.path.basename(file_name))
                self.update_window_title()
                self.editor.document().setModified(False)
                self.file_guard.track(file_name, signature)
                self.config_manager.set_value('last_opened_file', file_name)
                self.config_manager.save()
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", f"Failed to create file: {e}")

    def delete_file(self):
        """Delete selected file from file system."""
        current_item = self.file_tree.currentItem()
        if current_item:
            file_path = current_item.data(0, Qt.UserRole)
            if os.path.isfile(file_path):
                reply = QMessageBox.question(
                    self, "Delete File",
                    f"Are you sure you want to delete {file_path}?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    try:
                        os.remove(file_path)
                        parent_item = (
                            current_item.parent() or
                            self.file_tree.invisibleRootItem()
                        )
                        parent_item.removeChild(current_item)

                        if self.current_file_path == file_path:
                            self.file_guard.forget()
                            self.current_file_path = None
                            self.editor.setPlainText('')
                            self.editor_tabs.setTabText(0, 'Untitled')
                            self.update_window_title()
                            self.editor.document().setModified(False)
                            if self.config_manager.get_value(
                                'last_opened_file') == file_path:
                                self.config_manager.set_value(
                                    'last_opened_file', None)
                                self.config_manager.save()
                    except Exception as e:
                        QMessageBox.warning(
                            self, "Error", f"Failed to delete file: {e}")
            else:
                QMessageBox.warning(
                    self, "Warning", "Please select a file to delete."
                )
        else:
            QMessageBox.warning(
                self, "Warning", "Please select a file to delete."
            )

    def open_file_in_editor(self, item=None, column=0, file_path=None):
        """Open selected file in editor."""
        if not file_path and item:
            file_path = item.data(0, Qt.UserRole)

        if file_path and os.path.isfile(file_path):
            if self.editor.document().isModified():
                reply = QMessageBox.question(
                    self, "Unsaved Changes",
                    "The document has been modified. Do you want to save?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                    QMessageBox.Save
                )
                if reply == QMessageBox.Save:
                    if not self.save_file():
                        return
                elif reply == QMessageBox.Cancel:
                    return
            try:
                content = self.file_guard.open(file_path)
                self.editor.setPlainText(content)
                self.current_file_path = file_path
                self.update_window_title()
                self.config_manager.set_value('last_opened_file', file_path)
                self.config_manager.save()
                self.editor_tabs.setTabText(0, os.path.basename(file_path))
                self.editor.document().setModified(False)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to open file: {e}")
        # A folder needs nothing here: the tree toggles it on a double click
        # by itself, and toggling it again would undo that.

    def update_window_title(self):
        """Update window title to reflect current file and modification."""
        title = APP_NAME + " - "
        if self.current_file_path:
            title += os.path.basename(self.current_file_path)
        else:
            title += "Untitled"
        if self.editor.document().isModified():
            title += '*'
        self.setWindowTitle(title)

    def on_modification_changed(self, modified):
        """Handle changes to document's modification status."""
        self.update_window_title()
        tab_name = (
            os.path.basename(self.current_file_path)
            if self.current_file_path else 'Untitled'
        )
        if modified:
            tab_name += '*'
        self.editor_tabs.setTabText(0, tab_name)

    def save_file(self):
        """Save current file."""
        if self.current_file_path:
            try:
                if not self.file_guard.save(
                        self.current_file_path, document_text(self.editor)):
                    return False
                self.editor.document().setModified(False)
                self.update_window_title()
                return True
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save file: {e}")
                return False
        else:
            return self.save_file_as()

    def save_file_as(self):
        """Save current file with new name."""
        if self.current_file_path:
            initial_dir = os.path.dirname(self.current_file_path)
        else:
            initial_dir = self.config_manager.get_value(
                'last_working_folder', '')
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save File As", initial_dir, "Markdown Files (*.md)"
        )
        file_path = file_path and markdown_save_path(self, file_path)
        if file_path:
            previous_path = self.current_file_path
            self.current_file_path = file_path
            if self.save_file():
                self.editor_tabs.setTabText(0, os.path.basename(file_path))
                self.config_manager.set_value('last_opened_file', file_path)
                self.config_manager.save()
                # Saving changes no text, so nothing else would re-render,
                # and relative links have just moved.
                self.update_preview()
                folder = self.current_working_folder()
                if folder:
                    self.populate_file_tree(folder)
                return True
            # Keep pointing at the file the guard is still watching.
            self.current_file_path = previous_path
        return False

    def closeEvent(self, event):
        """Handle close event, prompting to save if necessary."""
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

        self.save_expanded_state()

        if self.settings_dialog is not None:
            self.settings_dialog.close()
            self.settings_dialog = None

        self.config_manager.save_window_geometry(self.geometry())
        self.config_manager.save_window_state(self.saveGeometry())
        self.config_manager.save_splitter_state(
            'main_splitter',
            self.main_splitter.saveState())
        self.config_manager.save_splitter_state(
            'editor_preview_splitter',
            self.editor_preview_splitter.saveState())
        self.config_manager.save()
        # No change dialogs for a window that is going away.
        self.file_guard.forget()
        event.accept()

    # Markdown formatting methods
    def make_bold(self):
        """Apply bold formatting to selected text."""
        markdown_insert.make_bold(self.editor)

    def make_italics(self):
        """Apply italics formatting to selected text."""
        markdown_insert.make_italics(self.editor)

    def make_code(self):
        """Apply code formatting to selected text."""
        markdown_insert.make_code(self.editor)

    def make_fenced_code(self):
        """Apply fenced code formatting to selected text."""
        markdown_insert.make_fenced_code(self.editor)

    def make_header(self, index):
        """Insert header at current cursor position."""
        markdown_insert.make_header(self.editor, index + 1)

    def make_quote(self):
        """Insert blockquote at current cursor position."""
        markdown_insert.make_quote(self.editor)

    def make_link(self):
        """Insert link syntax at current cursor position."""
        markdown_insert.make_link(self.editor)

    def make_image(self):
        """Insert image syntax at current cursor position."""
        markdown_insert.make_image(self.editor)

    def make_unordered_list(self):
        """Insert unordered list at current cursor position."""
        markdown_insert.make_unordered_list(self.editor)

    def make_ordered_list(self):
        """Insert ordered list at current cursor position."""
        markdown_insert.make_ordered_list(self.editor)

    def make_table(self):
        """Insert table at current cursor position."""
        markdown_insert.make_table(self.editor)

    def make_task_list(self):
        """Insert task list at current cursor position."""
        markdown_insert.make_task_list(self.editor)

    def make_footnote(self):
        """Insert footnote at current cursor position."""
        markdown_insert.make_footnote(self.editor)

    def make_horizontal_rule(self):
        """Insert horizontal rule at current cursor position."""
        markdown_insert.make_horizontal_rule(self.editor)

    def make_superscript(self):
        """Insert superscript text at current cursor position."""
        markdown_insert.make_superscript(self.editor)

    def make_subscript(self):
        """Insert subscript text at current cursor position."""
        markdown_insert.make_subscript(self.editor)

    def open_settings_window(self):
        """Open settings window."""
        if self.settings_dialog is None:
            self.settings_dialog = QDialog(self)
            self.settings_dialog.setWindowTitle('Settings')
            layout = QVBoxLayout(self.settings_dialog)

            about_label = QLabel(
                'yamep - Yet Another Markdown Editor & Preview\n'
                'Version 2.1.1\n\n'
                'Created by tomsh\n'
                'Website: github.com/itstomsh/yamep\n'
                'License: GPL-3.0-or-later')
            layout.addWidget(about_label)

            theme_button = QPushButton('Change Theme')
            theme_button.clicked.connect(self.toggle_theme)
            layout.addWidget(theme_button)

            toggle_look_button = QPushButton('Toggle Look')
            toggle_look_button.clicked.connect(self.toggle_look)
            layout.addWidget(toggle_look_button)

            self.settings_dialog.setLayout(layout)

        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()
