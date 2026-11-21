"""Fail when a public file names private content: /RammsPrivateAssets/ is an optional, private submodule, so nothing in
the superproject's Config, Content or Source may need it (a map that names a private robot, an ini that points at a
private asset). Scans the bytes of every file given (pre-commit passes the staged ones), ASCII and UTF-16, so binary
.umap / .uasset packages are covered too.

    python Scripts/check_no_private_refs.py FILE [FILE ...]
"""

import sys

NEEDLE = "/RammsPrivateAssets/"
PATTERNS = (NEEDLE.encode("ascii"), NEEDLE.encode("utf-16-le"))


def main(paths):
    bad = []
    for path in paths:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue  # deleted in this commit
        if any(p in data for p in PATTERNS):
            bad.append(path)
    for path in bad:
        print("%s: names %s (private content must not be referenced from the public project)" % (path, NEEDLE))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
