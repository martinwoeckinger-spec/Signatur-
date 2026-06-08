"""Baut aus index.html + styles.css + app.js + data.js eine einzelne HTML-Datei.

    python webapp/build.py   ->  webapp/demo.html (eigenstaendig, ohne Server)
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent


def _inline_js(src: str) -> str:
    # </script> im eingebetteten JS neutralisieren
    return src.replace("</script>", "<\\/script>")


def main() -> None:
    html = (HERE / "index.html").read_text(encoding="utf-8")
    css = (HERE / "styles.css").read_text(encoding="utf-8")
    app = _inline_js((HERE / "app.js").read_text(encoding="utf-8"))
    data = _inline_js((HERE / "data.js").read_text(encoding="utf-8"))

    html = html.replace('<link rel="stylesheet" href="styles.css">',
                        "<style>\n" + css + "\n</style>")
    html = html.replace('<script src="app.js"></script>',
                        "<script>\n" + app + "\n</script>")
    html = html.replace('<script src="data.js"></script>',
                        "<script>\n" + data + "\n</script>")

    out = HERE / "demo.html"
    out.write_text(html, encoding="utf-8")
    print(f"geschrieben: {out} ({out.stat().st_size} Bytes)")
    # Sanity-Checks
    assert "href=\"styles.css\"" not in html, "CSS nicht inlined"
    assert 'src="app.js"' not in html, "app.js nicht inlined"
    assert 'src="data.js"' not in html, "data.js nicht inlined"
    print("OK – eigenständig (keine externen Referenzen).")


if __name__ == "__main__":
    main()
