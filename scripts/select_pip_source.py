#!/usr/bin/env python3
"""Select one trusted PyPI-compatible index using a short parallel speed probe."""

from __future__ import annotations

import argparse
import concurrent.futures
import html
from html.parser import HTMLParser
import os
from pathlib import Path
import time
from urllib.parse import urldefrag, urljoin
from urllib.request import Request, urlopen


PROBE_PROJECT = "opencv-python"
SAMPLE_BYTES = 512 * 1024
TIMEOUT_SECONDS = 8.0
SOURCES = (
    ("Tsinghua PyPI", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("Aliyun PyPI", "https://mirrors.aliyun.com/pypi/simple"),
    ("USTC PyPI", "https://pypi.mirrors.ustc.edu.cn/simple"),
    ("Tencent PyPI", "https://mirrors.cloud.tencent.com/pypi/simple"),
    ("PyPI official", "https://pypi.org/simple"),
)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(html.unescape(value))


def _read_limited(response, limit: int) -> int:
    total = 0
    while total < limit:
        chunk = response.read(min(64 * 1024, limit - total))
        if not chunk:
            break
        total += len(chunk)
    return total


def _probe_source(source: tuple[str, str]) -> dict[str, object]:
    name, base_url = source
    started = time.perf_counter()
    try:
        project_url = f"{base_url.rstrip('/')}/{PROBE_PROJECT}/"
        page_request = Request(
            project_url,
            headers={
                "User-Agent": "PaperMiner/1.4.22",
                "Accept": "application/vnd.pypi.simple.v1+html, text/html",
            },
        )
        with urlopen(page_request, timeout=TIMEOUT_SECONDS) as response:
            page = response.read(2 * 1024 * 1024).decode("utf-8", "replace")

        parser = _LinkParser()
        parser.feed(page)
        wheel_links = []
        for link in parser.links:
            clean_link = urldefrag(urljoin(project_url, link))[0]
            lower = clean_link.lower()
            if lower.endswith(".whl") and "win_amd64" in lower:
                wheel_links.append(clean_link)
        if not wheel_links:
            for link in parser.links:
                clean_link = urldefrag(urljoin(project_url, link))[0]
                if clean_link.lower().endswith(".whl"):
                    wheel_links.append(clean_link)
        if not wheel_links:
            raise RuntimeError("no wheel link was exposed by the index")

        sample_request = Request(
            wheel_links[-1],
            headers={
                "User-Agent": "PaperMiner/1.4.22",
                "Range": f"bytes=0-{SAMPLE_BYTES - 1}",
            },
        )
        with urlopen(sample_request, timeout=TIMEOUT_SECONDS) as response:
            sampled = _read_limited(response, SAMPLE_BYTES)
        if sampled <= 0:
            raise RuntimeError("no wheel sample data was received")

        elapsed = max(time.perf_counter() - started, 0.001)
        mib_per_second = (sampled / (1024 * 1024)) / elapsed
        return {
            "name": name,
            "url": base_url,
            "available": True,
            "speed": mib_per_second,
            "sampled": sampled,
            "error": "",
        }
    except Exception as exc:  # A failed probe must not block installation.
        return {
            "name": name,
            "url": base_url,
            "available": False,
            "speed": 0.0,
            "sampled": 0,
            "error": str(exc),
        }


def _select_source() -> tuple[dict[str, object], list[dict[str, object]]]:
    override = os.environ.get("PAPERMINER_PIP_INDEX_URL", "").strip()
    if override:
        selected = {
            "name": "User override",
            "url": override.rstrip("/"),
            "available": True,
            "speed": 0.0,
            "sampled": 0,
            "error": "",
        }
        return selected, [selected]

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SOURCES)) as executor:
        results = list(executor.map(_probe_source, SOURCES))
    available = [item for item in results if item["available"]]
    if available:
        selected = max(available, key=lambda item: float(item["speed"]))
    else:
        selected = {
            "name": "PyPI official (probe fallback)",
            "url": "https://pypi.org/simple",
            "available": True,
            "speed": 0.0,
            "sampled": 0,
            "error": "all probes failed",
        }
    return selected, results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Path to a batch-compatible result file")
    args = parser.parse_args()

    selected, results = _select_source()
    print("Testing trusted PyPI download sources (short parallel wheel samples)...")
    for item in results:
        if item["available"]:
            print(f"  {item['name']}: {float(item['speed']):.2f} MiB/s")
        else:
            print(f"  {item['name']}: unavailable ({item['error']})")
    print(f"Selected PyPI source: {selected['name']} -> {selected['url']}")

    output_path = Path(args.output)
    output_path.write_text(
        "\n".join(
            (
                f"PIP_SOURCE_NAME={selected['name']}",
                f"PIP_INDEX_URL={selected['url']}",
                f"PIP_PROBE_MIBPS={float(selected['speed']):.3f}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
