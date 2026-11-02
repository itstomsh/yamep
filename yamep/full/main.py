# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from yamep.full.app import Yamep
from yamep.core.integration import parse_args_and_run_integration
from importlib.resources import files
from PySide6.QtCore import qInstallMessageHandler

logging.basicConfig(
    level=logging.WARNING,  # DEBUG / INFO / WARNING / ERROR / CRITICAL
    format="%(levelname)s | %(asctime)s | %(message)s",
    force=True
)


def myMessageHandler(msgType, context, message):
    # If the message contains the text we want to suppress, ignore it.
    if "This plugin supports grabbing the mouse only for popup windows" in message:
        return
    # Otherwise, print the message normally.
    sys.stderr.write(message + "\n")


def main():
    try:
        file_to_open = parse_args_and_run_integration()
        qInstallMessageHandler(myMessageHandler)
        app = QApplication(sys.argv)
        app.setApplicationName("Yamep")
        icon_path = files("yamep.core.resources").joinpath(
            "io.github.itstomsh.yamep.png")
        app.setWindowIcon(QIcon(str(icon_path)))
        app.setDesktopFileName("io.github.itstomsh.yamep")

        window = Yamep(file_to_open)
        window.show()

        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
