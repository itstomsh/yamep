# SPDX-FileCopyrightText: 2025-2026 tomsh <tomsh@disroot.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import QMenu, QApplication
from PySide6.QtCore import Qt, Signal, QObject, Slot, QEvent, QUrl
from PySide6.QtGui import QPalette, QDesktopServices
import markdown
from markdown.extensions.extra import ExtraExtension
from markdown.extensions.tables import TableExtension
from markdown.extensions.sane_lists import SaneListExtension
from pymdownx.highlight import HighlightExtension
import importlib.resources as pkg_resources

from yamep.core.line_anchors import add_line_markers
from yamep.core.markdown_utils import tag_task_checkboxes


# The copy affordance mirrors the lite variant: a small tile inset into the
# code block, tinted from that block's own background, carrying a drawn glyph
# rather than a word. It stays hidden until the block is hovered - the theme
# stylesheets gate that with `pre:hover .copy-button`.
COPY_BUTTONS_JS = r"""
        var COPY_GLYPH =
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"'
            + ' stroke="currentColor" stroke-width="1.5"'
            + ' stroke-linejoin="round" stroke-linecap="round">'
            + '<rect x="2.2" y="2.2" width="8.4" height="10.4" rx="1.6"/>'
            + '<rect x="5.4" y="5.4" width="8.4" height="10.4" rx="1.6"'
            + ' fill="var(--tile-bg)"/></svg>';
        var DONE_GLYPH =
            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"'
            + ' stroke="currentColor" stroke-width="1.5"'
            + ' stroke-linejoin="round" stroke-linecap="round">'
            + '<path d="M3.2 8.6 L6.4 11.8 L12.8 4.6"/></svg>';

        function readColor(value) {
            var parts = (value || "").match(/[\d.]+/g);
            if (!parts || parts.length < 3) { return null; }
            return [+parts[0], +parts[1], +parts[2]];
        }

        // Same rule as the lite variant: pick the ink that stays readable on
        // the code background, then mix the tile out of the two.
        function tint(rgb, amount) {
            var ink = (Math.max.apply(null, rgb) + Math.min.apply(null, rgb))
                      / 2 > 140 ? 0 : 255;
            return "rgb(" + rgb.map(function (c) {
                return Math.round(c + (ink - c) * amount);
            }).join(",") + ")";
        }

        function dressTile(btn, source) {
            var rgb = readColor(getComputedStyle(source).backgroundColor)
                      || [68, 68, 68];
            var ink = (Math.max.apply(null, rgb) + Math.min.apply(null, rgb))
                      / 2 > 140 ? "#000000" : "#ffffff";
            btn.style.setProperty("--tile-bg", tint(rgb, 0.16));
            btn.style.setProperty("--tile-hover", tint(rgb, 0.30));
            btn.style.color = ink;
            btn.innerHTML = COPY_GLYPH;
            btn.title = "Copy code";
        }

        function copyText(btn, text) {
            function confirmCopy() {
                btn.innerHTML = DONE_GLYPH;
                setTimeout(function () { btn.innerHTML = COPY_GLYPH; }, 1600);
            }
            // QtWebEngine never settles navigator.clipboard.writeText(): the
            // promise stays pending, so no confirmation and no fallback ever
            // ran. Hand the text to Qt over the web channel instead.
            if (window.clipboardBridge) {
                window.clipboardBridge.copyText(text);
                confirmCopy();
                return;
            }
            // Without the channel (a preview used on its own) execCommand
            // works, as long as JavascriptCanAccessClipboard is enabled.
            var textarea = document.createElement("textarea");
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            try {
                if (document.execCommand("copy")) { confirmCopy(); }
            } catch (err) {
                console.error("Copy failed", err);
            }
            document.body.removeChild(textarea);
        }

        // One tile per fenced or indented code block.
        function addCopyButtonsToCodeBlocks() {
            document.querySelectorAll("pre").forEach(function (pre) {
                if (pre.querySelector(".copy-button")) { return; }
                var btn = document.createElement("button");
                btn.className = "copy-button";
                dressTile(btn, pre);
                btn.addEventListener("click", function (e) {
                    e.stopPropagation();
                    var code = pre.querySelector("code");
                    // Drop the block's closing newline: pasted into a shell,
                    // it would run the command straight away.
                    if (code) { copyText(btn, code.innerText.replace(/\n+$/, "")); }
                });
                pre.appendChild(btn);
            });
        }

        // The same tile, sized down by the stylesheet, for inline code.
        function addCopyButtonsToInlineCode() {
            document.querySelectorAll("code").forEach(function (code) {
                if (code.closest("pre")) { return; }
                var wrapper = code.parentNode;
                if (!wrapper.classList.contains("inline-code")) {
                    wrapper = document.createElement("span");
                    wrapper.className = "inline-code";
                    code.parentNode.insertBefore(wrapper, code);
                    wrapper.appendChild(code);
                }
                if (wrapper.querySelector(".copy-inline")) { return; }
                var btn = document.createElement("button");
                btn.className = "copy-inline";
                dressTile(btn, code);
                btn.addEventListener("click", function (e) {
                    e.stopPropagation();
                    copyText(btn, code.innerText);
                });
                wrapper.appendChild(btn);
            });
        }

        function addAllCopyButtons() {
            addCopyButtonsToCodeBlocks();
            addCopyButtonsToInlineCode();
        }
"""


class ExternalLinkPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # If the navigation is triggered by a link click, open it externally.
        if nav_type == QWebEnginePage.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        # If the navigation is triggered by a back/forward action, ignore it.
        elif nav_type == QWebEnginePage.NavigationTypeBackForward:
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


# Rules the page needs whatever the theme. The theme stylesheet comes after
# them and can override any of it.
PREVIEW_BASE_CSS = """
        /* The line-anchored scroll sync holds the top line in place itself;
           the browser's own scroll anchoring would fight it. */
        html { overflow-anchor: none; }

        /* A phone photo should not fill several screens. Capped images get a
           zoom cursor, and a click shows them at full height (IMAGE_JS). */
        img { max-height: 60vh; object-fit: contain; }
        img.yamep-capped { cursor: zoom-in; }
        img.yamep-expanded { max-height: none; cursor: zoom-out; }
"""

IMAGE_JS = r"""
        // Mark the images that actually hit the height cap.
        function yamepMarkCapped(img) {
            if (img.classList.contains("yamep-expanded")) { return; }
            var cap = parseFloat(getComputedStyle(img).maxHeight);
            img.classList.toggle("yamep-capped",
                !isNaN(cap) && img.naturalHeight > cap + 1
                && img.clientHeight >= cap - 1);
        }

        document.querySelectorAll("img").forEach(function (img) {
            if (img.complete) { yamepMarkCapped(img); }
            img.addEventListener("load", function () { yamepMarkCapped(img); });
        });

        document.addEventListener("click", function (e) {
            var img = e.target.closest ? e.target.closest("img") : null;
            // A linked image is a link, and ExternalLinkPage opens those.
            if (!img || img.closest("a")) { return; }
            if (img.classList.contains("yamep-expanded")) {
                img.classList.remove("yamep-expanded");
                yamepMarkCapped(img);
            } else if (img.classList.contains("yamep-capped")) {
                img.classList.replace("yamep-capped", "yamep-expanded");
            }
        });
"""

TASK_JS = r"""
        // Ticking a box in the preview edits the line it came from. The line
        // number is written into the checkbox while the page is rendered, so
        // nesting and indentation do not matter.
        document.addEventListener("change", function (e) {
            var box = e.target;
            if (!box || box.type !== "checkbox") { return; }
            var line = box.getAttribute("data-task-line");
            if (line === null || !window.taskBridge) {
                // Nothing to edit: put the box back rather than leave the
                // preview showing a state the file does not have.
                box.checked = !box.checked;
                return;
            }
            window.taskBridge.toggleTask(+line, box.checked);
        });
"""

