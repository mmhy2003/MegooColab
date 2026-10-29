"""Release versions: exactly X.Y.Z (a leading v allowed). Anything else (dev, 0.1.0-dev+abc) is a build from
source, which is never "out of date"."""

import re

RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse(version: str | None) -> tuple[int, int, int] | None:
    m = RELEASE.match((version or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(latest: str | None, current: str | None) -> bool:
    newest, have = parse(latest), parse(current)
    return newest is not None and have is not None and newest > have
