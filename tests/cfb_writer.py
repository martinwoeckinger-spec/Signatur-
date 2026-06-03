"""Minimaler Writer fuer das Compound File Binary Format (CFB / OLE2).

Erzeugt eine schlanke, aber echte Outlook-.msg-Datei aus String-Properties –
nur fuer Tests, damit keine grosse Binaerdatei ins Repo muss. Alle Streams
liegen im Mini-Stream (Properties sind klein), eine FAT-Sektor reicht.
"""
from __future__ import annotations

import struct

ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF
SECTOR = 512
MINISECTOR = 64


def _dir_entry(name: str, obj_type: int, child: int, right: int,
               start: int, size: int) -> bytes:
    nb = name.encode("utf-16-le") + b"\x00\x00"
    if len(nb) > 64:
        raise ValueError("Name zu lang")
    e = nb + b"\x00" * (64 - len(nb))
    e += struct.pack("<H", len(nb))          # Name-Laenge (inkl. NUL)
    e += struct.pack("<B", obj_type)         # 5=Root, 2=Stream
    e += struct.pack("<B", 1)                # Farbe (schwarz)
    e += struct.pack("<I", NOSTREAM)         # left sibling
    e += struct.pack("<I", right)            # right sibling
    e += struct.pack("<I", child)            # child
    e += b"\x00" * 16                        # CLSID
    e += struct.pack("<I", 0)                # state bits
    e += b"\x00" * 16                        # ctime + mtime
    e += struct.pack("<I", start)            # Start-Sektor
    e += struct.pack("<Q", size)             # Groesse
    assert len(e) == 128
    return e


def build_msg(props: dict[str, str]) -> bytes:
    """Baut eine .msg aus {Property-ID(4 Hex): Unicode-Wert}."""
    streams = [(f"__substg1.0_{pid}001F", val.encode("utf-16-le"))
               for pid, val in props.items()]
    streams.sort(key=lambda s: (len(s[0]), s[0].upper()))
    n = len(streams)

    # Mini-Stream + Mini-FAT
    mini = b""
    meta = []  # (mini_start, count)
    for _name, data in streams:
        start = len(mini) // MINISECTOR
        mini += data
        mini += b"\x00" * ((-len(data)) % MINISECTOR)
        cnt = max(1, (len(data) + MINISECTOR - 1) // MINISECTOR)
        meta.append((start, cnt))
    mini_total = len(mini)
    mini_sector_count = mini_total // MINISECTOR

    minifat = [FREESECT] * max(1, mini_sector_count)
    for start, cnt in meta:
        for k in range(cnt):
            minifat[start + k] = ENDOFCHAIN if k == cnt - 1 else start + k + 1

    # Sektor-Layout: 0=FAT, dann Directory, Mini-FAT, Mini-Stream
    dir_bytes = (n + 1) * 128
    dir_sectors = max(1, (dir_bytes + SECTOR - 1) // SECTOR)
    minifat_sectors = max(1, (len(minifat) * 4 + SECTOR - 1) // SECTOR)
    ms_sectors = max(1, (mini_total + SECTOR - 1) // SECTOR)

    dir_start = 1
    minifat_start = dir_start + dir_sectors
    mini_start = minifat_start + minifat_sectors
    total = mini_start + ms_sectors

    fat = [FREESECT] * 128
    fat[0] = FATSECT

    def chain(first: int, count: int) -> None:
        for i in range(count):
            s = first + i
            fat[s] = ENDOFCHAIN if i == count - 1 else s + 1
    chain(dir_start, dir_sectors)
    chain(minifat_start, minifat_sectors)
    chain(mini_start, ms_sectors)

    # Directory: Root + Streams (rechts-verkettete, sortierte Liste = gueltiger BST)
    entries = [_dir_entry("Root Entry", 5, child=1 if n else NOSTREAM,
                          right=NOSTREAM, start=mini_start, size=mini_total)]
    for i, (name, data) in enumerate(streams):
        right = (i + 2) if i < n - 1 else NOSTREAM
        entries.append(_dir_entry(name, 2, child=NOSTREAM, right=right,
                                  start=meta[i][0], size=len(data)))
    dir_blob = b"".join(entries)
    dir_blob += b"\x00" * (dir_sectors * SECTOR - len(dir_blob))

    minifat_blob = b"".join(struct.pack("<I", x) for x in minifat)
    minifat_blob += b"\x00" * (minifat_sectors * SECTOR - len(minifat_blob))

    mini_blob = mini + b"\x00" * (ms_sectors * SECTOR - mini_total)
    fat_blob = b"".join(struct.pack("<I", x) for x in fat)

    # Header
    hdr = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
    hdr += struct.pack("<HH", 0x003E, 0x0003)   # minor/major
    hdr += struct.pack("<H", 0xFFFE)            # byte order
    hdr += struct.pack("<HH", 0x0009, 0x0006)   # sector / mini shift
    hdr += b"\x00" * 6
    hdr += struct.pack("<I", 0)                 # num dir sectors (v3)
    hdr += struct.pack("<I", 1)                 # num FAT sectors
    hdr += struct.pack("<I", dir_start)         # first dir sector
    hdr += struct.pack("<I", 0)                 # transaction sig
    hdr += struct.pack("<I", 4096)              # mini cutoff
    hdr += struct.pack("<I", minifat_start)     # first mini-FAT sector
    hdr += struct.pack("<I", minifat_sectors)   # num mini-FAT sectors
    hdr += struct.pack("<I", ENDOFCHAIN)        # first DIFAT sector
    hdr += struct.pack("<I", 0)                 # num DIFAT sectors
    difat = [0] + [FREESECT] * 108
    hdr += b"".join(struct.pack("<I", x) for x in difat)
    assert len(hdr) == 512

    body = bytearray(total * SECTOR)
    body[0:SECTOR] = fat_blob
    off = dir_start * SECTOR
    body[off:off + len(dir_blob)] = dir_blob
    off = minifat_start * SECTOR
    body[off:off + len(minifat_blob)] = minifat_blob
    off = mini_start * SECTOR
    body[off:off + len(mini_blob)] = mini_blob
    return hdr + bytes(body)