LINE_SYNC_JS = r"""
        // Scroll sync anchored to source lines. The first line of every block
        // carries <span data-line="N"> (yamep.core.line_anchors), and scroll
        // positions are translated through those anchors, so an image or a
        // large heading cannot push the panes apart: they line up again at
        // the next block.
        var yamepSync = {
            anchors: [{ line: 0, top: 0 }],
            // Source line the page follows the editor to; null once the user
            // scrolls the preview and leads instead.
            pinnedLine: null,
            // Where our own last scrollTo() landed.
            expectedY: null
        };

        function yamepCollectAnchors() {
            var anchors = [{ line: 0, top: 0 }];
            document.querySelectorAll("span[data-line]").forEach(function (span) {
                var block = span.closest("p, li, h1, h2, h3, h4, h5, h6, dt, dd")
                            || span;
                var line = +span.getAttribute("data-line");
                var top = block.getBoundingClientRect().top + window.scrollY;
                var last = anchors[anchors.length - 1];
                // Interpolation needs both columns to keep growing.
                if (line > last.line && top >= last.top) {
                    anchors.push({ line: line, top: top });
                }
            });
            var last = anchors[anchors.length - 1];
            var end = document.documentElement.scrollHeight;
            if (YAMEP_LINE_COUNT > last.line && end >= last.top) {
                anchors.push({ line: YAMEP_LINE_COUNT, top: end });
            }
            yamepSync.anchors = anchors;
        }

        function yamepInterpolate(value, from, to) {
            var a = yamepSync.anchors;
            var i = 0;
            while (i + 1 < a.length && a[i + 1][from] <= value) { i++; }
            var lo = a[i], hi = a[Math.min(i + 1, a.length - 1)];
            if (hi[from] === lo[from]) { return lo[to]; }
            var t = (value - lo[from]) / (hi[from] - lo[from]);
            return lo[to] + Math.max(0, Math.min(1, t)) * (hi[to] - lo[to]);
        }

        function yamepScrollTo(y) {
            window.scrollTo(0, y);
            // scrollTo() clamps to the scrollable range: remember where it
            // really landed, so the scroll event it fires is known to be ours.
            yamepSync.expectedY = window.scrollY;
        }

        window.yamepTopLine = function () {
            if (yamepSync.pinnedLine !== null) { return yamepSync.pinnedLine; }
            return yamepInterpolate(window.scrollY, "top", "line");
        };

        // Called from Python to follow the editor.
        window.yamepScrollToLine = function (line) {
            yamepSync.pinnedLine = line;
            yamepScrollTo(yamepInterpolate(line, "line", "top"));
        };

        window.addEventListener("scroll", function () {
            if (yamepSync.expectedY !== null
                    && Math.abs(window.scrollY - yamepSync.expectedY) <= 1) {
                return;
            }
            yamepSync.expectedY = null;
            yamepSync.pinnedLine = null;
            if (window.scrollSync) {
                window.scrollSync.setEditorLine(
                    yamepInterpolate(window.scrollY, "top", "line"));
            }
        });

        // Images load after the page does, and each one that arrives moves
        // every block below it. Measure again and keep the same source line
        // at the top.
        new ResizeObserver(function () {
            var line = window.yamepTopLine();
            yamepCollectAnchors();
            document.querySelectorAll("img").forEach(yamepMarkCapped);
            yamepScrollTo(yamepInterpolate(line, "line", "top"));
        }).observe(document.body);

        yamepCollectAnchors();
"""


class ScrollSync(QObject):
    # The source line (a float) at the top of the preview, sent when the user
    # scrolls it. The page itself filters out the scrolls it makes.
    previewLineChanged = Signal(float)

    @Slot(float)
    def setEditorLine(self, line):
        # Called from JavaScript when the user scrolls the preview.
        self.previewLineChanged.emit(line)


class ClipboardBridge(QObject):
    @Slot(str)
    def copyText(self, text):
        # Called from the copy tiles in the page.
        QApplication.clipboard().setText(text)


class TaskBridge(QObject):
    # Source line of a task the user ticked or cleared in the preview.
    taskToggled = Signal(int, bool)

    @Slot(int, bool)
    def toggleTask(self, line, checked):
        self.taskToggled.emit(line, checked)


