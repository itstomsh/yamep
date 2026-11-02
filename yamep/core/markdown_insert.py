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


def prefix_selected_lines(editor, prefix_for):
    """
    Start each selected line with `prefix_for(n)`, as one undoable edit.

    n counts the lines that are not blank. A selection ending at the very
    start of a line does not include that line.
    """
    cursor = editor.textCursor()
    document = editor.document()
    block = document.findBlock(cursor.selectionStart())
    last = document.findBlock(cursor.selectionEnd())
    if last != block and cursor.selectionEnd() == last.position():
        last = last.previous()

    cursor.beginEditBlock()
    count = 0
    while True:
        if block.text().strip():
            edit = QTextCursor(cursor)
            edit.setPosition(block.position())
            edit.insertText(prefix_for(count))
            count += 1
        if block == last:
            break
        block = block.next()
    cursor.endEditBlock()


def bullet_prefix(_index):
    return "- "


def number_prefix(index):
    return f"{index + 1}. "


def task_prefix(_index):
    return "- [ ] "


def collapse_to_selection_end(cursor):
    """Insert after the selection instead of over it."""
    cursor.setPosition(cursor.selectionEnd())


def set_header(editor, level):
    """Make the current line a heading of `level`, whatever it was before."""
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.StartOfBlock)
    existing = re.match(r'#{1,6}\s+', cursor.block().text())
    if existing:
        cursor.movePosition(
            QTextCursor.Right, QTextCursor.KeepAnchor, existing.end())
    cursor.insertText('#' * level + ' ')
    editor.setTextCursor(cursor)


def wrap_or_insert(editor, before, after, sample):
    """Wrap the selection; with none, insert `sample`."""
    editor.setFocus()
    cursor = editor.textCursor()
    if cursor.hasSelection():
        cursor.insertText(f"{before}{cursor.selectedText()}{after}")
    else:
        cursor.insertText(sample)
    editor.setTextCursor(cursor)


def make_image_syntax(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    alt = cursor.selectedText() if cursor.hasSelection() else ""
    cursor.insertText(f"![{alt}](image_path)")
    if not alt:
        cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, 13)
    editor.setTextCursor(cursor)


def insert_footnote(editor, ref):
    editor.setFocus()
    cursor = editor.textCursor()
    collapse_to_selection_end(cursor)
    cursor.insertText(ref)

    end_cursor = editor.textCursor()
    end_cursor.movePosition(QTextCursor.End)
    end_cursor.insertText(f"\n{ref}: ")

    editor.setTextCursor(cursor)


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
    set_header(editor, level)


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
    wrap_or_insert(editor, "^", "^", "X^2^")


def make_subscript(editor):
    wrap_or_insert(editor, "~", "~", "H~2~O")


def make_link(editor):
    editor.setFocus()
    cursor = editor.textCursor()
    editor.setTextCursor(insert_syntax(cursor, "[", "](url)", "text"))


def make_image(editor):
    make_image_syntax(editor)


def make_table(editor):
    editor.setFocus()
    cursor = editor.textCursor()

    # A table has nowhere to put arbitrary text, so it goes below it.
    collapse_to_selection_end(cursor)
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
        prefix_selected_lines(editor, bullet_prefix)
        return
    ensure_blank_line_before_block(cursor)

    cursor.insertText("- First item\n- Second item\n- Third item\n")
    editor.setTextCursor(cursor)


def make_ordered_list(editor):
    editor.setFocus()
    cursor = editor.textCursor()

    if cursor.hasSelection():
        prefix_selected_lines(editor, number_prefix)
        return
    ensure_blank_line_before_block(cursor)

    cursor.insertText("1. First item\n2. Second item\n3. Third item\n")
    editor.setTextCursor(cursor)


def make_task_list(editor):
    editor.setFocus()
    cursor = editor.textCursor()

    if cursor.hasSelection():
        prefix_selected_lines(editor, task_prefix)
        return
    ensure_blank_line_before_block(cursor)

    cursor.insertText(
        "- [x] Complete initial setup\n- [ ]"
        " Add new features\n- [ ] Test application\n")
    editor.setTextCursor(cursor)


def make_footnote(editor):
    insert_footnote(editor, f"[^{next_footnote_number(editor)}]")


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
