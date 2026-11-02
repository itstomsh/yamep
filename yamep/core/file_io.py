# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Reading and writing notes without losing them.

Notes often sit in a folder that a sync client (Nextcloud, Syncthing, ...)
rewrites behind the editor's back. Two things follow:

* A save must never leave a half-written file behind for the sync client to
  pick up. The text goes to a temporary file next to the note, which is then
  renamed over the original in one step.
* A note that changes on disk while it is open must neither be overwritten
  silently by the older copy in the editor, nor be replaced in the editor by
  a file that is still being written.

Both variants use this module, so these rules live in one place.
"""
import logging
import os
import stat
import tempfile
from collections import namedtuple

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMessageBox

# Identifies one version of a file: the inode changes when a file is replaced
# by a rename, size and mtime when it is rewritten in place.
FileSignature = namedtuple('FileSignature', 'device inode size mtime_ns')

# How long a changed file has to stay unchanged before it is acted on. An
# in-place writer truncates the file first and fills it afterwards; reloading
# in between would put an empty or partial note into the editor.
SETTLE_MS = 300

_UNSET = object()


def _signature_of(st):
    return FileSignature(st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def file_signature(path):
    """Signature of the file at `path`, or None if there is no such file."""
    try:
        return _signature_of(os.stat(path))
    except (FileNotFoundError, NotADirectoryError):
        return None


def read_text(path, encoding='utf-8'):
    """
    Return (text, signature) for `path`.

    The signature is taken before reading, so a write that races the read
    leaves the file looking changed instead of slipping by unnoticed.
    """
    signature = file_signature(path)
    with open(path, 'r', encoding=encoding) as f:
        return f.read(), signature


def _default_file_mode():
    # The umask can only be read by setting it, so put it straight back.
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def _fsync_directory(directory):
    # Makes the rename itself durable. Not possible everywhere - Windows
    # cannot open a directory - and the data is already on disk by then.
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path, text, encoding='utf-8'):
    """
    Replace the contents of `path` with `text` in a single step.

    The file keeps its permissions, and a symlinked note keeps its link: the
    link's target is replaced, not the link. Returns the signature of the
    written file, read from the file itself before the rename, so a change
    landing right after the rename still counts as someone else's.
    """
    target = os.path.realpath(path)
    directory = os.path.dirname(target)
    try:
        mode = stat.S_IMODE(os.stat(target).st_mode)
    except FileNotFoundError:
        mode = _default_file_mode()

    # Hidden and tilde-suffixed, the usual convention for an editor's
    # temporary file, for the moment it exists.
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=f'.{os.path.basename(target)}.', suffix='~')
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            signature = _signature_of(os.fstat(f.fileno()))
        # mkstemp creates the file 0600; a saved note must not lose the
        # permissions it had. chmod touches ctime only, not the signature.
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _fsync_directory(directory)
    return signature


class DocumentFileGuard(QObject):
    """
    Keeps an editor's document in step with the file it was loaded from.

    The file and its folder are both watched: a rename over the file - how
    sync clients, and this module, save - drops the watch on the file itself,
    while the folder keeps reporting it. Once a change has settled:

    * with no unsaved edits, the note is reloaded;
    * with unsaved edits, the user picks which version to keep;
    * if the file is gone, the text stays and the document is marked
      modified, so it cannot be closed without being offered a save.

    A reload is a single undoable edit: Ctrl+Z brings the replaced text back.
    """

    # A short, human readable message about what just happened.
    notice = Signal(str)

    def __init__(self, window, editor):
        super().__init__(window)
        self._window = window
        self._editor = editor
        self._path = None
        self._name = ''
        self._known = None
        self._pending = _UNSET
        self._prompting = False

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._schedule_check)
        self._watcher.directoryChanged.connect(self._schedule_check)

        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self._check)

    def open(self, path):
        """Read `path`, start guarding it and return its text."""
        text, signature = read_text(path)
        self.track(path, signature)
        return text

    def save(self, path, text):
        """
        Write `text` to `path` atomically and guard that file from then on.

        Returns False without writing if `path` is the guarded file, it was
        changed on disk since it was loaded, and the user declines to
        overwrite it. Raises OSError if the write itself fails.
        """
        if self._is_guarded(path) and not self._confirm_overwrite(text):
            return False
        self.track(path, atomic_write_text(path, text))
        return True

    def track(self, path, signature=None):
        """Guard `path`; the editor holds the version with `signature`."""
        self._unwatch()
        # Watch the real file: for a symlinked note, the folder that sees the
        # rename is the target's folder, not the link's.
        self._path = os.path.realpath(path)
        self._name = os.path.basename(path)
        self._known = (
            file_signature(self._path) if signature is None else signature)
        self._pending = _UNSET
        self._watch()

    def forget(self):
        """Stop guarding: the document no longer belongs to a file."""
        self._unwatch()
        self._settle.stop()
        self._path = None
        self._known = None
        self._pending = _UNSET

    # -- Watching -----------------------------------------------------------

    def _is_guarded(self, path):
        return self._path is not None and os.path.realpath(path) == self._path

    def _watch(self):
        watched = set(self._watcher.files()) | set(self._watcher.directories())
        for candidate in (self._path, os.path.dirname(self._path)):
            if candidate not in watched and os.path.exists(candidate):
                self._watcher.addPath(candidate)

    def _unwatch(self):
        paths = self._watcher.files() + self._watcher.directories()
        if paths:
            self._watcher.removePaths(paths)

    def _schedule_check(self, _changed_path=''):
        if self._path is not None:
            self._settle.start()

    def _check(self):
        if self._path is None:
            return
        signature = file_signature(self._path)
        if self._pending is _UNSET and signature == self._known:
            # Another file in the folder changed, or our own save came back.
            self._watch()
            return
        if signature != self._pending:
            # Still changing: look again once it has been quiet for a while.
            self._pending = signature
            self._settle.start()
            return

        self._pending = _UNSET
        self._watch()
        if signature == self._known or self._prompting:
            return
        if signature is None:
            self._on_removed()
        else:
            self._on_changed()

    # -- Reacting -----------------------------------------------------------

    def _on_changed(self):
        try:
            text, signature = read_text(self._path)
        except (OSError, UnicodeError) as e:
            logging.warning(f"Could not read changed file {self._path}: {e}")
            return

        document = self._editor.document()
        if text == self._editor.toPlainText():
            # Touched, or saved elsewhere with identical content.
            self._known = signature
            document.setModified(False)
            return

        if not document.isModified():
            self._replace_text(text, signature)
            self.notice.emit(f"{self._name} changed on disk and was reloaded")
            return

        self._prompting = True
        try:
            reload = self._ask_reload()
        finally:
            self._prompting = False

        if reload:
            # Read again: the file may have moved on while the dialog was up.
            try:
                text, signature = read_text(self._path)
            except (OSError, UnicodeError) as e:
                logging.warning(f"Could not reload {self._path}: {e}")
                return
            self._replace_text(text, signature)
            self.notice.emit(
                f"{self._name} reloaded - Ctrl+Z brings your edits back")
        else:
            # Keeping the editor's text: the version on disk is now the one a
            # save will knowingly replace.
            self._known = file_signature(self._path)
        self._schedule_check()

    def _on_removed(self):
        self._known = None
        # The editor may now hold the only copy of this note.
        self._editor.document().setModified(True)
        self.notice.emit(
            f"{self._name} was deleted or moved on disk - save to keep it")

    def _replace_text(self, text, signature):
        editor = self._editor
        position = editor.textCursor().position()
        scroll = editor.verticalScrollBar().value()

        # One edit block rather than setPlainText(), which would wipe the
        # undo history along with the text it replaces.
        cursor = QTextCursor(editor.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.insertText(text)
        cursor.endEditBlock()

        cursor = editor.textCursor()
        cursor.setPosition(
            min(position, editor.document().characterCount() - 1))
        editor.setTextCursor(cursor)
        editor.verticalScrollBar().setValue(scroll)
        editor.document().setModified(False)
        self._known = signature

    def _confirm_overwrite(self, text):
        on_disk = file_signature(self._path)
        if on_disk is None or on_disk == self._known:
            return True
        try:
            if read_text(self._path)[0] == text:
                return True
        except (OSError, UnicodeError):
            pass
        self._prompting = True
        try:
            return self._ask_overwrite()
        finally:
            self._prompting = False

    # -- Dialogs (separate so they can be replaced in tests) ----------------

    def _ask_reload(self):
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("File Changed on Disk")
        box.setText(
            f"{self._name} was changed by another program, "
            "such as a sync client.")
        box.setInformativeText(
            "Reload it and replace your unsaved edits, or keep your version? "
            "If you keep it, your next save overwrites the other change.")
        reload_button = box.addButton("Reload", QMessageBox.DestructiveRole)
        keep_button = box.addButton("Keep My Version", QMessageBox.RejectRole)
        box.setDefaultButton(keep_button)
        box.exec()
        return box.clickedButton() is reload_button

    def _ask_overwrite(self):
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("File Changed on Disk")
        box.setText(f"{self._name} was changed on disk after you opened it.")
        box.setInformativeText("Overwrite it with your version?")
        overwrite_button = box.addButton(
            "Overwrite", QMessageBox.DestructiveRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() is overwrite_button
