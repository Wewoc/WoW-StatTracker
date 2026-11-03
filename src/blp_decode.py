#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
# blp_decode.py
# Blizzard BLP2 textures (the item icons of the game) to PNG.
#
# Pure calculation: no file access, no project imports (stdlib only). It takes the bytes of a
# .blp file and returns the bytes of a .png file; the caller reads and writes the files.
#
# Only what the item icons use is decoded: BLP2, content type 1 (direct), encoding 2 (DXT) with
# DXT1, DXT3 or DXT5, the largest mip level. Everything else (palette or uncompressed BLP2, JPEG
# content, BLP0/BLP1, a damaged or truncated file) raises BlpError, and nothing is guessed: the
# caller keeps its fallback (the slot symbol) for that icon.

import struct
import zlib

# magic, content type, encoding, alpha depth, alpha encoding, mip flag, width, height
HEADER = struct.Struct("<4sIBBBBII")
OFFSETS_AT = 0x14          # 16 x uint32: where each mip level starts
SIZES_AT = 0x54            # 16 x uint32: how long each level is
TABLES_END = 0x94          # the palette (1024 bytes) follows; DXT data does not use it
MAX_SIDE = 512             # the icons are 64 x 64; anything far bigger is not an icon

CONTENT_DIRECT = 1
ENCODING_DXT = 2
ALPHA_ENCODING = {0: "dxt1", 1: "dxt3", 7: "dxt5"}
BLOCK_BYTES = {"dxt1": 8, "dxt3": 16, "dxt5": 16}


class BlpError(ValueError):
    """The file is not a BLP2 icon this module decodes."""


def _rgb565(value):
    r, g, b = (value >> 11) & 31, (value >> 5) & 63, value & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _alpha_dxt5(block):
    """The 16 alpha values of a DXT5 block (two end points, 3 bits per pixel)."""
    a0, a1 = block[0], block[1]
    bits = int.from_bytes(block[2:8], "little")
    if a0 > a1:
        table = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        table = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
    return [table[(bits >> (3 * i)) & 7] for i in range(16)]


def _block_pixels(kind, block, alpha_depth):
    """The 16 pixels of one 4 x 4 block as (r, g, b, a), row by row."""
    colors = block[:8] if kind == "dxt1" else block[8:16]
    c0, c1 = struct.unpack_from("<HH", colors)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    if kind != "dxt1" or c0 > c1:
        p2 = tuple((2 * a + b) // 3 for a, b in zip(p0, p1))
        p3 = tuple((a + 2 * b) // 3 for a, b in zip(p0, p1))
        palette = [p0 + (255,), p1 + (255,), p2 + (255,), p3 + (255,)]
    else:
        # DXT1 with the end points the other way round: three colors, the fourth is "no color"
        p2 = tuple((a + b) // 2 for a, b in zip(p0, p1))
        palette = [p0 + (255,), p1 + (255,), p2 + (255,), (0, 0, 0, 0 if alpha_depth else 255)]
    bits = struct.unpack_from("<I", colors, 4)[0]
    pixels = [palette[(bits >> (2 * i)) & 3] for i in range(16)]
    if kind == "dxt3":
        return [(r, g, b, ((block[i >> 1] >> (4 * (i & 1))) & 15) * 17) for i, (r, g, b, _a) in enumerate(pixels)]
    if kind == "dxt5":
        return [(r, g, b, a) for (r, g, b, _a), a in zip(pixels, _alpha_dxt5(block))]
    return pixels


def decode(data):
    """(width, height, RGBA bytes) of the largest level of a BLP2 file. Raises BlpError."""
    if len(data) < TABLES_END:
        raise BlpError("file too short for a BLP2 header")
    magic, content, encoding, alpha_depth, alpha_encoding, _mips, width, height = HEADER.unpack_from(data)
    if magic != b"BLP2":
        raise BlpError(f"not a BLP2 file (magic {magic!r})")
    if content != CONTENT_DIRECT or encoding != ENCODING_DXT:
        raise BlpError(f"not a DXT texture (content type {content}, encoding {encoding})")
    kind = ALPHA_ENCODING.get(alpha_encoding)
    if kind is None:
        raise BlpError(f"unknown DXT alpha encoding {alpha_encoding}")
    if not (4 <= width <= MAX_SIDE and 4 <= height <= MAX_SIDE) or width % 4 or height % 4:
        raise BlpError(f"unsupported size {width} x {height}")

    offset = struct.unpack_from("<I", data, OFFSETS_AT)[0]
    size = struct.unpack_from("<I", data, SIZES_AT)[0]
    expected = (width // 4) * (height // 4) * BLOCK_BYTES[kind]
    if size != expected:
        raise BlpError(f"first level holds {size} bytes, {expected} expected for {width} x {height} {kind}")
    if offset < TABLES_END or offset + size > len(data):
        raise BlpError("first level lies outside the file")

    step = BLOCK_BYTES[kind]
    rgba = bytearray(width * height * 4)
    position = offset
    for block_y in range(height // 4):
        for block_x in range(width // 4):
            pixels = _block_pixels(kind, data[position:position + step], alpha_depth)
            position += step
            for row in range(4):
                start = ((block_y * 4 + row) * width + block_x * 4) * 4
                rgba[start:start + 16] = bytes(v for pixel in pixels[row * 4:row * 4 + 4] for v in pixel)
    return width, height, bytes(rgba)


def _chunk(tag, payload):
    body = tag + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def to_png(width, height, rgba):
    """A PNG (8 bit RGBA, no interlace) of the pixel bytes."""
    if len(rgba) != width * height * 4:
        raise BlpError("pixel data does not match the size")
    rows = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(rows, 9))
            + _chunk(b"IEND", b""))


def blp_to_png(data):
    """The PNG of a BLP2 icon. Raises BlpError."""
    return to_png(*decode(data))
