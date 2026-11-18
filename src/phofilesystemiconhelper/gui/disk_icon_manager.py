"""Cross-platform Disk Icon Manager (Windows + macOS)."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PyQt6.QtCore import QFileInfo, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from phofilesystemiconhelper.apply_volume_icon import (
    ApplyResult,
    apply_icon_path,
    get_volume_icon_state,
    is_windows_admin,
    revert_volume_icon,
)
from phofilesystemiconhelper.disk_probe import DiskIdentity, list_disks
from phofilesystemiconhelper.icon_db import connect, icon_count, index_icons
from phofilesystemiconhelper.icon_preview import icon_to_png_bytes
from phofilesystemiconhelper.match_icons import MatchResult, match_all_disks
from phofilesystemiconhelper.paths import DEFAULT_DB_PATH, ensure_data_dirs

PREVIEW_SIZE = 96


def _format_capacity(nbytes: int | None) -> str:
    if not nbytes:
        return "?"
    gb = nbytes / (1000**3)
    if gb >= 1000:
        return f"{gb / 1000:.1f} TB"
    return f"{gb:.0f} GB"


def _pixmap_from_icon_file(path: Path | None, size: int = PREVIEW_SIZE) -> QPixmap | None:
    if path is None or not path.exists():
        return None
    data = icon_to_png_bytes(path, size=size)
    if data:
        pix = QPixmap()
        if pix.loadFromData(data, "PNG"):
            return pix
    # Fallback: let Qt try (works for .ico on Windows)
    pix = QPixmap(str(path))
    if pix.isNull():
        return None
    return pix.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _shell_pixmap_for_mount(mount: str, size: int = PREVIEW_SIZE) -> QPixmap:
    provider = QFileIconProvider()
    # Windows drive roots need trailing backslash for QFileInfo
    info_path = mount
    if sys.platform == "win32" and len(mount) >= 2 and mount[1] == ":":
        info_path = mount.rstrip("\\/") + "\\"
    icon = provider.icon(QFileInfo(info_path))
    return icon.pixmap(size, size)


def _primary_mount(disk: DiskIdentity) -> str | None:
    if not disk.mounts:
        return None
    if sys.platform == "win32":
        for m in disk.mounts:
            if len(m) >= 2 and m[1] == ":":
                return m
    return disk.mounts[0]


def _is_removable(disk: DiskIdentity) -> bool:
    return disk.bus in {"usb", "external"}


def _restart_elevated_windows() -> bool:
    """Relaunch this process elevated via UAC. Returns True if ShellExecute was invoked."""
    if sys.platform != "win32":
        return False
    params = " ".join(
        [f'"{a}"' if " " in a else a for a in ["-m", "phofilesystemiconhelper", "gui"]]
    )
    # If launched as script path, prefer -m package
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            params,
            None,
            1,  # SW_SHOWNORMAL
        )
        return int(rc) > 32
    except Exception:
        return False


class RefreshWorker(QThread):
    finished_ok = pyqtSignal(list, int)  # matches, icon_count
    failed = pyqtSignal(str)

    def __init__(
        self,
        db_path: Path,
        include_system: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.include_system = include_system

    def run(self) -> None:
        try:
            ensure_data_dirs()
            count = 0
            if self.db_path.is_file():
                conn = connect(self.db_path)
                try:
                    count = icon_count(conn)
                finally:
                    conn.close()
                matches = match_all_disks(
                    db_path=self.db_path,
                    include_system=self.include_system,
                )
            else:
                disks = list_disks()
                if not self.include_system:
                    disks = [d for d in disks if not d.is_system]
                matches = [
                    MatchResult(
                        disk=d,
                        icon=None,
                        score=0,
                        reasons=["no-icon-db"],
                    )
                    for d in disks
                ]
            self.finished_ok.emit(matches, count)
        except Exception as exc:
            self.failed.emit(str(exc))


class ApplyWorker(QThread):
    finished_ok = pyqtSignal(list)  # list[ApplyResult]
    failed = pyqtSignal(str)

    def __init__(
        self,
        jobs: list[tuple[str, Path | None, bool, str]],
        parent: QWidget | None = None,
    ) -> None:
        """jobs: (mount, icon_path|None, removable, action) action in apply|revert."""
        super().__init__(parent)
        self.jobs = jobs

    def run(self) -> None:
        results: list[ApplyResult] = []
        try:
            for mount, icon_path, removable, action in self.jobs:
                if action == "revert":
                    results.append(
                        revert_volume_icon(
                            mount, removable=removable, dry_run=False
                        )
                    )
                elif action == "apply" and icon_path is not None:
                    results.append(
                        apply_icon_path(
                            mount,
                            icon_path,
                            removable=removable,
                            dry_run=False,
                        )
                    )
                else:
                    results.append(
                        ApplyResult(
                            mount=mount,
                            icon_path=icon_path,
                            ok=False,
                            message="invalid apply job",
                            dry_run=False,
                        )
                    )
            self.finished_ok.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class IndexWorker(QThread):
    finished_ok = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(
        self, folder: Path, db_path: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.folder = folder
        self.db_path = db_path

    def run(self) -> None:
        try:
            n = index_icons(self.folder, self.db_path)
            self.finished_ok.emit(n)
        except Exception as exc:
            self.failed.emit(str(exc))


class DiskRow(QFrame):
    """One disk: identity, current icon, suggested icon, actions. Drop target for icons."""

    apply_suggestion = pyqtSignal(object)  # MatchResult
    choose_icon = pyqtSignal(object)  # MatchResult
    revert = pyqtSignal(object)  # MatchResult
    drop_icon = pyqtSignal(object, str)  # MatchResult, path

    def __init__(self, match: MatchResult, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.match = match
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("diskRow")

        disk = match.disk
        mounts = ", ".join(disk.mounts) if disk.mounts else "(unmounted)"
        title = disk.model or disk.name or disk.id
        meta = (
            f"{disk.vendor or '—'} · {disk.media} · {disk.bus} · "
            f"{_format_capacity(disk.capacity_bytes)} · {mounts}"
        )
        if disk.is_system:
            meta += " · system"

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(16)

        info = QVBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 600;")
        meta_lbl = QLabel(meta)
        meta_lbl.setWordWrap(True)
        meta_lbl.setStyleSheet("color: #666;")
        info.addWidget(title_lbl)
        info.addWidget(meta_lbl)
        info.addStretch(1)
        root.addLayout(info, stretch=2)

        self.current_icon = QLabel()
        self.current_icon.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.current_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_icon.setToolTip("Current volume icon")
        current_col = QVBoxLayout()
        current_col.addWidget(QLabel("Current"))
        current_col.addWidget(self.current_icon)
        root.addLayout(current_col)

        self.suggested_icon = QLabel()
        self.suggested_icon.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.suggested_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.suggested_icon.setToolTip("Suggested replacement from icon database")
        self.suggested_label = QLabel()
        self.suggested_label.setWordWrap(True)
        self.suggested_label.setMaximumWidth(180)
        suggested_col = QVBoxLayout()
        suggested_col.addWidget(QLabel("Suggested"))
        suggested_col.addWidget(self.suggested_icon)
        suggested_col.addWidget(self.suggested_label)
        root.addLayout(suggested_col)

        actions = QVBoxLayout()
        self.btn_apply = QPushButton("Apply suggestion")
        self.btn_choose = QPushButton("Choose icon…")
        self.btn_revert = QPushButton("Revert to default")
        self.btn_apply.clicked.connect(lambda: self.apply_suggestion.emit(self.match))
        self.btn_choose.clicked.connect(lambda: self.choose_icon.emit(self.match))
        self.btn_revert.clicked.connect(lambda: self.revert.emit(self.match))
        actions.addWidget(self.btn_apply)
        actions.addWidget(self.btn_choose)
        actions.addWidget(self.btn_revert)
        drop_hint = QLabel("Drop .ico / .icns here")
        drop_hint.setStyleSheet("color: #888; font-size: 11px;")
        actions.addWidget(drop_hint)
        actions.addStretch(1)
        root.addLayout(actions)

        self._refresh_previews()

    def update_match(self, match: MatchResult) -> None:
        self.match = match
        self._refresh_previews()

    def _refresh_previews(self) -> None:
        mount = _primary_mount(self.match.disk)
        current_pix: QPixmap | None = None
        if mount:
            state = get_volume_icon_state(mount)
            if state.is_custom and state.custom_path:
                current_pix = _pixmap_from_icon_file(state.custom_path)
            if current_pix is None:
                current_pix = _shell_pixmap_for_mount(mount)
        if current_pix is None or current_pix.isNull():
            self.current_icon.setText("—")
            self.current_icon.setPixmap(QPixmap())
        else:
            self.current_icon.setText("")
            self.current_icon.setPixmap(current_pix)

        if self.match.icon is None:
            self.suggested_icon.setText("no match")
            self.suggested_icon.setPixmap(QPixmap())
            self.suggested_label.setText("")
            self.btn_apply.setEnabled(False)
            self.suggested_icon.setToolTip("; ".join(self.match.reasons) or "no match")
        else:
            path = self.match.resolved_path or self.match.icon.path
            pix = _pixmap_from_icon_file(path)
            if pix is None:
                self.suggested_icon.setText(self.match.icon.stem[:12])
                self.suggested_icon.setPixmap(QPixmap())
            else:
                self.suggested_icon.setText("")
                self.suggested_icon.setPixmap(pix)
            reasons = ", ".join(self.match.reasons)
            self.suggested_label.setText(
                f"score {self.match.score}\n{self.match.icon.stem}"
            )
            tip = f"{path}\nscore={self.match.score}\n{reasons}"
            self.suggested_icon.setToolTip(tip)
            self.suggested_label.setToolTip(tip)
            self.btn_apply.setEnabled(bool(mount))

        has_mount = mount is not None
        self.btn_choose.setEnabled(has_mount)
        self.btn_revert.setEnabled(has_mount)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    suffix = Path(url.toLocalFile()).suffix.lower()
                    if suffix in {".ico", ".icns"}:
                        event.acceptProposedAction()
                        return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if Path(path).suffix.lower() in {".ico", ".icns"}:
                self.drop_icon.emit(self.match, path)
                event.acceptProposedAction()
                return
        event.ignore()


class DiskIconManager(QWidget):
    def __init__(
        self,
        db_path: Path | str | None = None,
        include_system: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.include_system = include_system
        self._matches: list[MatchResult] = []
        self._rows: list[DiskRow] = []
        self._worker: QThread | None = None

        self.setWindowTitle("Disk Icon Manager")
        self.resize(960, 640)

        layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        self.db_label = QLabel()
        self.db_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.chk_system = QCheckBox("Include system volumes")
        self.chk_system.setChecked(include_system)
        self.chk_system.toggled.connect(self._on_include_system)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh)
        btn_index = QPushButton("Index icons folder…")
        btn_index.clicked.connect(self._index_folder)
        header.addWidget(self.db_label)
        header.addWidget(self.chk_system)
        header.addWidget(btn_refresh)
        header.addWidget(btn_index)
        layout.addLayout(header)

        self.elev_banner = QFrame()
        elev_layout = QHBoxLayout(self.elev_banner)
        elev_layout.setContentsMargins(8, 6, 8, 6)
        self.elev_label = QLabel(
            "Windows DriveIcons changes require administrator privileges."
        )
        btn_elevate = QPushButton("Restart elevated")
        btn_elevate.clicked.connect(self._elevate)
        elev_layout.addWidget(self.elev_label, stretch=1)
        elev_layout.addWidget(btn_elevate)
        self.elev_banner.setStyleSheet(
            "QFrame { background: #fff3cd; border: 1px solid #ffc107; }"
        )
        layout.addWidget(self.elev_banner)
        self._update_elevation_banner()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.list_layout.setSpacing(8)
        scroll.setWidget(self.list_host)
        layout.addWidget(scroll, stretch=1)

        footer = QHBoxLayout()
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        btn_apply_all = QPushButton("Apply all suggestions")
        btn_apply_all.clicked.connect(self._apply_all)
        footer.addWidget(self.status, stretch=1)
        footer.addWidget(btn_apply_all)
        layout.addLayout(footer)

        self._update_db_label(0)
        self.refresh()

    def _update_elevation_banner(self) -> None:
        if sys.platform != "win32":
            self.elev_banner.hide()
            return
        if is_windows_admin():
            self.elev_banner.hide()
        else:
            self.elev_banner.show()

    def _update_db_label(self, count: int) -> None:
        exists = self.db_path.is_file()
        if exists:
            self.db_label.setText(f"DB: {self.db_path}  ({count} icons)")
        else:
            self.db_label.setText(
                f"DB: {self.db_path}  (missing — index an icons folder)"
            )

    def _on_include_system(self, checked: bool) -> None:
        self.include_system = checked
        self.refresh()

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.setEnabled(not busy)
        if message:
            self.status.setText(message)

    def _clear_rows(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()

    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        worker = RefreshWorker(self.db_path, self.include_system, self)
        self._worker = worker
        msg = (
            "Probing disks…"
            if not self.db_path.is_file()
            else "Refreshing disks and matches…"
        )
        self._set_busy(True, msg)
        worker.finished_ok.connect(self._on_refresh_done)
        worker.failed.connect(self._on_refresh_failed)
        worker.start()

    def _on_refresh_done(self, matches: list, count: int) -> None:
        self._set_busy(False)
        self._matches = list(matches)
        self._update_db_label(count)
        self._rebuild_rows()
        if not self.db_path.is_file():
            self.status.setText(
                f"Loaded {len(self._matches)} disk(s). "
                "No icon database yet — click “Index icons folder…”."
            )
        else:
            self.status.setText(f"Loaded {len(self._matches)} disk(s).")
        self._update_elevation_banner()

    def _on_refresh_failed(self, message: str) -> None:
        self._set_busy(False)
        self.status.setText(f"Refresh failed: {message}")
        QMessageBox.warning(self, "Refresh failed", message)

    def _rebuild_rows(self) -> None:
        self._clear_rows()
        if not self._matches:
            empty = QLabel("No disks found.")
            self.list_layout.addWidget(empty)
            return
        for match in self._matches:
            row = DiskRow(match)
            row.apply_suggestion.connect(self._on_apply_suggestion)
            row.choose_icon.connect(self._on_choose_icon)
            row.revert.connect(self._on_revert)
            row.drop_icon.connect(self._on_drop_icon)
            self.list_layout.addWidget(row)
            self._rows.append(row)

    def _confirm(self, title: str, text: str) -> bool:
        r = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return r == QMessageBox.StandardButton.Yes

    def _run_apply_jobs(
        self, jobs: list[tuple[str, Path | None, bool, str]], status: str
    ) -> None:
        if not jobs:
            self.status.setText("Nothing to do.")
            return
        if sys.platform == "win32" and not is_windows_admin():
            choice = QMessageBox.warning(
                self,
                "Administrator required",
                "Applying or reverting Windows drive icons needs elevation.\n\n"
                "Click Yes to restart elevated, or No to cancel.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if choice == QMessageBox.StandardButton.Yes:
                self._elevate()
            return
        if self._worker is not None and self._worker.isRunning():
            return
        worker = ApplyWorker(jobs, self)
        self._worker = worker
        self._set_busy(True, status)
        worker.finished_ok.connect(self._on_apply_done)
        worker.failed.connect(self._on_apply_failed)
        worker.start()

    def _on_apply_done(self, results: list) -> None:
        self._set_busy(False)
        parts = []
        for r in results:
            tag = "ok" if r.ok else "FAIL"
            parts.append(f"{tag}: {r.mount}: {r.message}")
        self.status.setText(" · ".join(parts) if parts else "Done.")
        # Refresh current-icon previews without full rematch if possible
        for row in self._rows:
            row._refresh_previews()
        if any(not r.ok for r in results) and sys.platform == "win32" and not is_windows_admin():
            self.elev_banner.show()

    def _on_apply_failed(self, message: str) -> None:
        self._set_busy(False)
        self.status.setText(f"Action failed: {message}")
        QMessageBox.warning(self, "Action failed", message)

    def _jobs_for_match(
        self, match: MatchResult, action: str, icon_path: Path | None = None
    ) -> list[tuple[str, Path | None, bool, str]]:
        removable = _is_removable(match.disk)
        jobs: list[tuple[str, Path | None, bool, str]] = []
        for mount in match.disk.mounts:
            if sys.platform == "win32" and not (len(mount) >= 2 and mount[1] == ":"):
                continue
            if (
                sys.platform == "darwin"
                and mount == "/"
                and match.disk.is_system
                and not self.include_system
            ):
                continue
            jobs.append((mount, icon_path, removable, action))
        return jobs

    def _on_apply_suggestion(self, match: MatchResult) -> None:
        if match.icon is None:
            return
        path = match.resolved_path or match.icon.path
        if not self._confirm(
            "Apply suggestion",
            f"Apply suggested icon to {', '.join(match.disk.mounts)}?\n\n{path}",
        ):
            return
        jobs = self._jobs_for_match(match, "apply", Path(path))
        self._run_apply_jobs(jobs, "Applying suggestion…")

    def _on_choose_icon(self, match: MatchResult) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose icon",
            "",
            "Icon files (*.ico *.icns);;All files (*.*)",
        )
        if not path:
            return
        if not self._confirm(
            "Apply custom icon",
            f"Apply this icon to {', '.join(match.disk.mounts)}?\n\n{path}",
        ):
            return
        jobs = self._jobs_for_match(match, "apply", Path(path))
        self._run_apply_jobs(jobs, "Applying custom icon…")

    def _on_drop_icon(self, match: MatchResult, path: str) -> None:
        if not self._confirm(
            "Apply dropped icon",
            f"Apply this icon to {', '.join(match.disk.mounts)}?\n\n{path}",
        ):
            return
        jobs = self._jobs_for_match(match, "apply", Path(path))
        self._run_apply_jobs(jobs, "Applying dropped icon…")

    def _on_revert(self, match: MatchResult) -> None:
        if not self._confirm(
            "Revert to default",
            f"Remove custom icon overrides for {', '.join(match.disk.mounts)}?",
        ):
            return
        jobs = self._jobs_for_match(match, "revert", None)
        self._run_apply_jobs(jobs, "Reverting…")

    def _apply_all(self) -> None:
        jobs: list[tuple[str, Path | None, bool, str]] = []
        for match in self._matches:
            if match.icon is None:
                continue
            if match.disk.is_system and not self.include_system:
                continue
            path = match.resolved_path or match.icon.path
            jobs.extend(self._jobs_for_match(match, "apply", Path(path)))
        if not jobs:
            self.status.setText("No suggestions to apply.")
            return
        if not self._confirm(
            "Apply all suggestions",
            f"Apply matched icons to {len(jobs)} mount(s)?",
        ):
            return
        self._run_apply_jobs(jobs, "Applying all suggestions…")

    def _index_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select icons folder to index")
        if not folder:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        worker = IndexWorker(Path(folder), self.db_path, self)
        self._worker = worker
        self._set_busy(True, f"Indexing {folder}…")
        worker.finished_ok.connect(self._on_index_done)
        worker.failed.connect(self._on_index_failed)
        worker.start()

    def _on_index_done(self, n: int) -> None:
        self._set_busy(False)
        self.status.setText(f"Indexed {n} icon file(s).")
        self.refresh()

    def _on_index_failed(self, message: str) -> None:
        self._set_busy(False)
        self.status.setText(f"Index failed: {message}")
        QMessageBox.warning(self, "Index failed", message)

    def _elevate(self) -> None:
        if _restart_elevated_windows():
            self.status.setText("Elevation prompted — close this window after the new one opens.")
            QApplication.instance().quit()  # type: ignore[union-attr]
        else:
            QMessageBox.warning(
                self,
                "Elevation failed",
                "Could not relaunch as administrator. "
                "Start a terminal elevated and run:\n"
                "uv run python -m phofilesystemiconhelper gui",
            )


def run_disk_icon_manager(
    db_path: Path | str | None = None,
    include_system: bool = False,
) -> int:
    ensure_data_dirs()
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication(sys.argv)
    window = DiskIconManager(db_path=db_path, include_system=include_system)
    window.show()
    if owns_app:
        return app.exec()
    return 0
