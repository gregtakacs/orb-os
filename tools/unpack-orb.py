#!/usr/bin/env python3
"""Unpack a .orb theme file into a directory of plain files.

The inverse of pack-orb.py, and the long form of read-orb-bundle.py -- that one lists the
same contents without writing anything, which is usually what you want when the question is
just "is this file actually in the theme?".

    python3 tools/unpack-orb.py "~/Downloads/Celestial 2.orb"
    python3 tools/unpack-orb.py "~/Downloads/Celestial 2.orb" /tmp/celestial

With no destination the files land in themes/unpacked/<slug>/ next to the other unpacked
themes in this repo. The bundle carries the slug, so the directory is named for you.
"""
import argparse
import os
import struct
import sys

MAGIC = b"ORBTHM01"

# The flat archive Orb Studio sends over the cable:
#   magic 8s | slug_len u16 | slug | count u16 | per file: name_len u16, name, size u32, bytes


def unpack(data):
    if data[:8] != MAGIC:
        raise SystemExit("not an Orb theme file (magic is %r, expected %r)" % (data[:8], MAGIC))
    at = 8
    (slug_len,) = struct.unpack_from("<H", data, at); at += 2
    slug = data[at:at + slug_len].decode("utf-8"); at += slug_len
    (count,) = struct.unpack_from("<H", data, at); at += 2
    files = []
    for i in range(count):
        (n,) = struct.unpack_from("<H", data, at); at += 2
        name = data[at:at + n].decode("utf-8"); at += n
        (size,) = struct.unpack_from("<I", data, at); at += 4
        if at + size > len(data):
            raise SystemExit("truncated bundle: %s wants %d bytes, only %d left"
                             % (name, size, len(data) - at))
        files.append((name, data[at:at + size])); at += size
    if at != len(data):
        print("  note: %d trailing byte(s) after the last file" % (len(data) - at), file=sys.stderr)
    return slug, files


def safe_leaf(name):
    """A bundle is untrusted input: a name with a separator in it must not be able to write
    outside the destination. The format is flat, so any separator is already malformed."""
    if not name or name in (".", "..") or "/" in name or "\\" in name or os.path.isabs(name):
        raise SystemExit("refusing to write unsafe entry name %r" % name)
    return name


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", help="the .orb file to unpack")
    ap.add_argument("dest", nargs="?", help="destination directory "
                                            "(default: themes/unpacked/<slug>/)")
    ap.add_argument("-f", "--force", action="store_true",
                    help="overwrite an existing destination directory")
    args = ap.parse_args()

    path = os.path.expanduser(args.bundle)
    with open(path, "rb") as f:
        slug, files = unpack(f.read())

    dest = os.path.expanduser(args.dest) if args.dest else os.path.join("themes", "unpacked", slug)
    if os.path.isdir(dest) and os.listdir(dest) and not args.force:
        raise SystemExit("%s already exists and is not empty -- pass --force to overwrite" % dest)
    os.makedirs(dest, exist_ok=True)

    print("\n  %s\n  slug: %s   files: %d -> %s\n" % (os.path.basename(path), slug, len(files), dest))
    total = 0
    for name, blob in files:
        out = os.path.join(dest, safe_leaf(name))
        with open(out, "wb") as f:
            f.write(blob)
        total += len(blob)
        print("    %8.1f KB  %s" % (len(blob) / 1024.0, name))
    print("\n  %d file(s), %.1f KB\n" % (len(files), total / 1024.0))


if __name__ == "__main__":
    main()
