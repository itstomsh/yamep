# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The full variant, on a real QtWebEngine page."""
import http.server
import json
import multiprocessing
import os
import re

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import yamep.core.utils as utils
from conftest import pick_file
from yamep.full.app import Yamep
from yamep.full.preview import SET_HTML_LIMIT

PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010806000000'
    '1f15c4890000000d49444154789c63f8cfc0f01f00050001ff5ca8d8a4'
    '0000000049454e44ae426082')


def _serve(port_pipe, log_path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            with open(log_path, 'a') as log:
                log.write(self.path + '\n')
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.end_headers()
            self.wfile.write(PNG)

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    port_pipe.send(server.server_port)
    server.serve_forever()


@pytest.fixture
def server(tmp_path):
    """A server in its own process: qWait() does not let threads run."""
    log = tmp_path / 'requests.log'
    log.touch()
    ours, theirs = multiprocessing.Pipe()
    process = multiprocessing.get_context('fork').Process(
        target=_serve, args=(theirs, log), daemon=True)
    process.start()
    yield ours.recv(), log
    process.terminate()


@pytest.fixture
def opened(monkeypatch):
    urls = []
    monkeypatch.setattr(
        utils.QDesktopServices, 'openUrl',
        staticmethod(lambda url: urls.append(url.toString()) or True))
    return urls


class Driver:
    def __init__(self, window):
        self.window = window
        self.loads = []
        window.preview.load_finished.connect(self.loads.append)

    def js(self, code):
        result = []
        self.window.preview.page().runJavaScript(code, 0, result.append)
        waited = 0
        while not result and waited < 5000:
            QTest.qWait(20)
            waited += 20
        return result[0] if result else None

    def wait_load(self, count):
        waited = 0
        while len(self.loads) == count and waited < 15000:
            QTest.qWait(20)
            waited += 20
        QTest.qWait(150)
        assert len(self.loads) > count

    def show(self, text):
        count = len(self.loads)
        self.window.editor.setPlainText(text)
        self.wait_load(count)

    def click(self, selector):
        rect = json.loads(self.js(
            '(function(){var r=document.querySelector('
            + json.dumps(selector) + ').getBoundingClientRect();'
            'return JSON.stringify([r.x+r.width/2,r.y+r.height/2])})()'))
        target = self.window.preview.focusProxy() or self.window.preview
        QTest.mouseClick(
            target, Qt.LeftButton, pos=QPoint(int(rect[0]), int(rect[1])))
        QTest.qWait(400)


@pytest.fixture
def full(qapp, dialogs):
    window = Yamep()
    window.resize(1100, 700)
    window.show()
    driver = Driver(window)
    QTest.qWait(600)
    assert driver.js('1') == 1
    yield driver
    window.editor.document().setModified(False)
    window.setAttribute(Qt.WA_DeleteOnClose, False)
    window.close()


def test_script_in_a_note_does_not_run(full, tmp_path):
    note = tmp_path / 'evil.md'
    note.write_text('x')
    full.window.open_file_in_editor(str(note))
    QTest.qWait(500)
    full.show(
        '<script>window.ran = 1;</script>\n\n'
        '<img src=x onerror="window.ran = 2">\n')
    QTest.qWait(300)
    assert full.js('String(window.ran)') == 'undefined'


def test_page_cannot_read_local_files_or_reach_the_network(full, tmp_path):
    secret = tmp_path / 'secret.txt'
    secret.write_text('s3cret')
    full.window.preview.set_base_path(str(tmp_path))
    full.show('# x\n')
    # runJavaScript goes past the nonce, which makes it a fair test of what
    # the policy leaves a script that somehow got in.
    assert full.js(f"""
        (function () {{
            var x = new XMLHttpRequest();
            try {{
                x.open('GET', 'file://{secret}', false);
                x.send();
                return x.responseText;
            }} catch (e) {{ return 'blocked'; }}
        }})()""") == 'blocked'


def test_own_page_script_still_runs(full):
    full.show('```python\nprint(1)\n```\n\n- [ ] task\n')
    QTest.qWait(1300)
    assert full.js('document.querySelectorAll(".copy-button").length') == 1
    assert full.js('!!window.taskBridge') is True


def test_ticking_a_box_edits_the_source(full):
    full.show('- [ ] a\n\n> - [ ] q\n')
    full.click('input[data-task-line="2"]')
    assert full.window.editor.toPlainText() == '- [ ] a\n\n> - [x] q\n'


def test_meta_refresh_cannot_replace_the_preview(full, server):
    port, log = server
    full.show(
        f'<meta http-equiv="refresh" content="0;url=http://127.0.0.1:{port}/x">'
        '\n\n# still here\n')
    QTest.qWait(700)
    assert log.read_text() == ''
    assert full.js('document.querySelector("h1").innerText') == 'still here'


def test_remote_image_is_shown(full, server, tmp_path):
    port, log = server
    note = tmp_path / 'n.md'
    note.write_text('x')
    full.window.open_file_in_editor(str(note))
    QTest.qWait(500)
    full.show(f'![x](http://127.0.0.1:{port}/i.png)\n')
    QTest.qWait(500)
    assert '/i.png' in log.read_text()
    assert full.js('document.images[0].naturalWidth') == 1


@pytest.mark.parametrize('character,size', [('š', 700), ('a', 2500)])
def test_large_document_is_rendered(full, character, size):
    line = character * 39 + '\n'
    body = line * (size * 1024 // len(line.encode()))
    full.show('# LARGE\n\n' + body)
    assert full.loads[-1] is True
    assert full.js('document.querySelector("h1").innerText') == 'LARGE'
    assert full.js('document.getElementById("watermark") !== null') is True
    # The page's own script runs there too.
    assert full.js('typeof window.yamepScrollToLine') == 'function'


def test_size_limit_is_below_the_data_url_cap():
    assert SET_HTML_LIMIT < 2 * 1024 * 1024


def test_code_is_highlighted(full):
    full.show('```python\ndef f():\n    return 1\n```\n')
    assert full.js(
        'getComputedStyle(document.querySelector("pre code span.k")).color'
        ' !== getComputedStyle(document.querySelector("pre code")).color'
    ) is True


def test_links_in_the_page(full, opened, tmp_path):
    note = tmp_path / 'n.md'
    note.write_text('x')
    full.window.open_file_in_editor(str(note))
    QTest.qWait(500)
    full.show('[rel](other.md) [frag](#sec) Text[^1]\n\n'
              + 'filler\n\n' * 200 + '## sec {#sec}\n\n[^1]: note\n')
    full.click('a[href="other.md"]')
    assert len(opened) == 1 and opened[0].endswith('/other.md')
    opened.clear()
    full.click('a[href="#sec"]')
    assert opened == []
    assert full.js('window.scrollY') > 0


def test_new_file_cancel_leaves_the_target_alone(
        full, dialogs, tmp_path, monkeypatch):
    target = tmp_path / 'target.md'
    target.write_text('keep')
    fresh = tmp_path / 'fresh.md'
    full.window.editor.setPlainText('unsaved')
    full.window.editor.document().setModified(True)

    pick_file(monkeypatch, target)
    dialogs.answers = [QMessageBox.Cancel]
    full.window.create_new_file()
    assert target.read_text() == 'keep'

    pick_file(monkeypatch, fresh)
    dialogs.answers = [QMessageBox.Cancel]
    full.window.create_new_file()
    assert not fresh.exists()


def test_save_as_confirms_the_name_it_really_writes(
        full, dialogs, tmp_path, monkeypatch):
    existing = tmp_path / 'note.md'
    existing.write_text('old')
    full.window.editor.setPlainText('new')
    pick_file(monkeypatch, tmp_path / 'note')
    dialogs.answers = [QMessageBox.No]
    assert not full.window.save_file_as()
    assert existing.read_text() == 'old'


def test_uppercase_extension_is_kept(full, tmp_path, monkeypatch):
    pick_file(monkeypatch, tmp_path / 'NOTE.MD')
    full.window.editor.setPlainText('x')
    assert full.window.save_file_as()
    assert os.path.basename(full.window.current_file_path) == 'NOTE.MD'


def test_save_as_moves_the_preview_base(full, tmp_path, monkeypatch):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    note = tmp_path / 'a' / 'n.md'
    note.write_text('text\n')
    full.window.open_file_in_editor(str(note))
    QTest.qWait(800)
    pick_file(monkeypatch, tmp_path / 'b' / 'c.md')
    count = len(full.loads)
    assert full.window.save_file_as()
    full.wait_load(count)
    assert re.search(r'/b/$', full.js('document.baseURI'))


def test_toggle_during_a_render_turns_the_preview_off(full):
    full.window.load_preview('# x')
    assert not full.window.preview.isVisible()
    full.window.toggle_preview_visibility()
    assert full.window.preview_enabled is False


def test_closing_during_a_render_keeps_the_setting(full):
    window = full.window
    window.load_preview('# x')
    window.close()
    assert window.config_manager.get_value('preview_visible') is True


def test_preview_button_follows_the_theme(full):
    button = full.window.toolbar_manager.preview_toggle_button
    full.window.apply_theme('dark_theme.qss')
    dark = button.icon().cacheKey()
    full.window.apply_theme('light_theme.qss')
    assert button.icon().cacheKey() != dark


def test_save_as_is_reachable(full):
    button = next(
        btn for btn, _icon, tip in full.window.toolbar_manager._buttons
        if tip == 'Save')
    assert [a.text() for a in button.menu().actions()] == ['Save As...']


def test_command_line_file_that_does_not_exist_yet(qapp, dialogs, tmp_path):
    path = tmp_path / 'new.md'
    window = Yamep(str(path))
    window.setAttribute(Qt.WA_DeleteOnClose, False)
    assert window.current_file_path == str(path)
    window.editor.setPlainText('hello')
    assert window.save_file()
    assert path.read_text() == 'hello'
    window.close()
    assert QApplication.instance()


def test_heading_has_an_id_to_link_to(full):
    full.show('[go](#far-away)\n\n## Far away\n')
    assert full.js('document.getElementById("far-away") !== null') is True


def test_footnote_link_in_a_large_document(
        full, opened, dialogs, tmp_path):
    note = tmp_path / 'big.md'
    note.write_text('x')
    full.window.open_file_in_editor(str(note))
    QTest.qWait(500)
    filler = ('word ' * 3000 + '\n\n') * (SET_HTML_LIMIT // 15000 + 10)
    full.show('Text[^1]\n\n' + filler + '[^1]: note\n')
    assert full.js('window.location.protocol') == 'file:'
    full.click('a.footnote-ref')
    assert opened == []
    assert full.js('window.scrollY') > 0
    assert not dialogs.errors
