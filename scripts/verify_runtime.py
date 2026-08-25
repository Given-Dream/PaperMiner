"""Fast dependency verification used by PaperMiner Setup."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys


REQUIRED_MODULES = (
    "torch",
    "pandas",
    "openpyxl",
    "bs4",
    "docx",
    "lxml",
    "pypdf",
    "requests",
    "dotenv",
    "ttkbootstrap",
)


def version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for item in value.split("."):
        digits = "".join(character for character in item if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def main() -> int:
    problems: list[str] = []
    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if missing:
        problems.append("missing modules: " + ", ".join(missing))

    try:
        mineru_version = importlib.metadata.version("mineru")
        parsed_version = version_tuple(mineru_version)
        if not ((3, 1) <= parsed_version < (4, 0)):
            problems.append(
                "unsupported mineru version: "
                + mineru_version
                + " (required: >=3.1.0,<4.0)"
            )
    except importlib.metadata.PackageNotFoundError:
        problems.append("missing distribution: mineru")

    try:
        ttkbootstrap_version = importlib.metadata.version("ttkbootstrap")
        parsed_version = version_tuple(ttkbootstrap_version)
        if not ((2, 2, 2) <= parsed_version < (3, 0, 0)):
            problems.append(
                "unsupported ttkbootstrap version: " + ttkbootstrap_version
            )
    except importlib.metadata.PackageNotFoundError:
        problems.append("missing distribution: ttkbootstrap")

    if problems:
        for problem in problems:
            print("[VERIFY ERROR] " + problem)
        return 1

    print("Runtime verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
