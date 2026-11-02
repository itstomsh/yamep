# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor
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

    def make_bold(self):
        """
        Apply bold formatting to the selected text or insert bold syntax.
        """
        self.setFocus()
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            cursor.insertText(f"**{selected_text}**")
        else:
            cursor.insertText("**Bold**")
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, 2)
            self.setTextCursor(cursor)

    def make_italics(self):
        """
        Apply italics formatting to the selected text or insert italics syntax.
        """
        self.setFocus()
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            cursor.insertText(f"*{selected_text}*")
        else:
            cursor.insertText("**")
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, 1)
            self.setTextCursor(cursor)

    def make_code(self):
        """
        Apply code formatting to the selected text or insert code syntax.
        """
        self.setFocus()
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            cursor.insertText(f"`{selected_text}`")
        else:
            cursor.insertText("``")
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, 1)
            self.setTextCursor(cursor)

    def make_fenced_code(self):
        self.setFocus()
        cursor = self.textCursor()

        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            cursor.insertText(f"```\n{selected_text}\n```")
        else:
            self.ensure_blank_line_before_block(cursor)
            cursor.insertText("```\n\n```")
            cursor.movePosition(QTextCursor.Up, QTextCursor.MoveAnchor, 1)

        self.setTextCursor(cursor)

    def make_header(self, level):
        """
        Insert a header at the current cursor position.
        """
        markdown_insert.set_header(self, level)

    def make_quote(self):
        self.setFocus()
        cursor = self.textCursor()
        self.ensure_blank_line_before_block(cursor)
        cursor.insertText("> ")
        self.setTextCursor(cursor)

    def make_link(self):
        """
        Insert a link syntax at the current cursor position.
        """
        self.setFocus()
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            cursor.insertText(f"[{selected_text}](url)")
        else:
            cursor.insertText("[](url)")
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, 6)
            self.setTextCursor(cursor)

    def make_image(self):
        """
        Insert an image syntax at the current cursor position.
        """
        markdown_insert.make_image_syntax(self)

    def make_unordered_list(self):
        """
        Insert an unordered list at the current cursor position.
        """
        self.setFocus()
        cursor = self.textCursor()

        if cursor.hasSelection():
            markdown_insert.prefix_selected_lines(
                self, markdown_insert.bullet_prefix)
            return
        self.ensure_blank_line_before_block(cursor)

        cursor.insertText("- First item\n- Second item\n- Third item\n")
        self.setTextCursor(cursor)

    def make_ordered_list(self):
        """
        Insert an ordered list at the current cursor position.
        """
        self.setFocus()
        cursor = self.textCursor()

        if cursor.hasSelection():
            markdown_insert.prefix_selected_lines(
                self, markdown_insert.number_prefix)
            return
        self.ensure_blank_line_before_block(cursor)

        cursor.insertText("1. First item\n2. Second item\n3. Third item\n")
        self.setTextCursor(cursor)

    def make_task_list(self):
        """
        Insert a task list at the current cursor position.
        """
        self.setFocus()
        cursor = self.textCursor()

        if cursor.hasSelection():
            markdown_insert.prefix_selected_lines(
                self, markdown_insert.task_prefix)
            return
        self.ensure_blank_line_before_block(cursor)

        cursor.insertText(
            "- [x] Complete initial setup\n- "
            "[ ] Add new features\n- [ ] Test application\n")
        self.setTextCursor(cursor)

    def make_horizontal_rule(self):
        self.setFocus()
        cursor = self.textCursor()
        self.ensure_blank_line_before_block(cursor)
        cursor.insertText("---\n")
        self.setTextCursor(cursor)

    def make_superscript(self):
        """
        Insert superscript text at the current cursor position.
        """
        markdown_insert.wrap_or_insert(self, "^", "^", "X^2^")

    def make_subscript(self):
        """
        Insert subscript text at the current cursor position.
        """
        markdown_insert.wrap_or_insert(self, "~", "~", "H~2~O")

    def make_table(self):
        self.setFocus()
        cursor = self.textCursor()

        # A table has nowhere to put arbitrary text, so it goes below it.
        markdown_insert.collapse_to_selection_end(cursor)
        self.ensure_blank_line_before_block(cursor)

        table = (
            "| Header 1 | Header 2 |\n"
            "|----------|----------|\n"
            "| Cell 1   | Cell 2   |"
        )
        cursor.insertText(table + "\n")

        # Remove accidental empty line after
        next_block = cursor.block().next()
        if next_block.isValid() and next_block.text().strip() == "":
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.movePosition(QTextCursor.NextBlock)
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()

        # Position cursor on first data row
        cursor.movePosition(QTextCursor.Up, QTextCursor.MoveAnchor, 1)
        cursor.movePosition(QTextCursor.EndOfLine)
        self.setTextCursor(cursor)

    def next_footnote_number(self):
        """
        Derive the next footnote number from the document itself. A counter
        held on the widget kept climbing across documents, so a freshly
        opened file started at [^7] instead of [^1].
        """
        used = [int(n) for n in re.findall(r'\[\^(\d+)\]', self.toPlainText())]
        return max(used) + 1 if used else 1

    def make_footnote(self):
        markdown_insert.insert_footnote(
            self, f"[^{self.next_footnote_number()}]")

    def ensure_blank_line_before_block(self, cursor):
        """
        Ensures there's a blank line before the block being inserted.
        Adds one or two newlines as needed.
        """
        block = cursor.block()
        current_line_text = block.text().strip()

        if current_line_text:
            # Current line has text, insert two newlines after it
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText("\n\n")
        else:
            # Already on empty line
            if block.blockNumber() > 0:
                prev_block = block.previous()
                if prev_block.isValid() and prev_block.text().strip():
                    # Line above is not blank → insert one newline
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    cursor.insertText("\n")
