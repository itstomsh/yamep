# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Source-line anchors for keeping an editor and a rendered preview in step.

Syncing by scroll ratio assumes every source line renders at the same height.
Images, large headings and code blocks break that, and the error piles up down
the document. Instead, the first line of each block is tagged in the rendered
output with the number of the source line it came from, and positions are
translated through those anchors: however tall a block renders, the two views
line up again at the next one.

Line numbers are editor block numbers (0-based), which match `text.split('\n')`.
"""
import re

from PySide6.QtCore import QPoint

from yamep.core.markdown_utils import iter_source_lines

# Two ways to carry a line number into the rendered document. A browser
# keeps any attribute, so the full variant uses a data attribute; Qt's rich
# text drops unknown attributes but preserves anchor names, so the lite
# variant uses those.
SPAN_MARKER = '<span data-line="{}"></span>'
# The zero width space matters: Qt keeps an anchor only if it has a
# character to attach it to, and the marker sits at the end of a line,
# where an empty anchor would simply be dropped.
ANCHOR_MARKER = '<a name="yamep-line-{}">\u200b</a>'
ANCHOR_PREFIX = 'yamep-line-'

# Lines that must never carry a marker: either the marker would change what
# the line means, or the line renders nothing a marker could sit in.
UNMARKABLE = re.compile(r'''^(?:
    \s*$ | \t | \s{4,}                    # blank, indented code
  | \s{0,3}<                              # raw HTML
  | \s{0,3}\[\^?[^\]]+\]:                 # reference and footnote definitions
  | \s{0,3}\*\[[^\]]+\]:                  # abbreviations
  | \s{0,3}([-*_])(?:\s*\1){2,}\s*$       # horizontal rule
  | \s{0,3}(?:=+|-+)\s*$                  # setext heading underline
  | \s{0,3}>\s*$                          # empty blockquote line
)''', re.VERBOSE)

# Lines that start a block even straight after another line.
BLOCK_START = re.compile(r'^\s{0,3}(?:#{1,6}(?:\s|$)|[-*+]\s|\d+[.)]\s|>)')

# Syntax that has to stay last on the line: an ATX heading's closing hashes
# and an attr_list block.
TRAILING_SYNTAX = re.compile(r'(\s+#+|\s*\{[^{}]*\})\s*$')


def add_line_markers(text, marker=SPAN_MARKER):
    """
    Return `text` with an empty <span data-line="N"> ending the first line of
    every block.

    The marker goes at the end of the line because at the start it would stop
    `- item` being a list or `# Title` a heading. Fenced and indented code,
    tables, rules and link definitions are left alone; rendering the result
    and dropping the markers gives exactly the HTML the plain text gives.
    """
    lines = []
    previous_blank = True
    for number, line, in_fence in iter_source_lines(text):
        if in_fence:
            lines.append(line)
            previous_blank = False
            continue

        if (not UNMARKABLE.match(line) and '|' not in line
                and (previous_blank or BLOCK_START.match(line))):
            body = line.rstrip()
            # Trailing spaces stay last: two of them are a hard line break.
            tail = line[len(body):]
            trailing = TRAILING_SYNTAX.search(body)
            cut = trailing.start() if trailing else len(body)
            line = body[:cut] + marker.format(number) + body[cut:] + tail

        lines.append(line)
        previous_blank = not line.strip()
    return '\n'.join(lines)


def document_line_anchors(document):
    """
    Pair every source line anchored in `document` with its position in it.

    Returns [(line, top)] with both columns increasing, which is what the
    interpolation below needs.
    """
    layout = document.documentLayout()
    anchors = [(0, 0.0)]
    block = document.begin()
    while block.isValid():
        top = layout.blockBoundingRect(block).top()
        for text_format in block.textFormats():
            for name in text_format.format.anchorNames():
                if not name.startswith(ANCHOR_PREFIX):
                    continue
                line = int(name[len(ANCHOR_PREFIX):])
                if line > anchors[-1][0] and top >= anchors[-1][1]:
                    anchors.append((line, top))
        block = block.next()
    return anchors


def _interpolate(anchors, value, source, target):
    if not anchors:
        return 0.0
    index = 0
    while index + 1 < len(anchors) and anchors[index + 1][source] <= value:
        index += 1
    low = anchors[index]
    high = anchors[min(index + 1, len(anchors) - 1)]
    if high[source] == low[source]:
        return low[target]
    fraction = (value - low[source]) / (high[source] - low[source])
    return low[target] + min(max(fraction, 0.0), 1.0) * (high[target] - low[target])


def anchor_y_for_line(anchors, line):
    """Where in the rendered document source `line` begins."""
    return _interpolate(anchors, line, 0, 1)


def anchor_line_for_y(anchors, y):
    """Which source line is rendered at `y`."""
    return _interpolate(anchors, y, 1, 0)


def editor_top_line(editor):
    """
    The source line at the top of a QTextEdit's viewport, as a float: the
    fraction is how much of a wrapped line has already scrolled past.
    """
    block = editor.cursorForPosition(QPoint(0, 0)).block()
    rect = editor.document().documentLayout().blockBoundingRect(block)
    if rect.height() <= 0:
        return float(block.blockNumber())
    scrolled = (editor.verticalScrollBar().value() - rect.top()) / rect.height()
    return block.blockNumber() + min(max(scrolled, 0.0), 0.999)


def scroll_editor_to_line(editor, line):
    """Scroll a QTextEdit so that source line `line` (a float) is at the top."""
    document = editor.document()
    number = max(0, min(int(line), document.blockCount() - 1))
    rect = document.documentLayout().blockBoundingRect(
        document.findBlockByNumber(number))
    fraction = min(max(line - number, 0.0), 1.0)
    editor.verticalScrollBar().setValue(
        round(rect.top() + fraction * rect.height()))
