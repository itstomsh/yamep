# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from PySide6.QtGui import QTextCursor


def next_footnote_number(editor):
    """
    Derive the next footnote number from the document itself.

    A module-level counter kept climbing across documents, so a freshly
    opened file started at [^7] instead of [^1].
    """
    used = [int(n) for n in re.findall(r'\[\^(\d+)\]', editor.toPlainText())]
    return max(used) + 1 if used else 1


def insert_syntax(cursor, before, after="", placeholder=""):
    if cursor.hasSelection():
        selected_text = cursor.selectedText()
        cursor.insertText(f"{before}{selected_text}{after}")
    else:
        cursor.insertText(f"{before}{placeholder}{after}")
        if after:
            cursor.movePosition(
                QTextCursor.Left, QTextCursor.MoveAnchor, len(after))
    return cursor


def ensure_blank_line_before_block(cursor):
    block = cursor.block()
    if block.text().strip():
        cursor.movePosition(QTextCursor.EndOfBlock)
        cursor.insertText("\n\n")
    else:
        if block.blockNumber() > 0:
            prev_block = block.previous()
            if prev_block.isValid() and prev_block.text().strip():
                cursor.movePosition(QTextCursor.StartOfBlock)
                cursor.insertText("\n")


def make_bold(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    editor.setTextCursor(insert_syntax(cursor, "**", "**", "Bold"))


def make_italics(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    editor.setTextCursor(insert_syntax(cursor, "*", "*", "italic"))


def make_code(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    editor.setTextCursor(insert_syntax(cursor, "`", "`", "code"))


def make_header(editor, level):
    editor.setFocus()
    levels = ['# ', '## ', '### ', '#### ', '##### ', '###### ']
    header = levels[level - 1]
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.StartOfBlock)
    cursor.insertText(header)
    editor.setTextCursor(cursor)


def make_fenced_code(editor):
    editor.setFocus()
    cursor = editor.textCursor()

    if cursor.hasSelection():
        selected_text = cursor.selectedText()
        cursor.insertText(f"```\n{selected_text}\n```")
    else:
        ensure_blank_line_before_block(cursor)
        cursor.insertText("```\n\n```")
        cursor.movePosition(QTextCursor.Up, QTextCursor.MoveAnchor, 1)

    editor.setTextCursor(cursor)


def make_superscript(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.insertText("X^2^")
    editor.setTextCursor(cursor)


def make_subscript(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.insertText("H~2~O")
    editor.setTextCursor(cursor)


def make_link(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    editor.setTextCursor(insert_syntax(cursor, "[", "](url)", "text"))


def make_image(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.insertText("![](image_path)")
    cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, 13)
    editor.setTextCursor(cursor)


def make_table(editor):
    editor.setFocus()
    cursor = editor.textCursor()

    if cursor.hasSelection():
        cursor.removeSelectedText()
    else:
        ensure_blank_line_before_block(cursor)

    table = (
        "| Header 1 | Header 2 |\n"
        "|----------|----------|\n"
        "| Cell 1   | Cell 2   |"
    )
    cursor.insertText(table + "\n")

    next_block = cursor.block().next()
    if next_block.isValid() and next_block.text().strip() == "":
        cursor.movePosition(QTextCursor.EndOfBlock)
        cursor.movePosition(QTextCursor.NextBlock)
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()

    cursor.movePosition(QTextCursor.Up, QTextCursor.MoveAnchor, 1)
    cursor.movePosition(QTextCursor.EndOfLine)
    editor.setTextCursor(cursor)


def make_unordered_list(editor):
    editor.setFocus()
    cursor = editor.textCursor()

    if cursor.hasSelection():
        cursor.removeSelectedText()
    else:
        ensure_blank_line_before_block(cursor)

    cursor.insertText("- First item\n- Second item\n- Third item\n")
    editor.setTextCursor(cursor)


def make_ordered_list(editor):
    editor.setFocus()
    cursor = editor.textCursor()

    if cursor.hasSelection():
        cursor.removeSelectedText()
    else:
        ensure_blank_line_before_block(cursor)

    cursor.insertText("1. First item\n2. Second item\n3. Third item\n")
    editor.setTextCursor(cursor)


def make_task_list(editor):
    editor.setFocus()
    cursor = editor.textCursor()

    if cursor.hasSelection():
        cursor.removeSelectedText()
    else:
        ensure_blank_line_before_block(cursor)

    cursor.insertText(
        "- [x] Complete initial setup\n- [ ]"
        " Add new features\n- [ ] Test application\n")
    editor.setTextCursor(cursor)


def make_footnote(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    ref = f"[^{next_footnote_number(editor)}]"
    cursor.insertText(ref)

    end_cursor = editor.textCursor()
    end_cursor.movePosition(QTextCursor.End)
    end_cursor.insertText(f"\n{ref}: ")

    editor.setTextCursor(cursor)


def make_quote(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    ensure_blank_line_before_block(cursor)
    cursor.insertText("> ")
    editor.setTextCursor(cursor)


def make_horizontal_rule(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    ensure_blank_line_before_block(cursor)
    cursor.insertText("---\n")
    editor.setTextCursor(cursor)
