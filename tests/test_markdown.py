# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

import markdown
import pytest

from yamep.core.line_anchors import add_line_markers
from yamep.core.markdown_utils import (
    iter_source_lines, tag_task_checkboxes, task_lines,
)

EXTENSIONS = [
    'markdown.extensions.extra', 'markdown.extensions.nl2br',
    'pymdownx.superfences', 'pymdownx.tilde', 'pymdownx.caret',
    'pymdownx.tasklist',
]


def render(text):
    return markdown.markdown(
        text, extensions=EXTENSIONS,
        extension_configs={
            'pymdownx.tasklist': {'clickable_checkbox': True}})


@pytest.mark.parametrize('text', [
    '`a\nb` c\n',
    '<!-- x\n\ny -->\n',
    '<pre>\n\nabc\n</pre>\n',
    '> ```python\n> print(1)\n> ```\n',
    '> ```\n> x\n\nafter\n',
    '- a\n\n    ```\n    x\n    ```\n',
    '```x``` inline\n\nnext\n',
    '    ```\n    x\n\nabc\n',
    '``` not closed\n\nabc\n',
    'Term\n: Def\n',
    'Title\n=====\n',
    'a  \nb\n',
    '# H {#id}\n',
    '[a\nb](u)\n',
    '`one` and `two`\n',
])
def test_markers_do_not_change_the_rendering(text):
    marked = render(add_line_markers(text))
    assert re.sub(r'<span data-line="\d+"></span>', '', marked) == render(text)


def literal_lines(text):
    return [n for n, _line, literal in iter_source_lines(text) if literal]


def test_inline_triple_backticks_do_not_open_a_fence():
    assert literal_lines('```x``` inline\n\nnext') == []


def test_unclosed_fence_is_not_a_fence():
    assert literal_lines('``` open\n\ntext') == []


def test_fence_in_a_quote_ends_with_the_quote():
    assert literal_lines('> ```\n> x\n\nafter') == [0, 1]


@pytest.mark.parametrize('text', [
    '- [ ] a\n- [x] b\n',
    '- [ ] a\n\n> - [ ] q\n',
    '- [ ] a\n\n```x``` inline\n\n- [ ] b\n',
    '- [ ] a\n- [x]nospace\n',
    '- [ ] a\n- [ ]\n',
    '1) [ ] a\n\n- [ ] b\n',
    '    - [ ] code\n\n- [ ] b\n',
    '- [ ] a\n    - [x] nested\n',
    '<!-- - [ ] x -->\n\n- [ ] b\n',
])
def test_task_scan_finds_what_the_renderer_renders(text):
    html = render(text)
    assert html.count('type="checkbox"') == len(task_lines(text))
    assert html.count('data-task-line') == 0
    tagged = tag_task_checkboxes(html, text)
    assert tagged.count('data-task-line') == len(task_lines(text))


def test_disagreeing_ticks_leave_the_boxes_untagged():
    html = render('- [x] a\n')
    assert tag_task_checkboxes(html, '- [ ] a\n') == html