class MarkdownPreview(QWebEngineView):
    load_started = Signal()
    load_finished = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setup_preview()
        self.setPage(ExternalLinkPage(self))
        # Needed for the copy tiles' execCommand("copy") fallback.
        self.page().settings().setAttribute(
            QWebEngineSettings.JavascriptCanAccessClipboard, True)
        self.installEventFilter(self)

        self._pending_top_line = None
        self._pending_callbacks = []
        self._base_url = QUrl.fromLocalFile(os.getcwd() + os.sep)
        self.scrollSync = None

        # A single, permanent connection: connecting per render leaked one
        # slot per keystroke and fired every stale callback on each load.
        self.page().loadFinished.connect(self._on_load_finished)

    def set_base_path(self, path):
        """
        Point relative links/images at `path` (a file or a directory), so a
        document that references `images/foo.png` renders it.
        """
        if path and os.path.isfile(path):
            path = os.path.dirname(path)
        if not path or not os.path.isdir(path):
            path = os.getcwd()
        self._base_url = QUrl.fromLocalFile(os.path.join(path, ''))

    def scroll_to_line(self, line):
        """Scroll so that source line `line` (a float) is at the top."""
        self.page().runJavaScript(
            f"window.yamepScrollToLine && window.yamepScrollToLine({line});")

    def _on_load_finished(self, ok):
        # Back to the source line that was at the top before the re-render;
        # a pixel offset would be wrong as soon as anything above it changed.
        if self._pending_top_line is not None:
            self.scroll_to_line(self._pending_top_line)
        callbacks, self._pending_callbacks = self._pending_callbacks, []
        for callback in callbacks:
            callback()
        self.load_finished.emit(ok)

    def eventFilter(self, source, event):
        if event.type() == QEvent.NativeGesture:
            # Ignore native gesture events (like back/forward from extra mouse buttons)
            return True
        return super().eventFilter(source, event)

    def setup_preview(self):
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_custom_menu)

    def show_custom_menu(self, pos):
        menu = QMenu(self)
        copy_action = self.page().action(QWebEnginePage.Copy)
        menu.addAction(copy_action)
        menu.exec_(self.mapToGlobal(pos))

    def is_system_dark_mode(self):
        palette = QApplication.palette()
        base_color = palette.color(QPalette.ColorRole.Base)
        text_color = palette.color(QPalette.ColorRole.Text)

        # Heuristic: if base is darker than text, it's probably dark mode
        return base_color.value() < text_color.value()

    def update_preview(
            self, markdown_text, theme="dark_theme.qss", on_finished=None):
        def after_top_line(top_line):
            self._render_html(markdown_text, theme, top_line, on_finished)

        self.page().runJavaScript(
            "window.yamepTopLine ? window.yamepTopLine() : null;",
            0, after_top_line)

    def _render_html(
            self, markdown_text,
            theme="dark_theme.qss",
            top_line=None,
            on_finished=None):

        html = markdown.markdown(
            add_line_markers(markdown_text),
            extensions=[
                ExtraExtension(),
                TableExtension(),
                SaneListExtension(),
                HighlightExtension(),
                'markdown.extensions.nl2br',
                'pymdownx.superfences',
                'pymdownx.tilde',
                'pymdownx.caret',
                'pymdownx.tasklist',
            ],
            extension_configs={
                # Without this the checkboxes render disabled, so a task
                # cannot be ticked in the preview at all.
                'pymdownx.tasklist': {'clickable_checkbox': True},
            },
        )
        html = tag_task_checkboxes(html, markdown_text)

        if theme == 'default':
            css_file = (
                'markdown_style_dark.css'
                if self.is_system_dark_mode()
                else 'markdown_style_light.css'
            )
        else:
            theme_css_mapping = {
                'dark_theme.qss': 'markdown_style_dark.css',
                'light_theme.qss': 'markdown_style_light.css',
                'blue_theme.qss': 'markdown_style_blue.css',
            }
            css_file = theme_css_mapping.get(theme, 'markdown_style_light.css')

        try:
            css = pkg_resources.read_text(
                "yamep.core.resources.themes", css_file)
        except FileNotFoundError:
            css = ""

        self._pending_top_line = top_line
        line_count = markdown_text.count('\n') + 1
        if on_finished:
            self._pending_callbacks.append(on_finished)

        html_full = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
{PREVIEW_BASE_CSS}
    </style>
    <style>
        {css}
    </style>
</head>
<body class="markdown-body">
    <div id="watermark">Preview</div>
    {html}
    <script>
        // Re-attach the bridge on every render: setHtml() replaces the
        // document, so objects fetched once at start-up do not survive.
        if (typeof qt !== "undefined" && qt.webChannelTransport) {{
            new QWebChannel(qt.webChannelTransport, function(channel) {{
                window.scrollSync = channel.objects.scrollSync;
                window.clipboardBridge = channel.objects.clipboard;
                window.taskBridge = channel.objects.tasks;
            }});
        }}

        var YAMEP_LINE_COUNT = {line_count};
{IMAGE_JS}
{TASK_JS}
{LINE_SYNC_JS}

{COPY_BUTTONS_JS}

        // Run the functions after a delay to ensure content is loaded.
        setTimeout(addAllCopyButtons, 1000);

        // Optional: Observe DOM changes to re-add copy buttons if new code appears.
        var observer = new MutationObserver(function(mutations) {{
            addAllCopyButtons();
        }});
        observer.observe(document.body, {{ childList: true, subtree: true }});
    </script>
</body>
</html>"""

        self.setHtml(html_full, self._base_url)

    def setup_scroll_channel(self):
        """
        Register the objects the page talks to: scroll sync and the
        clipboard. The channel lives on the page and survives navigation;
        every rendered document picks both up again (see `_render_html`).
        """
        self.channel = QWebChannel(self.page())
        self.scrollSync = ScrollSync()
        self.clipboardBridge = ClipboardBridge()
        self.taskBridge = TaskBridge()
        self.channel.registerObject("scrollSync", self.scrollSync)
        self.channel.registerObject("clipboard", self.clipboardBridge)
        self.channel.registerObject("tasks", self.taskBridge)
        self.page().setWebChannel(self.channel)
