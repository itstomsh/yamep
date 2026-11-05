# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import Signal

from yamep.core import markdown_insert
from yamep.core.file_io import document_text


class MarkdownEditor(QTextEdit):
    """
    A Markdown editor widget with formatting actions.
    """
    text_updated = Signal(str)

    def __init__(self):
        super().__init__()
        self.setup_editor()

    def setup_editor(self):
        """
        Set up the editor with default settings.
        """
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setFontPointSize(14)
        self.textChanged.connect(self.emit_text_updated)

    def emit_text_updated(self):
        """
        Emit the current text content when the text changes.
        """
        self.text_updated.emit(document_text(self))

    # The formatting tools are shared with the lite variant, so both edit
    # text the same way. They used to be written out twice and had drifted
    # apart: italics without a selection, for one, inserted "**" here.
    def make_bold(self):
        markdown_insert.make_bold(self)

    def make_italics(self):
        markdown_insert.make_italics(self)

    def make_code(self):
        markdown_insert.make_code(self)

    def make_fenced_code(self):
        markdown_insert.make_fenced_code(self)

    def make_header(self, level):
        markdown_insert.set_header(self, level)

    def make_quote(self):
        markdown_insert.make_quote(self)

    def make_link(self):
        markdown_insert.make_link(self)

    def make_image(self):
        markdown_insert.make_image(self)

    def make_unordered_list(self):
        markdown_insert.make_unordered_list(self)

    def make_ordered_list(self):
        markdown_insert.make_ordered_list(self)

    def make_task_list(self):
        markdown_insert.make_task_list(self)

    def make_horizontal_rule(self):
        markdown_insert.make_horizontal_rule(self)

    def make_superscript(self):
        markdown_insert.make_superscript(self)

    def make_subscript(self):
        markdown_insert.make_subscript(self)

    def make_table(self):
        markdown_insert.make_table(self)

    def make_footnote(self):
        markdown_insert.make_footnote(self)
