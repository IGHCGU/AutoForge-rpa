"""AutoForge high-contrast Endfield-inspired UI tokens.

The implementation is original Qt/QSS and contains no third-party artwork,
logos, production bundles, or redistributed fonts.
"""


def studio_style() -> str:
    """Return the single, application-wide dark visual system."""
    return """
        QWidget {
            color: #F5F5F2;
            font-family: 'Microsoft YaHei UI', 'Microsoft YaHei';
            font-size: 13px;
        }
        QMainWindow, QDialog { background: #121316; }
        QWidget#stageCanvas { background: #121316; }
        QWidget#panel {
            background: transparent;
            border: none;
        }
        QWidget#propertyBody { background: #1A1C20; }
        QWidget#inspectorSection {
            background: #181A1F;
            border: 1px solid #2E323A;
        }
        QWidget#inspectorSectionContent {
            background: #1A1C20;
            border: none;
        }
        QLabel#parameterLabel {
            color: #D7D9DE;
            font-weight: 600;
            padding-left: 2px;
        }
        QLabel#inlineFieldLabel {
            color: #8E939D;
            font-family: 'Consolas';
            font-size: 10px;
            font-weight: 700;
        }
        QLabel#sectionTitle {
            color: #FFFFFF;
            font-family: 'Arial Narrow', 'Microsoft YaHei UI';
            font-size: 20px;
            font-weight: 800;
            padding: 3px 0;
        }
        QLabel#sectionMicro {
            color: #FFE600;
            font-family: 'Consolas';
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 2px;
        }
        QLabel#panelWatermark {
            color: rgba(255, 255, 255, 0.08);
            font-family: 'Impact', 'Arial Black', 'Microsoft YaHei UI';
            font-size: 46px;
            font-weight: 900;
            padding: 0;
        }
        QLabel#subtitle { color: #A7A7AA; padding: 4px 0; }
        QMenuBar {
            background: #0B0C0E;
            color: #FFFFFF;
            border-bottom: 1px solid #FFFFFF;
            padding: 3px 10px;
        }
        QMenuBar::item { color: #FFFFFF; padding: 6px 11px; }
        QMenuBar::item:selected { background: #FFE600; color: #000000; }
        QMenu, QComboBox QAbstractItemView {
            background: #15171B;
            color: #FFFFFF;
            border: 1px solid #FFFFFF;
            selection-background-color: #FFE600;
            selection-color: #000000;
        }
        QMenu::item { padding: 10px 28px; }
        QMenu::item:selected { background: #FFE600; color: #000000; }
        QMenu::item:disabled { color: #66666A; }
        QToolBar#studioToolbar {
            background: #0B0C0E;
            border: none;
            border-bottom: 1px solid #2E323A;
            spacing: 6px;
            padding: 7px 12px;
        }
        QToolBar::separator { background: #2E323A; width: 1px; margin: 7px 5px; }
        QPushButton, QToolButton {
            background: #15171B;
            color: #FFFFFF;
            border: 1px solid #3A3F4D;
            border-radius: 0;
            padding: 7px 11px;
            min-height: 24px;
        }
        QToolBar#studioToolbar QToolButton {
            background: #15171B;
            border-color: #3A3F4D;
            font-weight: 600;
        }
        QPushButton:hover, QToolButton:hover {
            background: #FFE600;
            color: #000000;
            border-color: #FFE600;
        }
        QPushButton:pressed, QToolButton:pressed { background: #FFFFFF; color: #000000; }
        QPushButton#microAdjustButton,
        QPushButton#microAdjustCompactButton {
            background: #15171B;
            color: #FFFFFF;
            border: 1px solid #3A3F4D;
            padding: 0;
            font-family: 'Consolas';
            font-size: 14px;
            font-weight: 700;
        }
        QPushButton#microAdjustButton { min-width: 34px; max-width: 34px; }
        QPushButton#microAdjustCompactButton { min-width: 20px; max-width: 20px; }
        QPushButton#microAdjustButton:hover,
        QPushButton#microAdjustCompactButton:hover {
            background: #FFE600;
            color: #000000;
            border-color: #FFE600;
        }
        QPushButton:checked, QToolButton:checked {
            background: #FFE600;
            color: #000000;
            border-color: #FFE600;
            font-weight: 800;
        }
        QToolBar#studioToolbar QToolButton#tagButton {
            background: #15171B;
            border: 1px solid #3A3F4D;
            border-left: 4px solid #FFE600;
            padding: 6px 10px;
        }
        QToolBar#studioToolbar QToolButton#stopButton {
            color: #FFFFFF;
            border-color: #FFFFFF;
            font-weight: 700;
        }
        QToolBar#studioToolbar QToolButton:hover,
        QToolBar#studioToolbar QToolButton#tagButton:hover,
        QToolBar#studioToolbar QToolButton#stopButton:hover {
            background: #FFE600;
            color: #000000;
            border-color: #FFE600;
        }
        QPushButton#inspectorSectionHeader {
            background: #15171B;
            color: #C5C8D0;
            border: none;
            border-left: 3px solid #3A3F4D;
            border-bottom: 1px solid #2E323A;
            text-align: left;
            padding: 2px 9px;
            min-height: 22px;
            font-family: 'Consolas', 'Microsoft YaHei UI';
            font-size: 11px;
            font-weight: 700;
        }
        QPushButton#inspectorSectionHeader:checked {
            background: #15171B;
            color: #FFFFFF;
            border-left-color: #FFE600;
        }
        QPushButton#inspectorSectionHeader:hover {
            background: #252930;
            color: #FFFFFF;
            border-left-color: #FFE600;
            border-bottom-color: #3A3F4D;
        }
        QPushButton:disabled, QToolButton:disabled, QMenu::item:disabled {
            color: #66666A;
            background: #1A1C20;
            border-color: #2E323A;
        }
        QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus,
        QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus,
        QTableWidget:focus, QTreeWidget:focus {
            border: 2px solid #FFE600;
        }
        QTableWidget, QTreeWidget, QPlainTextEdit {
            background: #1D2025;
            alternate-background-color: #1A1C20;
            color: #C5C8D0;
            border: 1px solid #2E323A;
            border-radius: 0;
            selection-background-color: #252930;
            selection-color: #FFFFFF;
            gridline-color: transparent;
        }
        QTableWidget::item { padding: 7px; border: none; border-bottom: 1px solid #282C34; }
        QTreeWidget::item { padding: 9px; border-bottom: 1px solid #282C34; }
        QTreeWidget::item:selected { background: #FFE600; color: #000000; }
        QHeaderView::section {
            background: #15171B;
            color: #AFAFB3;
            border: none;
            border-bottom: 1px solid #2E323A;
            padding: 9px 7px;
            font-size: 11px;
            font-weight: 700;
        }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background: #15171B;
            color: #FFFFFF;
            border: 1px solid #3A3F4D;
            border-radius: 0;
            padding: 7px;
            min-height: 24px;
            selection-background-color: #FFE600;
            selection-color: #000000;
        }
        QWidget#propertyBody QLineEdit,
        QWidget#propertyBody QComboBox,
        QWidget#propertyBody QSpinBox,
        QWidget#propertyBody QDoubleSpinBox {
            padding: 5px 6px;
            min-height: 22px;
        }
        QWidget#propertyBody QPushButton {
            padding: 5px 8px;
            min-height: 22px;
        }
        QWidget#propertyBody QPushButton#pickPositionButton {
            padding: 5px 2px;
        }
        QWidget#propertyBody QPushButton#microAdjustButton,
        QWidget#propertyBody QPushButton#microAdjustCompactButton {
            min-height: 22px;
            padding: 0;
        }
        QLineEdit:read-only { color: #B8BBC4; background: #17191D; }
        QComboBox::drop-down { background: #15171B; border: none; border-left: 1px solid #3A3F4D; width: 28px; }
        QComboBox::drop-down:hover { background: #252930; border-left-color: #FFE600; }
        QComboBox::drop-down:disabled { background: #1A1C20; border-left-color: #2E323A; }
        QComboBox::down-arrow { width: 0; height: 0; }
        QScrollArea { border: none; background: #1A1C20; }
        QCheckBox { spacing: 10px; padding: 5px 0; }
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
            border: 2px solid #FFFFFF;
            background: #15171B;
        }
        QCheckBox::indicator:hover { border-color: #FFE600; }
        QCheckBox::indicator:checked { background: #FFE600; border: 4px solid #000000; }
        QScrollBar:vertical { background: #15171B; width: 11px; margin: 0; }
        QScrollBar::handle:vertical { background: #66666A; min-height: 28px; }
        QScrollBar::handle:vertical:hover { background: #FFE600; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        QScrollBar:horizontal { background: #15171B; height: 11px; }
        QScrollBar::handle:horizontal { background: #66666A; min-width: 28px; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QSplitter::handle { background: #121316; }
        QSplitter::handle:horizontal { width: 14px; }
        QTabWidget::pane { border: 1px solid #2E323A; background: #1A1C20; }
        QTabBar::tab {
            background: #15171B;
            color: #AFAFB3;
            padding: 11px 25px;
            border: none;
            border-bottom: 3px solid #2E323A;
            font-weight: 700;
        }
        QTabBar::tab:selected { color: #000000; background: #FFE600; border-bottom-color: #FFE600; }
        QStatusBar {
            background: #0B0C0E;
            color: #E8E8E5;
            border-top: 1px solid #2E323A;
            padding: 3px 10px;
        }
        QStatusBar QLabel { color: #E8E8E5; font-family: 'Consolas'; font-size: 11px; }
        QPushButton#logToggle {
            text-align: left;
            background: #15171B;
            color: #FFFFFF;
            border: none;
            border-left: 5px solid #FFE600;
            border-bottom: 1px solid #2E323A;
            font-family: 'Arial Narrow', 'Microsoft YaHei UI';
            font-weight: 800;
            padding-left: 12px;
        }
        QWidget#focusPixel { background: #FFE600; border: none; }
        QToolTip { background: #FFE600; color: #000000; border: 1px solid #FFFFFF; padding: 8px; }
    """
