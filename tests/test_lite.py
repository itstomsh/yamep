# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import re

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

import yamep.core.utils as utils
from conftest import pick_file
from yamep.lite.app import YamepLite


@pytest.fixture
def opened(monkeypatch):
    urls = []
    monkeypatch.setattr(
        utils.QDesktopServices, 'openUrl',
        staticmethod(lambda url: urls.append(url.toString()) or True))
    return urls


@pytest.fixture
def window(qapp, dialogs):
    win = YamepLite()
    win.show()
    yield win
    win.editor.document().setModified(False)
    win.close()


def render(window, text):
    window.editor.setPlainText(text)
    window.update_preview()
    return window.live_preview.toPlainText(), window.live_preview.toHtml()


def hrefs(html):
    return re.findall(r'href="([^"]*)"', html)


def test_save_as_confirms_the_name_it_really_writes(
        window, dialogs, tmp_path, monkeypatch):
    existing = tmp_path / 'note.md'
    existing.write_text('old')
    window.editor.setPlainText('new')
    pick_file(monkeypatch, tmp_path / 'note')

    dialogs.answers = [QMessageBox.No]
    assert not window.save_file_as()
    assert existing.read_text() == 'old'

    dialogs.answers = [QMessageBox.Yes]
    assert window.save_file_as()
    assert existing.read_text() == 'new'


def test_new_file_confirms_the_name_it_really_writes(
        window, dialogs, tmp_path, monkeypatch):
    existing = tmp_path / 'note.md'
    existing.write_text('old')
    window.populate_file_tree(str(tmp_path))
    pick_file(monkeypatch, tmp_path / 'note')
    dialogs.answers = [QMessageBox.No]
    window.create_new_file()
    assert existing.read_text() == 'old'


def test_save_as_updates_preview_config_and_tree(
        window, tmp_path, monkeypatch):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    note = tmp_path / 'a' / 'note.md'
    note.write_text('![i](p.png)\n')
    window.populate_file_tree(str(tmp_path))
    window.open_file_in_editor(file_path=str(note))
    window.update_preview()

    target = tmp_path / 'b' / 'copy.md'
    pick_file(monkeypatch, target)
    assert window.save_file_as()

    assert hrefs(window.live_preview.toHtml())[0].endswith('/b/p.png')
    assert window.config_manager.get_value('last_opened_file') == str(target)
    root = window.file_tree.topLevelItem(0)
    assert 'copy.md' in [
        root.child(1).child(i).text(0)
        for i in range(root.child(1).childCount())]


def test_fenced_code_in_a_quote_shows_no_markers(window):
    text, _html = render(window, '> ```python\n> print(1)\n> ```\n')
    assert 'yamep-line' not in text
    assert 'print(1)' in text


def test_remote_image_stays_remote(window, opened):
    _text, html = render(window, '![r](https://example.org/i.png)\n')
    target = hrefs(html)[0]
    assert target == 'https://example.org/i.png'
    window.open_image(QUrl(target))
    assert opened == [target]


def test_image_example_in_code_stays_literal(window):
    text, _html = render(window, '```\n![sample](image.png)\n```\n')
    assert '![sample](image.png)' in text


def test_image_with_title_is_a_link(window):
    text, html = render(window, '![a](b.png "Title")\n')
    assert 'Image: a' in text and '<a' not in text
    assert hrefs(html)[0].endswith('/b.png')


def test_image_inside_a_link_keeps_the_outer_link(window):
    _text, html = render(window, '[![Build](https://x/y.svg)](https://x)\n')
    assert hrefs(html) == ['https://x']


def test_footnote_link_scrolls_instead_of_leaving(window, opened):
    render(window, 'Text[^1]\n\n' + 'filler\n\n' * 200 + '[^1]: note\n')
    window.resize(800, 400)
    window.preview_scrollbar.setValue(0)
    window.open_image(QUrl('#fn:1'))
    QTest.qWait(50)
    assert opened == []
    assert window.preview_scrollbar.value() > 0


def test_relative_link_resolves_against_the_note(window, opened, tmp_path):
    note = tmp_path / 'n.md'
    note.write_text('x')
    window.open_file_in_editor(file_path=str(note))
    window.update_preview()
    window.open_image(QUrl('other.md'))
    assert opened == [QUrl.fromLocalFile(str(tmp_path / 'other.md')).toString()]


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', 'smb://host/share', 'file:///tmp/evil.desktop',
])
def test_dangerous_links_are_refused(window, opened, url):
    window.open_image(QUrl(url))
    assert opened == []


def test_pasting_rich_text_stays_plain(window):
    window.editor.clear()
    mime = QMimeData()
    mime.setHtml('<b>bold</b> <img src="x.png">')
    mime.setText('bold')
    window.editor.insertFromMimeData(mime)
    assert window.editor.toPlainText() == 'bold'


def test_double_click_expands_a_folder(window, tmp_path):
    folder = tmp_path / 'tree' / 'sub'
    folder.mkdir(parents=True)
    (folder / 'a.md').write_text('x')
    window.populate_file_tree(str(tmp_path / 'tree'))
    QTest.qWait(20)
    item = window.file_tree.topLevelItem(0).child(0)
    viewport = window.file_tree.viewport()
    center = window.file_tree.visualItemRect(item).center()
    QTest.mouseClick(viewport, Qt.LeftButton, pos=center)
    QTest.qWait(300)
    QTest.mouseDClick(viewport, Qt.LeftButton, pos=center)
    QTest.qWait(20)
    assert item.isExpanded()


def checkbox_blocks(window):
    block = window.live_preview.document().begin()
    found = []
    while block.isValid():
        if block.text().startswith(('☐', '☑')):
            found.append(block)
        block = block.next()
    return found


def click_box(window, block):
    cursor = window.live_preview.textCursor()
    cursor.setPosition(block.position())
    window.toggle_task_at(
        window.live_preview.cursorRect(cursor).center() + QPoint(2, 0))


def test_task_in_a_quote_does_not_break_the_others(window):
    render(window, '- [ ] a\n\n> - [ ] q\n')
    click_box(window, checkbox_blocks(window)[0])
    assert window.editor.toPlainText() == '- [x] a\n\n> - [ ] q\n'


def test_task_inside_a_quote_can_be_ticked(window):
    render(window, '- [ ] a\n\n> - [ ] q\n')
    click_box(window, checkbox_blocks(window)[1])
    assert window.editor.toPlainText() == '- [ ] a\n\n> - [x] q\n'


def test_command_line_file_that_does_not_exist_yet(qapp, dialogs, tmp_path):
    path = tmp_path / 'new.md'
    window = YamepLite(str(path))
    assert window.current_file_path == str(path)
    window.editor.setPlainText('hello')
    assert window.save_file()
    assert path.read_text() == 'hello'
    window.close()


def test_broken_config_does_not_stop_the_start(qapp, dialogs):
    probe = YamepLite()
    config_path = probe.config_manager.config_path
    probe.close()
    config_path.write_text('{"window_geometry": "x", "expanded_items": 3}')
    YamepLite().close()
    os.unlink(config_path)
