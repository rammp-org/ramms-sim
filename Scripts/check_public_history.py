"""Fail when a public curb-performance file (Docs/curb-performance/, pre-commit passes the staged ones) carries what must
stay private or local: a record of a robot whose history is kept privately (gen2), the code state of a private
repository, the name of the optional private plugin, or an absolute path (this machine's folders).

    python Scripts/check_public_history.py FILE [FILE ...]
"""

import re
import sys

RULES = (
    (re.compile(r'"robot"\s*:\s*"gen2'), "a record of a robot whose history is private"),
    (re.compile(r'"private"\s*:\s*\{'), "a private repository's code state"),
    (re.compile("Ramms" + "PrivateAssets"), "the optional private plugin's name"),
    (re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:(\\\\|\\|/)'), "an absolute Windows path"),
    (re.compile(r'(?<![\w.])/(Users|home)/'), "an absolute path"),
)


def main(paths):
    bad = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue  # deleted in this commit
        for n, line in enumerate(lines, 1):
            for rx, what in RULES:
                if rx.search(line):
                    print("%s:%d: %s (public curb history must not carry it)" % (path, n, what))
                    bad += 1
                    break
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
