"""Build local guide pages and API documentation for GitHub Pages."""

import argparse
import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    import markdown2

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pdoc",
            "india_trader",
            "!india_trader.__main__",
            "-o",
            str(output / "api"),
        ],
        cwd=ROOT,
        check=True,
    )
    sources = [
        ROOT / name
        for name in (
            "README.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "NOTICE.md",
            "CODE_OF_CONDUCT.md",
            "PLAN.md",
            "ROADMAP.md",
            "AGENTS.md",
        )
    ]
    sources += sorted((ROOT / "docs").rglob("*.md"))
    sources += sorted((ROOT / "skills").rglob("*.md"))
    for source in sources:
        relative = source.relative_to(ROOT)
        target = output / relative.with_suffix(".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        body = markdown2.markdown(source.read_text(), extras=["fenced-code-blocks", "tables"])
        body = re.sub(
            r'href="([^"#?]+)\.md([#?][^"]*)?"',
            lambda match: 'href="' + match[1] + ".html" + (match[2] or "") + '"',
            body,
        )
        prefix = "../" * len(relative.parent.parts)
        title = html.escape(source.stem.replace("-", " ").title())
        page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} · India Day Trader</title>
<style>body{{max-width:960px;margin:35px auto;padding:0 22px;color:#202a29;background:#fafbf7;font:16px/1.7 system-ui,sans-serif}}nav{{padding-bottom:15px;border-bottom:1px solid #ddd}}a{{color:#315f4b}}img{{max-width:100%;height:auto}}pre{{overflow:auto;padding:16px;background:#edf0e8}}code{{font-size:13px}}table{{border-collapse:collapse;font-size:14px}}td,th{{border:1px solid #d8dfd3;padding:8px}}h1,h2{{line-height:1.3}}footer{{margin-top:50px;font-size:13px;color:#68736b}}</style>
<nav><a href="{prefix}index.html">India Day Trader</a> · <a href="{prefix}api/india_trader.html">API</a> · <a href="{prefix}SECURITY.html">Security</a> · <a href="https://github.com/kirasvg/india-day-trader">Source</a></nav><main>{body}</main><footer>MIT · Experimental research and paper trading. Actual broker/note/session validation remains separate.</footer></html>'''
        target.write_text(page)
    shutil.copy2(output / "README.html", output / "index.html")
    shutil.copytree(ROOT / "docs/assets", output / "docs/assets", dirs_exist_ok=True)
    for source in (ROOT / "docs/research").glob("*.json"):
        target = output / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")
    shutil.copytree(ROOT / "examples", output / "examples", dirs_exist_ok=True)
    print("Built guide and API docs:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "site")
    build(parser.parse_args().output)
