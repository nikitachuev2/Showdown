from __future__ import annotations

import sys
import traceback

from showdown_app.bootstrap import build_context


def main() -> int:
    try:
        import wx
    except Exception:
        print(
            "wxPython is required to run the GUI. "
            "Install dependencies from requirements.txt or use build.bat.",
            file=sys.stderr,
        )
        return 2

    import showdown_app.ui.app as ui_app
    from showdown_app.ui import enhancements as _ui_enhancements  # noqa: F401

    context = build_context()
    app = ui_app.ShowdownWxApp(False, context)
    app.MainLoop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise
