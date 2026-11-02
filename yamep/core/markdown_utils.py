# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from markdown import Extension
from markdown.treeprocessors import Treeprocessor

# Matches the "[ ]" / "[x]" marker at the very start of a list item. As in
# pymdownx.tasklist, a marker with nothing after it is not a task yet.
TASK_MARKER = re.compile(r'^\s*\[([xX ])\]\s+(?=\S)')


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


# Block quote markers in front of a line.
QUOTE_PREFIX = r'(?:[ ]{0,3}>[ ]?)*'

# Fenced code, so that scanners can skip what only looks like markdown. A
# backtick fence has no backticks after it: ```x``` is inline code.
FENCE_OPEN = re.compile(
    r'^(' + QUOTE_PREFIX + r')(\s*)(`{3,}(?=[^`]*$)|~{3,})')
LIST_ITEM = re.compile(r'^' + QUOTE_PREFIX + r'\s*(?:[-*+]|\d+\.)\s')

# Raw HTML whose content is not markdown, and what ends it.
RAW_BLOCKS = re.compile(
    r'^\s{0,3}<(!--|pre\b|script\b|style\b|textarea\b)', re.IGNORECASE)
RAW_BLOCK_END = {'!--': '-->', 'pre': '</pre>', 'script': '</script>',
                 'style': '</style>', 'textarea': '</textarea>'}

CHECKBOX_TAG = re.compile(r'<input type="checkbox"[^>]*?(?=/?>)')


def _fence_end(lines, start, prefix, fence):
    """Index of the line closing a fence opened on `start`, or None."""
    closing = re.compile(
        r'^' + QUOTE_PREFIX + r'\s*' + re.escape(fence[0])
        + r'{%d,}\s*$' % len(fence))
    quoted = '>' in prefix
    for index in range(start + 1, len(lines)):
        if closing.match(lines[index]):
            return index
        if quoted and not lines[index].lstrip().startswith('>'):
            # Leaving the quote ends the code block, without a closing line.
            return index - 1
    return None


def _raw_block_end(lines, start, tag):
    end = RAW_BLOCK_END[tag.lower()]
    for index in range(start, len(lines)):
        if end in lines[index].lower():
            return index
    return len(lines) - 1


def iter_source_lines(text):
    """
    Yield (number, line, literal) for every line of `text`.

    `literal` marks what only looks like markdown: fenced and indented code,
    and raw HTML blocks that keep their content. One place decides that, so
    the scanners that add line anchors and the one that finds task items
    cannot drift apart.
    """
    lines = text.split('\n')
    in_list = False
    previous_blank = True
    in_indented_code = False
    index = 0
    while index < len(lines):
        line = lines[index]
        end = None

        fence = FENCE_OPEN.match(line)
        raw = RAW_BLOCKS.match(line)
        # Four spaces make a fence code only outside a list item. An opening
        # that is never closed is not a fence: it renders as plain text.
        if fence and (in_list or len(fence.group(2)) < 4):
            end = _fence_end(lines, index, fence.group(1), fence.group(3))
        elif raw:
            end = _raw_block_end(lines, index, raw.group(1).split()[0])
        if end is not None:
            for number in range(index, end + 1):
                yield number, lines[number], True
            index = end + 1
            previous_blank = False
            continue

        blank = not line.strip()
        indented = line.startswith(('    ', '\t'))
        in_indented_code = (
            indented and not blank and not in_list
            and (previous_blank or in_indented_code))
        if not in_indented_code:
            if LIST_ITEM.match(line):
                in_list = True
            elif not blank and not indented and previous_blank:
                # Unindented text after a blank line ends the list; without
                # the blank line it is a lazy continuation of the last item.
                in_list = False
        yield index, line, in_indented_code
        previous_blank = blank
        index += 1


def task_lines(text):
    """Line numbers of the task items markdown will render as checkboxes."""
    return [number for number, line, literal in iter_source_lines(text)
            if not literal and TASK_LINE.match(line)]


def task_states(text):
    """Ticked or not, for every line of task_lines(), in the same order."""
    source = text.split('\n')
    return [TASK_LINE.match(source[number]).group(2).lower() == 'x'
            for number in task_lines(text)]


def tag_task_checkboxes(html, text):
    """
    Write the source line of each task into its rendered checkbox.

    Checkboxes and task lines come out in the same order, so they pair up by
    position. If the counts or the ticks disagree the pairing would be
    guesswork, and the tags are left off entirely rather than risk editing
    the wrong line.
    """
    lines = task_lines(text)
    boxes = CHECKBOX_TAG.findall(html)
    if len(boxes) != len(lines):
        return html
    if ['checked' in box for box in boxes] != task_states(text):
        return html
    numbers = iter(lines)
    return CHECKBOX_TAG.sub(
        lambda m: f'{m.group(0)} data-task-line="{next(numbers)}"', html)


# The marker that starts a task item, with the list bullet in front of it. It
# has to find the same items the renderers do: python-markdown has no `1)`
# lists, and a marker needs text after it.
TASK_LINE = re.compile(
    r'^(' + QUOTE_PREFIX + r'\s*(?:[-*+]|\d+\.)\s+)\[([xX ])\](?=\s+\S)')


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
