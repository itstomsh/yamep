yamep/
├── core/               ← Shared logic (e.g. file I/O, config, themes)
│   ├── __init__.py
│   ├── config.py
│   ├── file_utils.py
│   ├── theme_utils.py
│   ├── markdown_utils.py  ← Shared parser/extensions
│   └── resources/
│       ├── themes/
│       └── icons/
│
├── lite/               ← Lightweight version (QTextBrowser, no threading)
│   ├── __init__.py
│   ├── app.py          ← Main QWidget app
│   └── ui_lite.py      ← All in one class or simple layout
│
├── full/               ← Full version (QWebEngineView, threads, toolbars)
│   ├── __init__.py
│   ├── app.py          ← Main QMainWindow app
│   ├── editor.py
│   ├── preview.py
│   ├── file_tree.py
│   ├── settings.py
│   └── toolbar.py
│
├── launcher.py         ← Optional: lets user pick “lite” or “full”
├── requirements.txt
└── pyproject.toml / setup.py
