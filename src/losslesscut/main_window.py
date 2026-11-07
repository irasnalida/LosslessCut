"""Main application window."""

from __future__ import annotations

from bisect import bisect_left
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QThreadPool, QUrl
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .exporter import Exporter
from .ffmpeg_utils import check_binaries
from .ffprobe import probe_keyframes, probe_media
from .icons import DEFAULT_COLOR, MUTED_COLOR, icon
from .models import (
    MediaInfo,
    Segment,
    format_size,
    format_timecode,
    nearest_keyframe,
    next_keyframe,
    previous_keyframe,
    split_segment,
)
from .preview import VideoPreview
from .segments import SegmentPanel
from .timeline import TimelinePanel
from .workers import Worker

_VIDEO_FILTER = (
    "Video files (*.mp4 *.mkv *.mov *.m4v *.avi *.webm *.ts *.m2ts *.mts *.flv *.wmv "
    "*.mpg *.mpeg *.3gp *.ogv *.vob);;All files (*.*)"
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LosslessCut")
        self.resize(1440, 900)
        self.setMinimumSize(940, 620)
        self.setAcceptDrops(True)

        self.settings = QSettings("LosslessCut", "LosslessCut")
        self.media: MediaInfo | None = None
        self.keyframes: list[float] = []
        self.segments: list[Segment] = []
        self.selected_segment = -1
        self.current_time = 0.0
        self.output_dir: Path | None = None
        self._load_id = 0
        self._probe_worker: Worker | None = None
        self._keyframe_worker: Worker | None = None
        self._keyframes_loading = False
        self._export_worker: Exporter | None = None
        self._export_dialog: QProgressDialog | None = None
        self._exporting = False
        self._recent_files: list[str] = []
        self._workers: list[Worker] = []
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._wire_signals()
        self._restore_settings()
        self._update_actions()
        self._update_metadata()
        self._report_binary_status()

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.preview = VideoPreview(self)
        self.segments_panel = SegmentPanel(self)
        self.timeline_panel = TimelinePanel(self)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self.preview)
        self.splitter.addWidget(self.segments_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([1040, 340])
        self.splitter.setChildrenCollapsible(False)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.timeline_panel, 0)
        layout.addWidget(self._build_transport(), 0)
        self.setCentralWidget(central)

    def _build_transport(self) -> QWidget:
        bar = QFrame(self)
        bar.setStyleSheet("QFrame { background: #202326; border-top: 1px solid #15181a; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(4)

        self.start_button = self._media_button(
            "skip-back", "Go to start (Home)", self._go_start
        )
        self.prev_keyframe_button = self._media_button(
            "caret-double-left",
            "Previous keyframe (Up)",
            lambda: self._jump_keyframe(-1),
        )
        self.frame_back_button = self._media_button(
            "caret-left", "Step back one frame (Left)", lambda: self._step_frames(-1)
        )
        self.play_button = self._media_button(
            "play", "Play / pause (Space)", self._toggle_play
        )
        self.frame_forward_button = self._media_button(
            "caret-right", "Step forward one frame (Right)", lambda: self._step_frames(1)
        )
        self.next_keyframe_button = self._media_button(
            "caret-double-right",
            "Next keyframe (Down)",
            lambda: self._jump_keyframe(1),
        )
        self.end_button = self._media_button(
            "skip-forward", "Go to end (End)", self._go_end
        )

        fixed_font = QFont("Inter")
        fixed_font.setPointSize(11)
        fixed_font.setFeature(QFont.Tag("tnum"), 1)
        self.time_label = QLabel("00:00:00.000", bar)
        self.time_label.setFont(fixed_font)
        self.time_label.setMinimumWidth(112)
        self.time_label.setStyleSheet("color: #e7eaec;")
        self.frame_label = QLabel("Frame 0", bar)
        self.frame_label.setObjectName("muted")
        self.percent_label = QLabel("0.0%", bar)
        self.percent_label.setObjectName("muted")
        self.keyframe_indicator = QLabel("No keyframes", bar)
        self.keyframe_indicator.setStyleSheet("color: #7f8a91;")

        for widget in (
            self.start_button,
            self.prev_keyframe_button,
            self.frame_back_button,
            self.play_button,
            self.frame_forward_button,
            self.next_keyframe_button,
            self.end_button,
        ):
            layout.addWidget(widget)

        layout.addSpacing(12)
        layout.addWidget(self.time_label)
        layout.addWidget(self.frame_label)
        layout.addWidget(self.percent_label)
        layout.addSpacing(12)
        layout.addWidget(self.keyframe_indicator)
        layout.addStretch(1)
        silent = QLabel("SILENT PREVIEW", bar)
        silent.setStyleSheet("color: #636b71; font-size: 10px; letter-spacing: 1px;")
        silent.setToolTip("Preview is decoded by ffmpeg without audio")
        layout.addWidget(silent)
        return bar

    def _media_button(
        self, name: str, tooltip: str, callback, color: str = DEFAULT_COLOR
    ) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(icon(name, color, 18))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setObjectName("flatButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def _build_actions(self) -> None:
        self.open_action = self._action(
            "&Open video…", "Ctrl+O", self._choose_video, "folder-open"
        )
        self.output_action = self._action(
            "Choose &output folder…", None, self._choose_output_dir, "folder-simple"
        )
        self.exit_action = self._action("E&xit", "Ctrl+Q", self.close)

        self.split_action = self._action(
            "&Split at playhead", "S", self._split_at_playhead, "scissors"
        )
        self.split_action.setToolTip("Split the active segment at the nearest keyframe")
        self.delete_action = self._action(
            "&Delete segment", "Del", self._delete_selected, "trash"
        )
        self.delete_action.setShortcuts([QKeySequence("Del"), QKeySequence("Backspace")])
        self.reset_action = self._action(
            "Reset to &full video", None, self._reset_segments, "arrow-counter-clockwise"
        )
        self.export_action = self._action(
            "&Export segments…", "Ctrl+E", lambda: self._start_export(), "export"
        )
        self.export_merged_action = self._action(
            "Export &merged…", "Ctrl+Shift+E", lambda: self._start_export("merge"), "git-merge"
        )

        self.play_action = self._action("Play / pause", "Space", self._toggle_play, "play")
        self.step_back_action = self._action(
            "Step back one frame", "Left", lambda: self._step_frames(-1)
        )
        self.step_forward_action = self._action(
            "Step forward one frame", "Right", lambda: self._step_frames(1)
        )
        self.second_back_action = self._action(
            "Jump back one second", "Shift+Left", lambda: self._step_seconds(-1.0)
        )
        self.second_forward_action = self._action(
            "Jump forward one second", "Shift+Right", lambda: self._step_seconds(1.0)
        )
        self.prev_keyframe_action = self._action(
            "Previous keyframe", "Up", lambda: self._jump_keyframe(-1)
        )
        self.next_keyframe_action = self._action(
            "Next keyframe", "Down", lambda: self._jump_keyframe(1)
        )
        self.start_action = self._action("Go to start", "Home", self._go_start)
        self.end_action = self._action("Go to end", "End", self._go_end)

        self.zoom_in_action = self._action(
            "Zoom &in", "+", lambda: self.timeline_panel.zoom_by(1.5), "magnifying-glass-plus"
        )
        self.zoom_in_action.setShortcuts([QKeySequence("+"), QKeySequence("=")])
        self.zoom_out_action = self._action(
            "Zoom &out",
            "-",
            lambda: self.timeline_panel.zoom_by(1 / 1.5),
            "magnifying-glass-minus",
        )
        self.fit_action = self._action(
            "&Fit timeline", "F", self.timeline_panel.fit, "arrows-out"
        )
        self.fullscreen_action = self._action("Toggle &full screen", "F11", self._toggle_fullscreen)

        self.copy_time_action = self._action("&Copy current timecode", "Ctrl+C", self._copy_timecode)
        self.about_action = self._action("&About LosslessCut", None, self._show_about)
        self.check_ffmpeg_action = self._action("Check &ffmpeg", None, self._show_binary_status)

        for action in (
            self.export_action,
            self.export_merged_action,
            self.split_action,
            self.delete_action,
            self.reset_action,
            self.play_action,
            self.step_back_action,
            self.step_forward_action,
            self.second_back_action,
            self.second_forward_action,
            self.prev_keyframe_action,
            self.next_keyframe_action,
            self.start_action,
            self.end_action,
            self.zoom_in_action,
            self.zoom_out_action,
            self.fit_action,
            self.copy_time_action,
        ):
            self.addAction(action)

    def _action(
        self,
        text: str,
        shortcut: str | None,
        callback,
        icon_name: str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if icon_name is not None:
            action.setIcon(icon(icon_name, DEFAULT_COLOR, 16))
        action.triggered.connect(callback)
        return action

    def _build_menus(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        file_menu.addAction(self.open_action)
        self.recent_menu = file_menu.addMenu("Open &recent")
        file_menu.addSeparator()
        file_menu.addAction(self.output_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = menu.addMenu("&Edit")
        edit_menu.addAction(self.copy_time_action)

        segment_menu = menu.addMenu("&Segments")
        segment_menu.addAction(self.split_action)
        segment_menu.addAction(self.delete_action)
        segment_menu.addAction(self.reset_action)
        segment_menu.addSeparator()
        segment_menu.addAction(self.export_action)
        segment_menu.addAction(self.export_merged_action)

        view_menu = menu.addMenu("&View")
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.fit_action)
        view_menu.addSeparator()
        view_menu.addAction(self.fullscreen_action)

        help_menu = menu.addMenu("&Help")
        help_menu.addAction(self.check_ffmpeg_action)
        help_menu.addAction(self.about_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        toolbar.addAction(self.open_action)
        toolbar.addSeparator()
        toolbar.addAction(self.split_action)
        toolbar.addAction(self.delete_action)
        toolbar.addSeparator()

        output_label = QLabel("Output:", toolbar)
        output_label.setObjectName("muted")
        toolbar.addWidget(output_label)
        self.output_button = QPushButton("Choose…", toolbar)
        self.output_button.setIcon(icon("folder-simple", MUTED_COLOR, 16))
        self.output_button.setIconSize(QSize(16, 16))
        self.output_button.setObjectName("flatButton")
        self.output_button.setMaximumWidth(300)
        self.output_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.output_button.setToolTip("Choose the export folder")
        self.output_button.clicked.connect(self._choose_output_dir)
        toolbar.addWidget(self.output_button)

        toolbar.addSeparator()
        self.all_tracks_checkbox = QCheckBox("All tracks", toolbar)
        self.all_tracks_checkbox.setChecked(True)
        self.all_tracks_checkbox.setToolTip(
            "Copy every stream (video, audio, subtitles). Disable if the output container "
            "cannot hold all tracks."
        )
        toolbar.addWidget(self.all_tracks_checkbox)

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        bar.showMessage("Ready")
        self.media_info_label = QLabel("No media")
        self.duration_label = QLabel("—")
        self.keyframe_count_label = QLabel("Keyframes: —")
        self.format_label = QLabel("")
        for label in (
            self.media_info_label,
            self._separator_label(),
            self.duration_label,
            self._separator_label(),
            self.keyframe_count_label,
            self._separator_label(),
            self.format_label,
        ):
            bar.addPermanentWidget(label)

    def _separator_label(self) -> QLabel:
        label = QLabel("│")
        label.setStyleSheet("color: #3b4248;")
        return label

    def _wire_signals(self) -> None:
        self.timeline_panel.seek_requested.connect(self._seek_to)
        self.timeline_panel.segment_selected.connect(self._select_segment)
        self.segments_panel.selection_changed.connect(self._select_segment)
        self.segments_panel.export_requested.connect(lambda: self._start_export())
        self.segments_panel.remove_requested.connect(self._remove_segment)
        self.segments_panel.segment_activated.connect(self._activate_segment)

        self.preview.position_changed.connect(self._on_preview_position)
        self.preview.playback_started.connect(self._on_playback_started)
        self.preview.playback_paused.connect(self._on_playback_paused)
        self.preview.playback_finished.connect(self._on_playback_finished)
        self.preview.error.connect(self._on_preview_error)

    # ----------------------------------------------------------- media loading
    def _choose_video(self) -> None:
        start = self.settings.value("last_dir", str(Path.home()), type=str)
        filename, _ = QFileDialog.getOpenFileName(self, "Open video", start, _VIDEO_FILTER)
        if filename:
            self.open_path(Path(filename))

    def open_path(self, path: Path) -> None:
        path = Path(path).expanduser()
        if not path.exists() or not path.is_file():
            QMessageBox.critical(self, "Open video", f"File not found:\n{path}")
            return
        status = check_binaries()
        if not status.ready:
            QMessageBox.critical(self, "ffmpeg not found", status.message)
            return

        self._load_id += 1
        token = self._load_id
        self.settings.setValue("last_dir", str(path.parent))
        self.settings.setValue("last_file", str(path))

        self.media = None
        self.keyframes = []
        self._keyframes_loading = False
        self.segments = []
        self.selected_segment = -1
        self.current_time = 0.0
        self.output_dir = path.parent
        self.preview.clear()
        self.timeline_panel.set_media(0.0, [], 0.0)
        self.segments_panel.set_segments([], None)
        self._update_output_label()
        self._update_time_labels()
        self._update_metadata()
        self._update_actions()
        self.setWindowTitle(f"Loading {path.name}… — LosslessCut")
        self.statusBar().showMessage(f"Probing {path.name}…")
        self.media_info_label.setText("Probing…")
        self.keyframe_count_label.setText("Keyframes: scanning…")

        worker = Worker(probe_media, path)
        worker.signals.finished.connect(lambda media, tok=token: self._on_media_probed(media, tok))
        worker.signals.failed.connect(
            lambda message, detail, tok=token: self._on_probe_failed(message, detail, tok)
        )
        self._probe_worker = worker
        self._workers.append(worker)
        self._pool.start(worker)

    def _on_media_probed(self, media: object, token: int) -> None:
        if token != self._load_id or not isinstance(media, MediaInfo):
            return
        self.media = media
        self.keyframes = [0.0]
        media.keyframes = self.keyframes
        self.segments = [Segment(0.0, media.duration, True)]
        self.selected_segment = 0
        self.current_time = 0.0
        self.preview.set_media(media)
        self.timeline_panel.set_media(media.duration, self.keyframes, media.fps)
        self._refresh_segments()
        self.setWindowTitle(f"{media.path.name} — LosslessCut")
        self._add_recent(media.path)
        self.statusBar().showMessage("Scanning keyframes…")

        worker = Worker(probe_keyframes, media)
        worker.signals.finished.connect(
            lambda keyframes, tok=token: self._on_keyframes_ready(keyframes, tok)
        )
        worker.signals.failed.connect(
            lambda message, detail, tok=token: self._on_keyframes_failed(message, detail, tok)
        )
        self._keyframe_worker = worker
        self._keyframes_loading = True
        self._workers.append(worker)
        self._pool.start(worker)

        self._update_metadata()
        self._update_time_labels()
        self._update_actions()

    def _on_keyframes_ready(self, keyframes: object, token: int) -> None:
        if token != self._load_id or not isinstance(keyframes, list):
            return
        self._keyframes_loading = False
        self.keyframes = sorted(float(value) for value in keyframes)
        if not self.keyframes:
            self.keyframes = [0.0]
        if self.media is not None:
            self.media.keyframes = self.keyframes
        self.timeline_panel.set_keyframes(self.keyframes)
        self.timeline_panel.set_segments(self.segments, self.selected_segment)
        self._update_metadata()
        self._update_time_labels()
        self._update_actions()
        self.statusBar().showMessage(
            f"Loaded {len(self.keyframes):,} keyframe boundaries"
        )

    def _on_probe_failed(self, message: str, detail: str, token: int) -> None:
        if token != self._load_id:
            return
        self.setWindowTitle("LosslessCut")
        self.media_info_label.setText("No media")
        self.statusBar().showMessage("Could not open the video")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Could not open video")
        box.setText(message)
        if detail:
            box.setDetailedText(detail)
        box.exec()

    def _on_keyframes_failed(self, message: str, detail: str, token: int) -> None:
        if token != self._load_id:
            return
        self._keyframes_loading = False
        self.keyframe_count_label.setText("Keyframes: unavailable")
        self.keyframe_count_label.setToolTip(detail or message)
        self.statusBar().showMessage(
            "Keyframe scan failed; splitting is unavailable for this file"
        )

    # ------------------------------------------------------------- navigation
    def _seek_to(self, value: float) -> None:
        if self.media is None:
            return
        value = min(max(0.0, value), max(0.0, self.media.duration - 1e-4))
        self.current_time = value
        self.preview.seek(value)
        self.timeline_panel.set_current_time(value)
        self._update_time_labels()

    def _on_preview_position(self, value: float) -> None:
        self.current_time = value
        self.timeline_panel.set_current_time(value)
        if self.preview.is_playing:
            self.timeline_panel.ensure_time_visible(value)
        self._update_time_labels()

    def _step_frames(self, count: int) -> None:
        if self.media is None:
            return
        fps = self.media.fps or 30.0
        if self.preview.is_playing:
            self.preview.pause(request_still=False)
        self._seek_to(self.current_time + count / fps)

    def _step_seconds(self, seconds: float) -> None:
        if self.media is None:
            return
        if self.preview.is_playing:
            self.preview.pause(request_still=False)
        self._seek_to(self.current_time + seconds)

    def _jump_keyframe(self, direction: int) -> None:
        if self.media is None or len(self.keyframes) < 2:
            return
        if self.preview.is_playing:
            self.preview.pause(request_still=False)
        target = (
            next_keyframe(self.keyframes, self.current_time)
            if direction > 0
            else previous_keyframe(self.keyframes, self.current_time)
        )
        if target is None:
            target = self.keyframes[-1] if direction > 0 else self.keyframes[0]
        self._seek_to(target)
        self.timeline_panel.ensure_time_visible(target)

    def _go_start(self) -> None:
        self._seek_to(0.0)
        self.timeline_panel.ensure_time_visible(0.0)

    def _go_end(self) -> None:
        if self.media is not None:
            self._seek_to(max(0.0, self.media.duration - 1e-4))
            self.timeline_panel.ensure_time_visible(self.current_time)

    def _toggle_play(self) -> None:
        if self.media is None:
            return
        self.preview.toggle_playback()

    def _on_playback_started(self) -> None:
        self._set_play_icon(True)
        self.current_time = self.preview.current_time
        self.timeline_panel.set_current_time(self.current_time)
        self._update_time_labels()

    def _on_playback_paused(self) -> None:
        self._set_play_icon(False)
        self.current_time = self.preview.current_time
        self.timeline_panel.set_current_time(self.current_time)
        self._update_time_labels()

    def _on_playback_finished(self) -> None:
        self._set_play_icon(False)
        self.current_time = self.preview.current_time
        self.timeline_panel.set_current_time(self.current_time)
        self._update_time_labels()

    def _on_preview_error(self, message: str) -> None:
        self.statusBar().showMessage(f"Preview: {message.splitlines()[0]}")

    def _set_play_icon(self, playing: bool) -> None:
        self.play_button.setIcon(icon("pause" if playing else "play", DEFAULT_COLOR, 18))
        self._update_actions()

    # ---------------------------------------------------------------- segments
    def _refresh_segments(self) -> None:
        self.segments_panel.set_segments(self.segments, self.media, self.selected_segment)
        self.timeline_panel.set_segments(self.segments, self.selected_segment)
        self.timeline_panel.set_current_time(self.current_time)
        self._update_actions()

    def _select_segment(self, index: int) -> None:
        if not (0 <= index < len(self.segments)):
            return
        self.selected_segment = index
        self.segments_panel.set_selected(index)
        self.timeline_panel.set_segments(self.segments, index)
        self._update_actions()

    def _activate_segment(self, index: int) -> None:
        if 0 <= index < len(self.segments):
            self._select_segment(index)
            self._seek_to(self.segments[index].start)
            self.timeline_panel.ensure_time_visible(self.current_time)

    def _split_at_playhead(self) -> None:
        if self.media is None or not self.segments:
            return
        target = -1
        if 0 <= self.selected_segment < len(self.segments) and self.segments[
            self.selected_segment
        ].contains(self.current_time):
            target = self.selected_segment
        else:
            for index, segment in enumerate(self.segments):
                if segment.contains(self.current_time):
                    target = index
                    break
        if target < 0:
            self.statusBar().showMessage("Move the playhead inside a segment to split it")
            return
        segment = self.segments[target]
        result = split_segment(segment, self.current_time, self.keyframes, self.media.fps)
        if result is None:
            self.statusBar().showMessage(
                "No usable keyframe boundary inside this segment at the playhead"
            )
            return
        left, right = result
        self.segments[target : target + 1] = [left, right]
        self.selected_segment = target + 1
        self._refresh_segments()
        self.statusBar().showMessage(
            f"Split at keyframe {format_timecode(left.end)}"
        )

    def _delete_selected(self) -> None:
        if not (0 <= self.selected_segment < len(self.segments)):
            return
        removed = self.segments.pop(self.selected_segment)
        if self.segments:
            self.selected_segment = min(self.selected_segment, len(self.segments) - 1)
        else:
            self.selected_segment = -1
        self._refresh_segments()
        self.statusBar().showMessage(
            f"Removed segment {format_timecode(removed.start)} – {format_timecode(removed.end)}"
        )

    def _remove_segment(self, index: int) -> None:
        self.selected_segment = index
        self._delete_selected()

    def _reset_segments(self) -> None:
        if self.media is None:
            return
        self.segments = [Segment(0.0, self.media.duration, True)]
        self.selected_segment = 0
        self._refresh_segments()
        self.statusBar().showMessage("Reset to one full-length segment")

    # ------------------------------------------------------------------ export
    def _choose_output_dir(self) -> None:
        start = self.output_dir or Path(
            self.settings.value("last_dir", str(Path.home()), type=str)
        )
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", str(start))
        if folder:
            self.output_dir = Path(folder)
            self.settings.setValue("last_dir", folder)
            self._update_output_label()
            self.statusBar().showMessage(f"Output folder: {folder}")

    def _start_export(self, mode_override: str | None = None) -> None:
        if self.media is None:
            return
        enabled_segments = [segment for segment in self.segments if segment.enabled]
        if not enabled_segments:
            QMessageBox.information(
                self,
                "Nothing to export",
                "Add at least one segment before exporting.",
            )
            return
        if self._exporting:
            return
        output_dir = self.output_dir or self.media.path.parent
        mode = mode_override or self.segments_panel.export_mode()

        dialog = QProgressDialog("Preparing lossless export…", "Cancel", 0, 100, self)
        dialog.setWindowTitle("Exporting")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        dialog.show()

        exporter = Exporter(
            self.media,
            enabled_segments,
            output_dir,
            mode=mode,
            all_tracks=self.all_tracks_checkbox.isChecked(),
            parent=self,
        )
        dialog.canceled.connect(self._cancel_export)
        exporter.progress.connect(self._on_export_progress)
        exporter.status.connect(self.statusBar().showMessage)
        exporter.finished.connect(lambda paths: self._on_export_finished(paths, dialog))
        exporter.failed.connect(lambda message, detail: self._on_export_failed(message, detail, dialog))
        exporter.cancelled.connect(lambda: self._on_export_cancelled(dialog))

        self._export_worker = exporter
        self._export_dialog = dialog
        self._exporting = True
        self.segments_panel.set_exporting(True)
        self._update_actions()
        self.statusBar().showMessage("Starting export…")
        exporter.start()

    def _cancel_export(self) -> None:
        if self._export_worker is not None:
            self._export_worker.cancel()

    def _on_export_progress(self, value: int, text: str) -> None:
        if self._export_dialog is not None:
            self._export_dialog.setValue(value)
            self._export_dialog.setLabelText(text)

    def _close_export_dialog(self) -> None:
        if self._export_dialog is not None:
            self._export_dialog.blockSignals(True)
            self._export_dialog.close()
            self._export_dialog.deleteLater()
            self._export_dialog = None
        self._export_worker = None
        self._exporting = False
        self.segments_panel.set_exporting(False)
        self._update_actions()

    def _on_export_finished(self, paths: object, dialog: QProgressDialog) -> None:
        self._close_export_dialog()
        if not isinstance(paths, list) or not paths:
            self.statusBar().showMessage("Export finished, but no files were reported")
            return
        output_paths = [Path(path) for path in paths]
        folder = output_paths[0].parent
        self.statusBar().showMessage(f"Exported {len(output_paths)} file(s) to {folder}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Export complete")
        box.setText(f"Exported {len(output_paths)} file(s).")
        box.setInformativeText(
            f"Output folder:\n{folder}\n\n" + "\n".join(path.name for path in output_paths[:12])
        )
        open_button = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_export_failed(
        self, message: str, detail: str, dialog: QProgressDialog
    ) -> None:
        self._close_export_dialog()
        self.statusBar().showMessage("Export failed")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Export failed")
        box.setText(message)
        if detail:
            box.setDetailedText(detail)
        box.exec()

    def _on_export_cancelled(self, dialog: QProgressDialog) -> None:
        self._close_export_dialog()
        self.statusBar().showMessage("Export cancelled")

    # ------------------------------------------------------------------ misc
    def _update_time_labels(self) -> None:
        if self.media is None:
            self.time_label.setText("00:00:00.000")
            self.frame_label.setText("Frame 0")
            self.percent_label.setText("0.0%")
            self.keyframe_indicator.setText("No keyframes")
            self.keyframe_indicator.setStyleSheet("color: #7f8a91;")
            return
        fps = self.media.fps or 30.0
        frame = round(self.current_time * fps)
        percent = (self.current_time / self.media.duration * 100.0) if self.media.duration else 0.0
        self.time_label.setText(format_timecode(self.current_time))
        self.frame_label.setText(f"Frame {frame:,}")
        self.percent_label.setText(f"{percent:.1f}%")

        if not self.keyframes:
            self.keyframe_indicator.setText("No keyframes")
            self.keyframe_indicator.setStyleSheet("color: #7f8a91;")
            return
        index = bisect_left(self.keyframes, self.current_time - 0.0015)
        if index < len(self.keyframes) and abs(self.keyframes[index] - self.current_time) <= 0.0015:
            self.keyframe_indicator.setText(f"◆ Keyframe {index + 1:,}/{len(self.keyframes):,}")
            self.keyframe_indicator.setStyleSheet("color: #39b9c9;")
        else:
            near = nearest_keyframe(self.keyframes, self.current_time)
            text = f"Nearest keyframe {format_timecode(near)}" if near is not None else "No keyframes"
            self.keyframe_indicator.setText(text)
            self.keyframe_indicator.setStyleSheet("color: #7f8a91;")

    def _update_metadata(self) -> None:
        if self.media is None:
            self.media_info_label.setText("No media")
            self.media_info_label.setToolTip("")
            self.duration_label.setText("—")
            self.keyframe_count_label.setText("Keyframes: —")
            self.keyframe_count_label.setToolTip("")
            self.format_label.setText("")
            return
        media = self.media
        display_width, display_height = media.display_size
        codec = media.video_codec or "video"
        fps = f"{media.fps:.3g} fps" if media.fps else "unknown fps"
        self.media_info_label.setText(f"{codec} · {display_width}×{display_height} · {fps}")
        self.duration_label.setText(
            f"{format_timecode(media.duration)} · {format_size(media.size)}"
        )
        if self._keyframes_loading:
            self.keyframe_count_label.setText("Keyframes: scanning…")
        elif media.keyframes:
            self.keyframe_count_label.setText(f"Keyframes: {len(media.keyframes):,}")
        else:
            self.keyframe_count_label.setText("Keyframes: —")
        self.keyframe_count_label.setToolTip(
            "Keyframe boundary data is read directly from the video packets."
        )
        self.format_label.setText(media.format_name.split(",")[0] if media.format_name else "")
        tracks = "\n".join(stream.label for stream in media.streams)
        self.media_info_label.setToolTip(
            f"{media.path}\n\n{tracks}\n\nContainer: {media.format_name}"
        )

    def _update_actions(self) -> None:
        has_media = self.media is not None
        has_segments = bool(self.segments)
        selected = 0 <= self.selected_segment < len(self.segments)
        busy = self._exporting
        for action in (
            self.split_action,
            self.delete_action,
            self.reset_action,
            self.play_action,
            self.step_back_action,
            self.step_forward_action,
            self.second_back_action,
            self.second_forward_action,
            self.prev_keyframe_action,
            self.next_keyframe_action,
            self.start_action,
            self.end_action,
            self.zoom_in_action,
            self.zoom_out_action,
            self.fit_action,
            self.copy_time_action,
        ):
            action.setEnabled(has_media)
        self.delete_action.setEnabled(has_media and selected and not busy)
        self.export_action.setEnabled(has_media and has_segments and not busy)
        self.export_merged_action.setEnabled(has_media and has_segments and not busy)
        self.split_action.setEnabled(has_media and has_segments and not busy)
        self.reset_action.setEnabled(has_media and not busy)
        self.segments_panel.export_button.setEnabled(has_media and has_segments and not busy)
        self.segments_panel.mode_combo.setEnabled(not busy)
        for button in (
            self.start_button,
            self.prev_keyframe_button,
            self.frame_back_button,
            self.play_button,
            self.frame_forward_button,
            self.next_keyframe_button,
            self.end_button,
        ):
            button.setEnabled(has_media)

    def _update_output_label(self) -> None:
        if self.output_dir is None:
            self.output_button.setText("Choose…")
            self.output_button.setToolTip("Choose the export folder")
            return
        self.output_button.setText(self.output_dir.name or str(self.output_dir))
        self.output_button.setToolTip(str(self.output_dir))

    def _copy_timecode(self) -> None:
        if self.media is None:
            return
        QApplication.clipboard().setText(format_timecode(self.current_time))
        self.statusBar().showMessage("Copied current timecode", 2000)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About LosslessCut",
            "<b>LosslessCut</b><br>"
            "A keyframe-based lossless video cutter.<br><br>"
            "Cuts and merges use ffmpeg stream copy, so the video is never re-encoded. "
            "Preview frames are decoded by ffmpeg and are silent.<br><br>"
            "Built with PySide6.",
        )

    def _show_binary_status(self) -> None:
        status = check_binaries()
        QMessageBox.information(self, "ffmpeg status", status.message)

    def _report_binary_status(self) -> None:
        status = check_binaries()
        if not status.ready:
            self.statusBar().showMessage(status.message)
            self.media_info_label.setText("ffmpeg missing")

    # -------------------------------------------------------------- recent files
    def _add_recent(self, path: Path) -> None:
        text = str(path)
        if text in self._recent_files:
            self._recent_files.remove(text)
        self._recent_files.insert(0, text)
        self._recent_files = self._recent_files[:8]
        self.settings.setValue("recent_files", self._recent_files)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        existing = [value for value in self._recent_files if Path(value).exists()]
        for value in existing:
            action = self.recent_menu.addAction(Path(value).name)
            action.setToolTip(value)
            action.triggered.connect(lambda checked=False, p=value: self.open_path(Path(p)))
        if not existing:
            empty = self.recent_menu.addAction("No recent files")
            empty.setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            clear = self.recent_menu.addAction("Clear recent files")
            clear.triggered.connect(self._clear_recent)

    def _clear_recent(self) -> None:
        self._recent_files = []
        self.settings.setValue("recent_files", [])
        self._rebuild_recent_menu()

    # -------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        if not paths:
            return
        event.acceptProposedAction()
        self.open_path(paths[0])

    # ---------------------------------------------------------------- settings
    def _restore_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.settings.value("window/splitter")
        if state is not None:
            self.splitter.restoreState(state)
        all_tracks = self.settings.value("export/all_tracks", True, type=bool)
        self.all_tracks_checkbox.setChecked(all_tracks)
        raw_recent = self.settings.value("recent_files", [])
        if isinstance(raw_recent, str):
            raw_recent = [raw_recent]
        self._recent_files = [str(value) for value in (raw_recent or [])][:8]
        self._rebuild_recent_menu()

    def _save_settings(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/splitter", self.splitter.saveState())
        self.settings.setValue("export/all_tracks", self.all_tracks_checkbox.isChecked())

    def closeEvent(self, event: QCloseEvent) -> None:
        self.preview.shutdown()
        if self._export_worker is not None:
            self._export_worker.cancel()
        self._save_settings()
        super().closeEvent(event)
