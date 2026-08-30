"""Dark theme and shared widget helpers."""

from __future__ import annotations

BG = "#16181d"
PANEL = "#1e2127"
PANEL_ALT = "#252932"
BORDER = "#333846"
TEXT = "#e6e8ee"
MUTED = "#8b93a6"
ACCENT = "#4d7cfe"
ACCENT_HOVER = "#6690ff"
OK = "#3fb950"
WARN = "#d29922"
BAD = "#f0616d"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {MUTED};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    color: {MUTED};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}
QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}
QPushButton#primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: white;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {PANEL_ALT}; color: {MUTED}; }}
QPushButton#danger:hover {{ border-color: {BAD}; color: {BAD}; }}
QProgressBar {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    height: 16px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QTabBar::tab {{
    background: transparent;
    padding: 9px 18px;
    color: {MUTED};
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabWidget::pane {{ border: none; }}
QTableWidget {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background: {PANEL_ALT};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    font-size: 11px;
    text-transform: uppercase;
}}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {PANEL_ALT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QLabel#hint {{ color: {MUTED}; font-size: 11px; }}
QLabel#heading {{ font-size: 15px; font-weight: 600; }}
QStatusBar {{ color: {MUTED}; border-top: 1px solid {BORDER}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""

STATE_COLOURS = {
    "created": MUTED,
    "transferring": ACCENT,
    "queued": WARN,
    "rendering": ACCENT,
    "encoded": OK,
    "returning": ACCENT,
    "complete": OK,
    "failed": BAD,
    "cancelled": MUTED,
}


def state_colour(state: str) -> str:
    return STATE_COLOURS.get(str(state).lower(), MUTED)
