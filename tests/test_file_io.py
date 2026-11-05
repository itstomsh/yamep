# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest
from PySide6.QtWidgets import QTextEdit

from yamep.core.config_manager import ConfigManager
from yamep.core.file_io import (
    DocumentFileGuard, atomic_write_text, document_text, read_document,
)


@pytest.fixture
def editor(qapp):
    return QTextEdit()


@pytest.fixture
def guard(editor):
    return DocumentFileGuard(None, editor)


def round_trip(guard, editor, path):
    editor.setPlainText(guard.open(path))
    assert guard.save(path, document_text(editor))
    return path.read_bytes()


@pytest.mark.parametrize('raw', [
    'a\r\nb\r\n'.encode(),
    '10\u00a0km\n'.encode(),
    'x\u2028y\n'.encode(),
    b'a\nb\n',
    b'no final newline',
])
def test_saving_keeps_every_byte(guard, editor, tmp_path, raw):
    path = tmp_path / 'note.md'
    path.write_bytes(raw)
    assert round_trip(guard, editor, path) == raw


def test_read_document_normalises_and_reports_newline(tmp_path):
    path = tmp_path / 'n.md'
    path.write_bytes(b'a\r\nb\r\nc\n')
    text, _signature, file_format = read_document(path)
    assert (text, file_format.newline) == ('a\nb\nc\n', '\r\n')


def test_byte_order_mark_stays_out_of_the_text_and_in_the_file(
        guard, editor, tmp_path):
    path = tmp_path / 'windows.md'
    raw = '\ufeff# Title\r\n\r\ntext\r\n'.encode('utf-8')
    path.write_bytes(raw)
    text = guard.open(path)
    assert text == '# Title\n\ntext\n'
    assert round_trip(guard, editor, path) == raw


def test_save_as_elsewhere_does_not_carry_old_file_state(
        guard, editor, tmp_path):
    source = tmp_path / 'windows.md'
    source.write_bytes(b'a\r\n')
    editor.setPlainText(guard.open(source))
    target = tmp_path / 'copy.md'
    assert guard.save(target, 'b\n')
    assert target.read_bytes() == b'b\n'


def test_retargeted_symlink_asks_before_overwriting(guard, editor, tmp_path):
    a, b = tmp_path / 'a.md', tmp_path / 'b.md'
    a.write_text('A')
    b.write_text('B')
    link = tmp_path / 'link.md'
    link.symlink_to(a)
    editor.setPlainText(guard.open(link))

    link.unlink()
    link.symlink_to(b)
    asked = []
    guard._ask_overwrite = lambda: asked.append(True) or False

    assert not guard.save(link, 'edited')
    assert asked
    assert b.read_text() == 'B'


def test_symlinked_note_stays_a_symlink(guard, editor, tmp_path):
    target = tmp_path / 'real.md'
    target.write_text('x')
    link = tmp_path / 'link.md'
    link.symlink_to(target)
    editor.setPlainText(guard.open(link))
    assert guard.save(link, 'y')
    assert link.is_symlink() and target.read_text() == 'y'


def test_hard_link_survives_a_save(guard, editor, tmp_path):
    first, second = tmp_path / '1.md', tmp_path / '2.md'
    first.write_text('old')
    os.link(first, second)
    editor.setPlainText(guard.open(first))
    assert guard.save(first, 'new')
    assert second.read_text() == 'new'


def test_long_file_name_can_be_saved(tmp_path):
    path = tmp_path / ('n' * 250 + '.md')
    atomic_write_text(path, 'x')
    assert path.read_text() == 'x'


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores permissions')
def test_writable_note_in_read_only_folder(tmp_path):
    folder = tmp_path / 'ro'
    folder.mkdir()
    note = folder / 'a.md'
    note.write_text('old')
    folder.chmod(0o555)
    try:
        atomic_write_text(note, 'new')
        assert note.read_text() == 'new'
    finally:
        folder.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores permissions')
def test_check_survives_lost_permissions(guard, editor, tmp_path):
    folder = tmp_path / 'g'
    folder.mkdir()
    note = folder / 'a.md'
    note.write_text('x')
    editor.setPlainText(guard.open(note))
    folder.chmod(0)
    try:
        guard._check()
    finally:
        folder.chmod(0o755)


@pytest.mark.parametrize('content', ['[]', 'null', '3', '{broken'])
def test_config_that_is_not_a_dict_is_ignored(qapp, content):
    config = ConfigManager('lite')
    config.config_path.parent.mkdir(parents=True, exist_ok=True)
    config.config_path.write_text(content)
    assert ConfigManager('lite').config == {}


def test_config_values_of_the_wrong_type_are_ignored(qapp):
    config = ConfigManager('lite')
    config.config = {'window_geometry': 'x', 'window_state': 5,
                     'expanded_items': 3, 'expanded_paths': 'y'}
    assert config.get_window_geometry() is None
    assert config.get_window_state() is None
    assert config.get_list('expanded_items') == []
    assert config.get_expanded_paths() == []
