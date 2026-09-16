from __future__ import annotations

import sys


def main() -> int:
    try:
        from keymouse.gui import run_app
    except ImportError as exc:
        if exc.name == "PySide6":
            print("缺少 GUI 组件。请先双击“安装依赖.bat”，或运行：python -m pip install -r requirements.txt")
            return 1
        raise
    return run_app()


if __name__ == "__main__":
    sys.exit(main())

