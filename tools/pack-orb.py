#!/usr/bin/env python3
"""Pack a directory of theme files into a .orb bundle.

The inverse of unpack-orb.py. Produces exactly what Orb Studio would send over the cable,
so the result can be installed, inspected with read-orb-bundle.py, or kept as a backup.

    python3 tools/pack-orb.py themes/unpacked/celestial-animated-qvym
    python3 tools/pack-orb.py themes/unpacked/aviator-eyl2 -o ~/Aviator.orb

The slug is taken from the directory name, which is how unpack-orb.py names things; pass
--slug to override it. Files are packed in sorted order so the same directory always makes
the same bytes -- a round trip through unpack/pack is therefore equal in CONTENT to the
original, but not necessarily byte-identical, since Studio's own file order is arbitrary.

WHAT THIS DOES NOT DO: it never edits theme.json. Two fields in there are Studio's and are
computed with an algorithm that is not in this repo:

  assetsHash   what the firmware actually trusts to decide whether a theme changed
               (theme_style::assetsFingerprint prefers it over the name-only hash). If you
               edit an asset's BYTES and leave this alone, the Orb decides nothing moved
               and keeps serving the previously baked pixels -- the new artwork silently
               never appears. Pass --rehash to break that.
  fileHashes   what a wireless pull compares to decide which files it can skip re-sending.

--rehash replaces assetsHash with a value of our own over the declared assets' contents and
DROPS fileHashes entirely, so the next pull re-sends everything rather than trusting stale
entries. The firmware only ever compares assetsHash for equality, so any value that moves
when the contents move does the job; it does not have to be Studio's number.
"""
import argparse
import json
import os
import struct
import sys

MAGIC = b"ORBTHM01"

# Config, not artwork: these live in a theme but are deliberately absent from theme.json's
# asset list, so they must not be reported as "present but undeclared". Mirrors what
# /themefiles shows with `declared NO` for every theme on the card.
NOT_ASSETS = {"theme.json", "studio.json", "_installed"}

# theme_art.cpp's index stores an asset name in a char[24], written with 23 characters plus
# a NUL and compared over all 24. A longer name bakes and is then unfindable -- the same
# trap that cost Celestial every one of its assets through the slug field.
MAX_NAME = 23


def fnv1a(data, h=2166136261):
    for c in data:
        h = ((h ^ c) * 16777619) & 0xFFFFFFFF
    return h


def is_config(name):
    return name in NOT_ASSETS or name.endswith("_style.json")


def collect(src):
    names = []
    for name in sorted(os.listdir(src)):
        full = os.path.join(src, name)
        if name.startswith("."):
            print("  skipping dotfile %s" % name, file=sys.stderr)
            continue
        if os.path.isdir(full):
            print("  skipping directory %s (the format is flat)" % name, file=sys.stderr)
            continue
        if not os.path.isfile(full):
            continue
        names.append(name)
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="the theme directory to pack")
    ap.add_argument("-o", "--out", help="output .orb path (default: <slug>.orb here)")
    ap.add_argument("--slug", help="override the slug (default: the directory's name)")
    ap.add_argument("--rehash", action="store_true",
                    help="give theme.json a fresh assetsHash and drop fileHashes")
    args = ap.parse_args()

    src = os.path.expanduser(args.src).rstrip("/")
    if not os.path.isdir(src):
        raise SystemExit("%s is not a directory" % src)
    slug = args.slug or os.path.basename(src)
    if not slug:
        raise SystemExit("could not work out a slug -- pass --slug")

    names = collect(src)
    if not names:
        raise SystemExit("%s holds no files" % src)
    blobs = {n: open(os.path.join(src, n), "rb").read() for n in names}

    # ---- theme.json: the manifest the firmware reads, optionally re-hashed -------------
    declared, warn = set(), []
    if "theme.json" not in blobs:
        warn.append("no theme.json: the firmware allows every file for a theme that declares "
                    "no list, but nothing will re-bake when the theme changes")
    else:
        try:
            tj = json.loads(blobs["theme.json"].decode("utf-8"))
        except ValueError as e:
            raise SystemExit("theme.json will not parse: %s" % e)
        declared = set(tj.get("assets", []))
        if args.rehash:
            h = 2166136261
            for n in sorted(declared):
                if n in blobs:
                    h = fnv1a(n.encode("utf-8") + blobs[n], h)
            tj["assetsHash"] = h if h else 1
            dropped = len(tj.pop("fileHashes", {}) or {})
            blobs["theme.json"] = (json.dumps(tj, indent=2) + "\n").encode("utf-8")
            print("  --rehash: assetsHash -> %d, dropped %d fileHashes entry(ies)"
                  % (tj["assetsHash"], dropped))
        elif "assetsHash" in tj:
            warn.append("theme.json kept as-is (assetsHash %s). If you changed any asset's "
                        "BYTES, pass --rehash or the Orb will keep serving the art it "
                        "already baked" % tj["assetsHash"])

        for n in sorted(declared - set(blobs)):
            warn.append("declared in theme.json but ABSENT from the directory: %s" % n)
        for n in sorted(set(blobs) - declared):
            if not is_config(n):
                warn.append("present but NOT declared in theme.json, so the bake will skip "
                            "it and the Orb will never use it: %s" % n)

    for n in sorted(blobs):
        if len(n) > MAX_NAME:
            warn.append("name is %d characters, over the %d the firmware's index can hold -- "
                        "it will bake and then never be found: %s" % (len(n), MAX_NAME, n))

    # ---- write the bundle ---------------------------------------------------------------
    out = os.path.expanduser(args.out) if args.out else slug + ".orb"
    body = bytearray(MAGIC)
    slug_b = slug.encode("utf-8")
    body += struct.pack("<H", len(slug_b)) + slug_b
    body += struct.pack("<H", len(blobs))
    total = 0
    for n in sorted(blobs):
        nb = n.encode("utf-8")
        body += struct.pack("<H", len(nb)) + nb
        body += struct.pack("<I", len(blobs[n])) + blobs[n]
        total += len(blobs[n])
    with open(out, "wb") as f:
        f.write(body)

    print("\n  %s\n  slug: %s   files: %d   %.1f KB of assets, %.1f KB packed\n"
          % (out, slug, len(blobs), total / 1024.0, len(body) / 1024.0))
    fonts = sorted(n for n in blobs if n.startswith("font_"))
    print("  %d font slot(s): %s" % (len(fonts), ", ".join(fonts) if fonts else "none"))
    if warn:
        print("\n  %d warning(s):" % len(warn))
        for w in warn:
            print("    - %s" % w)
    print()


if __name__ == "__main__":
    main()
