# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
import sys
from yamep.lite.app import YamepLite
from yamep.core.integration import parse_args_and_run_integration
from importlib.resources import files

logging.basicConfig(
    level=logging.WARNING,  # DEBUG / INFO / WARNING / ERROR / CRITICAL
    format="%(levelname)s | %(asctime)s | %(message)s",
    force=True
)


def main():
    try:
        file_to_open = parse_args_and_run_integration()
        app = QApplication(sys.argv)

        icon_path = files("yamep.core.resources").joinpath(
            "io.github.itstomsh.yamep.lite.png")
        app.setWindowIcon(QIcon(str(icon_path)))

        app.setApplicationName("YamepLite")
        app.setDesktopFileName("io.github.itstomsh.yamep.lite")
        window = YamepLite(file_to_open)
        window.show()

        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
