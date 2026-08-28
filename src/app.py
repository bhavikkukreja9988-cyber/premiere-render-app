from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QProgressBar, QStackedWidget, QVBoxLayout, QWidget

from .core.workflow import Workflow, WorkflowState
from .network.session import DEFAULT_PORT, NetworkSession, Peer, local_ipv4_addresses
from .render.media_encoder import MediaEncoder


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def run(self, fn) -> None:
        try:
            result = fn(self.progress.emit)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class PremiereRenderApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.workflow = Workflow()
        self.session = NetworkSession()
        self.encoder = MediaEncoder()
        self.selected_project: Path | None = None
        self.selected_output: Path | None = None
        self.server_socket = None
        self.setWindowTitle("Premiere Render App")
        self.resize(1050, 700)
        self._build_ui()
        self._refresh_status()

    def _build_ui(self) -> None:
        root = QWidget()
        main = QVBoxLayout(root)
        main.setContentsMargins(26, 22, 26, 22)
        main.setSpacing(18)
        header = QHBoxLayout()
        title = QLabel("Premiere Render App")
        title.setObjectName("title")
        subtitle = QLabel("Direct PC-to-PC Premiere rendering")
        subtitle.setObjectName("subtitle")
        header.addWidget(title); header.addStretch(); header.addWidget(subtitle); main.addLayout(header)
        self.pages = QStackedWidget()
        self.home_page = self._make_home(); self.sender_page = self._make_sender(); self.receiver_page = self._make_receiver()
        self.pages.addWidget(self.home_page); self.pages.addWidget(self.sender_page); self.pages.addWidget(self.receiver_page); main.addWidget(self.pages, 1)
        status = QFrame(); status.setObjectName("statusFrame"); status_layout = QHBoxLayout(status)
        self.status_label = QLabel("Ready"); self.network_label = QLabel("Network: not connected"); self.encoder_label = QLabel("Media Encoder: checking…")
        status_layout.addWidget(self.status_label); status_layout.addStretch(); status_layout.addWidget(self.network_label); status_layout.addWidget(self.encoder_label); main.addWidget(status)
        self.setCentralWidget(root)
        self.setStyleSheet("""
        QWidget { font-size: 14px; } QMainWindow { background: #111318; } QLabel { color: #e9edf5; }
        #title { font-size: 30px; font-weight: 700; } #subtitle { color: #8f98aa; }
        QFrame#card, QFrame#statusFrame { background: #191c23; border: 1px solid #2a2f3a; border-radius: 14px; }
        QFrame#statusFrame { padding: 5px; } QPushButton { background: #2b6df3; color: white; border: none; border-radius: 9px; padding: 11px 17px; font-weight: 600; }
        QPushButton:hover { background: #3a79f5; } QPushButton:disabled { background: #343943; color: #7e8799; }
        QLineEdit { background: #0e1014; color: white; border: 1px solid #303642; border-radius: 8px; padding: 10px; }
        QProgressBar { background: #0d0f13; border: 1px solid #303642; border-radius: 8px; height: 14px; text-align: center; color: white; }
        QProgressBar::chunk { background: #2b6df3; border-radius: 7px; }
        """)

    def _make_card(self, title: str, body: str, button_text: str, handler):
        card = QFrame(); card.setObjectName("card"); layout = QVBoxLayout(card)
        label = QLabel(title); label.setStyleSheet("font-size: 21px; font-weight: 700;")
        desc = QLabel(body); desc.setWordWrap(True); desc.setStyleSheet("color: #9da5b5;")
        button = QPushButton(button_text); button.clicked.connect(handler)
        layout.addWidget(label); layout.addWidget(desc); layout.addStretch(); layout.addWidget(button); return card

    def _make_home(self):
        page = QWidget(); grid = QGridLayout(page); grid.setSpacing(18)
        grid.addWidget(self._make_card("Send to Render Station", "Choose a Premiere project folder and send it directly to another Windows PC running this app.", "Use Sender Mode", lambda: self.pages.setCurrentWidget(self.sender_page)), 0, 0)
        grid.addWidget(self._make_card("Render Station", "Put this PC online, receive a project, launch Adobe Media Encoder and return the finished file.", "Use Render Station", lambda: self.pages.setCurrentWidget(self.receiver_page)), 0, 1)
        info = QLabel("Local IP addresses: " + ", ".join(local_ipv4_addresses()) + f"\nDefault port: {DEFAULT_PORT}")
        info.setStyleSheet("color:#8f98aa; padding:10px;"); grid.addWidget(info, 1, 0, 1, 2); return page

    def _make_sender(self):
        page = QWidget(); layout = QVBoxLayout(page)
        back = QPushButton("← Home"); back.clicked.connect(lambda: self.pages.setCurrentWidget(self.home_page)); layout.addWidget(back, 0, Qt.AlignLeft)
        title = QLabel("Sender"); title.setStyleSheet("font-size:24px;font-weight:700;"); layout.addWidget(title)
        form = QGridLayout(); self.project_edit = QLineEdit(); browse = QPushButton("Browse"); browse.clicked.connect(self._browse_project)
        form.addWidget(QLabel("Premiere project folder"), 0, 0); form.addWidget(self.project_edit, 0, 1); form.addWidget(browse, 0, 2)
        self.host_edit = QLineEdit(); self.host_edit.setPlaceholderText("192.168.1.50"); self.port_edit = QLineEdit(str(DEFAULT_PORT))
        form.addWidget(QLabel("Render Station"), 1, 0); form.addWidget(self.host_edit, 1, 1); form.addWidget(self.port_edit, 1, 2); layout.addLayout(form)
        self.send_progress = QProgressBar(); self.send_message = QLabel("Select a project folder and connect."); self.send_button = QPushButton("Connect & Send"); self.send_button.clicked.connect(self._send_project)
        layout.addWidget(self.send_progress); layout.addWidget(self.send_message); layout.addStretch(); layout.addWidget(self.send_button); return page

    def _make_receiver(self):
        page = QWidget(); layout = QVBoxLayout(page); back = QPushButton("← Home"); back.clicked.connect(lambda: self.pages.setCurrentWidget(self.home_page)); layout.addWidget(back, 0, Qt.AlignLeft)
        title = QLabel("Render Station"); title.setStyleSheet("font-size:24px;font-weight:700;"); layout.addWidget(title)
        self.output_edit = QLineEdit(); browse = QPushButton("Browse"); browse.clicked.connect(self._browse_output); row = QHBoxLayout()
        row.addWidget(QLabel("Incoming / output folder")); row.addWidget(self.output_edit); row.addWidget(browse); layout.addLayout(row)
        ips = QLabel("This PC: " + ", ".join(local_ipv4_addresses())); ips.setStyleSheet("color:#8f98aa;"); layout.addWidget(ips)
        self.online_button = QPushButton("Go Online"); self.online_button.clicked.connect(self._toggle_online); self.receiver_status = QLabel("Offline"); self.receiver_status.setStyleSheet("font-size:18px;font-weight:600;")
        layout.addWidget(self.receiver_status); layout.addStretch(); layout.addWidget(self.online_button); return page

    def _refresh_status(self) -> None:
        info = self.encoder.detect(); self.encoder_label.setText("Media Encoder: " + ("Detected" if info.found else "Not detected"))

    def _browse_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Premiere Project Folder")
        if folder: self.selected_project = Path(folder); self.project_edit.setText(folder)

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder: self.selected_output = Path(folder); self.output_edit.setText(folder)

    def _send_project(self) -> None:
        project = Path(self.project_edit.text().strip()); host = self.host_edit.text().strip()
        try: port = int(self.port_edit.text().strip())
        except ValueError: QMessageBox.warning(self, "Invalid Port", "Enter a valid TCP port."); return
        if not project.is_dir(): QMessageBox.warning(self, "Project Folder", "Choose a valid Premiere project folder."); return
        if not host: QMessageBox.warning(self, "Render Station", "Enter the render station IP address."); return
        self.send_button.setEnabled(False); self.workflow.update(WorkflowState.CONNECTING, "Connecting…"); self.send_message.setText(f"Connecting to {host}:{port}…")
        self._run_background(lambda progress: self._send_worker(project, host, port, progress), self._send_finished)

    def _send_worker(self, project: Path, host: str, port: int, progress):
        session = NetworkSession(); session.connect(Peer(host, port)); files = [p for p in project.rglob("*") if p.is_file()]; total_bytes = sum(p.stat().st_size for p in files); done = 0
        session.send_json({"type": "project-start", "name": project.name, "file_count": len(files), "total_bytes": total_bytes})
        for file in files:
            rel = file.relative_to(project).as_posix(); session.send_json({"type": "project-file", "path": rel, "size": file.stat().st_size})
            with file.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    session.socket.sendall(len(chunk).to_bytes(4, "big") + chunk); done += len(chunk); progress(int(done * 100 / total_bytes) if total_bytes else 100, rel)
        session.send_json({"type": "project-end"}); response = session.recv_json(); session.disconnect(); return response

    def _run_background(self, fn, finished):
        thread = QThread(self); worker = Worker(); worker.moveToThread(thread); thread.started.connect(lambda: worker.run(fn)); worker.progress.connect(self._progress); worker.finished.connect(finished); worker.failed.connect(self._failed); worker.finished.connect(thread.quit); worker.failed.connect(thread.quit); thread.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater); self._thread = thread; thread.start()

    @Slot(int, str)
    def _progress(self, value: int, text: str) -> None:
        self.send_progress.setValue(value); self.send_message.setText(text); self.workflow.update(WorkflowState.TRANSFERRING, text, value)

    def _send_finished(self, response) -> None:
        self.send_button.setEnabled(True)
        if response.get("ok"):
            self.send_progress.setValue(100); self.send_message.setText("Project transferred successfully."); self.workflow.update(WorkflowState.COMPLETED, "Project transferred", 100); QMessageBox.information(self, "Transfer Complete", "The project was sent to the render station.")
        else: self._failed(response.get("error", "Transfer failed"))

    def _failed(self, message: str) -> None:
        self.send_button.setEnabled(True); self.status_label.setText("Error: " + message); self.workflow.update(WorkflowState.ERROR, message); QMessageBox.critical(self, "Operation Failed", message)

    def _toggle_online(self) -> None:
        if self.server_socket is not None:
            self.server_socket.close(); self.server_socket = None; self.online_button.setText("Go Online"); self.receiver_status.setText("Offline"); self.network_label.setText("Network: not connected"); return
        output = Path(self.output_edit.text().strip()) if self.output_edit.text().strip() else Path.home() / "PremiereRenderIncoming"; self.output_edit.setText(str(output)); output.mkdir(parents=True, exist_ok=True); self._start_server(output)

    def _start_server(self, output: Path) -> None:
        import socket, threading
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); server.bind(("0.0.0.0", DEFAULT_PORT)); server.listen(8); self.server_socket = server
        self.online_button.setText("Go Offline"); self.receiver_status.setText(f"Online on port {DEFAULT_PORT}"); self.network_label.setText("Network: online")
        def loop():
            while self.server_socket is server:
                try: conn, address = server.accept()
                except OSError: break
                threading.Thread(target=self._handle_sender, args=(conn, address, output), daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()

    def _handle_sender(self, conn, address, output: Path) -> None:
        session = NetworkSession(sock=conn)
        try:
            header = session.recv_json()
            if header.get("type") != "project-start": raise ValueError("Unsupported request")
            project_root = output / f"received_{header.get('name', 'project')}"
            for _ in range(int(header.get("file_count", 0))):
                meta = session.recv_json()
                if meta.get("type") != "project-file": raise ValueError("Invalid project file message")
                rel = Path(str(meta["path"]))
                if rel.is_absolute() or ".." in rel.parts: raise ValueError("Unsafe file path")
                target = project_root / rel; target.parent.mkdir(parents=True, exist_ok=True); remaining = int(meta["size"])
                with target.open("wb") as handle:
                    while remaining:
                        length = int.from_bytes(session._read_exact(4), "big")
                        if length <= 0 or length > remaining: raise ValueError("Invalid chunk")
                        handle.write(session._read_exact(length)); remaining -= length
            if session.recv_json().get("type") != "project-end": raise ValueError("Project transfer did not finish correctly")
            encoder = self.encoder.detect(); session.send_json({"ok": True, "message": "Received; Media Encoder " + ("detected" if encoder.found else "not detected"), "project": str(project_root)})
        except Exception as exc:
            try: session.send_json({"ok": False, "error": str(exc)})
            except Exception: pass
        finally: session.disconnect()

    def closeEvent(self, event) -> None:
        if self.server_socket:
            try: self.server_socket.close()
            except OSError: pass
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv); window = PremiereRenderApp(); window.show(); return app.exec()