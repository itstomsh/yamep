# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from PySide6.QtGui import QTextCursor

from yamep.core import markdown_insert as lite
from yamep.full.editor import MarkdownEditor


class LiteActions:
    def __init__(self, editor):
        self.editor = editor

    def __getattr__(self, name):
        return lambda *args: getattr(lite, name)(self.editor, *args)


def make(variant, text, start=0, end=None, width=500):
    editor = MarkdownEditor()
    editor.resize(width, 300)
    editor.show()
    editor.setPlainText(text)
    cursor = editor.textCursor()
    cursor.setPosition(start)
    if end is not None:
        cursor.setPosition(end, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)
    return editor, (editor if variant == 'full' else LiteActions(editor))


variants = pytest.mark.parametrize('variant', ['full', 'lite'])


@variants
@pytest.mark.parametrize('action,expected', [
    ('make_unordered_list', '- one\n\n- two\nrest'),
    ('make_ordered_list', '1. one\n\n2. two\nrest'),
    ('make_task_list', '- [ ] one\n\n- [ ] two\nrest'),
])
def test_lists_apply_to_the_selection(qapp, variant, action, expected):
    text = 'one\n\ntwo\nrest'
    editor, actions = make(variant, text, 0, text.index('rest'))
    getattr(actions, action)()
    assert editor.toPlainText() == expected


@variants
def test_list_on_a_selection_is_one_undo(qapp, variant):
    editor, actions = make(variant, 'a\nb', 0, 3)
    actions.make_unordered_list()
    editor.undo()
    assert editor.toPlainText() == 'a\nb'


@variants
def test_table_keeps_the_selected_text(qapp, variant):
    editor, actions = make(variant, 'keep me', 0, 7)
    actions.make_table()
    assert editor.toPlainText().startswith('keep me\n\n| Header 1')


@variants
@pytest.mark.parametrize('action', ['make_footnote'])
def test_footnote_keeps_the_selected_text(qapp, variant, action):
    editor, actions = make(variant, 'keep me', 0, 7)
    getattr(actions, action)()
    assert editor.toPlainText() == 'keep me[^1]\n[^1]: '


@variants
@pytest.mark.parametrize('action,expected', [
    ('make_superscript', '^keep^'),
    ('make_subscript', '~keep~'),
    ('make_image', '![keep](image_path)'),
])
def test_wrapping_tools_keep_the_selection(qapp, variant, action, expected):
    editor, actions = make(variant, 'keep', 0, 4)
    getattr(actions, action)()
    assert editor.toPlainText() == expected


@variants
def test_header_goes_to_the_start_of_a_wrapped_paragraph(qapp, variant):
    editor, actions = make(variant, 'word ' * 200, 600)
    actions.make_header(2)
    assert editor.toPlainText().startswith('## word')


@variants
def test_header_replaces_an_existing_one(qapp, variant):
    editor, actions = make(variant, '# Title')
    actions.make_header(3)
    assert editor.toPlainText() == '### Title'
