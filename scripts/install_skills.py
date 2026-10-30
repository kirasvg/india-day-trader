"""Install eleven independent skills with their shared engine bundled locally."""

import argparse
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install(destination):
    sources = sorted((ROOT / "skills").glob("india-trader-*"))
    if len(sources) != 11:
        raise ValueError("Expected complete eleven-skill source checkout")
    collisions = [destination / p.name for p in sources if (destination / p.name).exists()]
    if collisions:
        raise ValueError("Refusing to overwrite existing skill: " + str(collisions[0]))
    destination.mkdir(parents=True, exist_ok=True)
    # Prepare every copy before publishing the first skill; never copy account state.
    with tempfile.TemporaryDirectory(
        prefix=".india-skill-install-", dir=str(destination)
    ) as temporary:
        staging = Path(temporary)
        for source in sources:
            target = staging / source.name
            shutil.copytree(source, target)
            for name in ("india_trader", "examples", "docs"):
                shutil.copytree(
                    ROOT / name,
                    target / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            instruction = target / "SKILL.md"
            instruction.write_text(
                instruction.read_text(encoding="utf-8").replace("../../docs/", "docs/"),
                encoding="utf-8",
            )
        for source in sources:
            (staging / source.name).rename(destination / source.name)
    return len(sources)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("codex", "claude"), default="codex")
    parser.add_argument(
        "--destination", type=Path, help="Override skill folder, useful for project-local installs"
    )
    args = parser.parse_args()
    default = (
        (Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills")
        if args.platform == "codex"
        else Path.home() / ".claude" / "skills"
    )
    target = args.destination or default
    try:
        print("Installed %s skills to %s" % (install(target), target))
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
