# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Every test runs headless and against a throwaway config folder, so the suite
needs no display and never touches the settings of a real installation.
"""
import os
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QTWEBENGINE_DISABLE_SANDBOX'] = '1'
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
os.environ['XDG_CONFIG_HOME'] = tempfile.mkdtemp(prefix='yamep-tests-')

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


@pytest.fixture(scope='session')
def qapp():
    yield QApplication.instance() or QApplication(['yamep-tests'])


class Dialogs:
    """Stands in for QMessageBox: answers from a queue and records questions."""

    def __init__(self):
        self.answers = []
        self.asked = []
        self.warnings = []

    def question(self, _parent, title, *_args, **_kwargs):
        self.asked.append(title)
        return self.answers.pop(0) if self.answers else QMessageBox.Discard

    def warning(self, _parent, _title, text, *_args):
        self.warnings.append(text)


@pytest.fixture
def dialogs(monkeypatch):
    fake = Dialogs()
    monkeypatch.setattr(QMessageBox, 'question', fake.question)
    monkeypatch.setattr(QMessageBox, 'warning', fake.warning)
    return fake


@pytest.fixture(autouse=True)
def clean_config():
    folder = os.path.join(os.environ['XDG_CONFIG_HOME'], 'yamep')
    for name in ('config_lite.json', 'config_full.json'):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            os.unlink(path)


def pick_file(monkeypatch, path):
    """Make the next save dialogs return `path`."""
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(
        QFileDialog, 'getSaveFileName',
        staticmethod(lambda *_a, **_k: (str(path), '')))
