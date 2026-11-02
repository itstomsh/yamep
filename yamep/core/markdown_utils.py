# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from markdown import Extension
from markdown.treeprocessors import Treeprocessor

# Matches the "[ ]" / "[x]" marker at the very start of a list item.
TASK_MARKER = re.compile(r'^\s*\[([xX ])\](?:\s+|$)')


def _text_holder(li):
    """
    Return the element whose `.text` holds the start of the list item.

    In a tight list the marker sits directly in <li>; in a loose list
    markdown wraps the content in a <p> first.
    """
    if li.text and li.text.strip():
        return li
    children = list(li)
    if children and children[0].tag == 'p':
        return children[0]
    return li


def _unwrap_leading_paragraph(li, holder):
    """
    Lift a leading <p> wrapper out of `li`, keeping its inline markup.

    A blank line between items makes markdown a "loose" list and wraps every
    item in <p>. The preview stylesheet gives paragraphs a vertical margin, so
    a task list rendered that way is spaced out instead of compact. Dropping
    just the wrapper restores the tight look without touching its content.
    """
    if holder is li or len(li) == 0 or li[0] is not holder:
        return
    li.text = holder.text
    for index, child in enumerate(list(holder)):
        li.insert(index, child)
    li.remove(holder)


# Fenced code, so that scanners can skip what only looks like markdown.
FENCE_OPEN = re.compile(r'^\s*(`{3,}|~{3,})')

CHECKBOX_TAG = re.compile(r'<input type="checkbox"')


def iter_source_lines(text):
    """
    Yield (number, line, inside_fence) for every line of `text`.

    One place decides what counts as fenced code, so the scanners that add
    line anchors and the one that finds task items cannot drift apart.
    """
    fence = None
    for number, line in enumerate(text.split('\n')):
        if fence:
            closing = r'^\s*' + re.escape(fence[0]) + r'{%d,}\s*$' % len(fence)
            if re.match(closing, line):
                fence = None
            yield number, line, True
            continue
        opening = FENCE_OPEN.match(line)
        if opening:
            fence = opening.group(1)
            yield number, line, True
            continue
        yield number, line, False


def task_lines(text):
    """Line numbers of the task items markdown will render as checkboxes."""
    return [number for number, line, in_fence in iter_source_lines(text)
            if not in_fence and TASK_LINE.match(line)]


def tag_task_checkboxes(html, text):
    """
    Write the source line of each task into its rendered checkbox.

    Checkboxes and task lines come out in the same order, so they pair up by
    position. If the two counts disagree the pairing would be guesswork, and
    the tags are left off entirely rather than risk editing the wrong line.
    """
    lines = task_lines(text)
    if len(CHECKBOX_TAG.findall(html)) != len(lines):
        return html
    numbers = iter(lines)
    return CHECKBOX_TAG.sub(
        lambda m: f'{m.group(0)} data-task-line="{next(numbers)}"', html)


# The marker that starts a task item, with the list bullet in front of it.
TASK_LINE = re.compile(r'^(\s*(?:[-*+]|\d+[.)])\s+)\[([xX ])\]')


def set_task_checked(line, checked):
    """
    Return `line` with its task marker ticked or cleared.

    Returns None if the line does not start a task item, which is how a caller
    can tell that a preview it acted on is a render behind the editor.
    """
    match = TASK_LINE.match(line)
    if not match:
        return None
    return f"{match.group(1)}[{'x' if checked else ' '}]{line[match.end():]}"


class TasklistTreeprocessor(Treeprocessor):
    def run(self, root):
        for li in root.iter('li'):
            holder = _text_holder(li)
            match = TASK_MARKER.match(holder.text or '')
            if not match:
                continue
            checkbox = '☑' if match.group(1).lower() == 'x' else '☐'
            # Only rewrite the leading text node: replacing the marker in
            # place keeps inline markup and nested lists intact.
            holder.text = f'{checkbox} ' + (holder.text or '')[match.end():]
            _unwrap_leading_paragraph(li, holder)
            li.set('class', 'task-list-item')

        for parent in root.iter():
            if parent.tag not in ('ul', 'ol'):
                continue
            if any(child.get('class') == 'task-list-item' for child in parent):
                # Qt draws its own bullet in front of the checkbox. It honours
                # list-style-type on the list element, but ignores the same
                # rule written as a CSS class, which is why the stylesheet
                # alone did not help.
                parent.set('style', 'list-style-type:none')
        return root


class TasklistExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(TasklistTreeprocessor(md), 'tasklist', 15)
