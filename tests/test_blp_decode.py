# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

import struct
import zlib

import pytest

import blp_decode
from blp_decode import BlpError

RED, GREEN, BLUE, WHITE = 0xF800, 0x07E0, 0x001F, 0xFFFF      # RGB565
TABLES_END = 0x94
PALETTE_BYTES = 1024
LEVEL_AT = TABLES_END + PALETTE_BYTES       # where the game's files put the first level


def blp2(width, height, payload, *, magic=b"BLP2", content=1, encoding=2, alpha_depth=0, alpha_encoding=0,
         offset=LEVEL_AT, size=None):
    """A BLP2 file around `payload` (the DXT blocks of level 0)."""
    header = blp_decode.HEADER.pack(magic, content, encoding, alpha_depth, alpha_encoding, 1, width, height)
    offsets = struct.pack("<16I", offset, *([0] * 15))
    sizes = struct.pack("<16I", len(payload) if size is None else size, *([0] * 15))
    return header + offsets + sizes + bytes(PALETTE_BYTES) + payload


def color_block(c0, c1, indices):
    return struct.pack("<HHI", c0, c1, sum(i << (2 * n) for n, i in enumerate(indices)))


def dxt1(c0, c1, indices):
    return color_block(c0, c1, indices)


def dxt3(c0, c1, indices, alphas):
    """alphas: 16 values 0..15, two to a byte, the first pixel in the low nibble."""
    alpha = bytes(alphas[2 * j] | (alphas[2 * j + 1] << 4) for j in range(8))
    return alpha + color_block(c0, c1, indices)


def dxt5(c0, c1, indices, a0, a1, alpha_indices):
    bits = sum(i << (3 * n) for n, i in enumerate(alpha_indices))
    return bytes([a0, a1]) + bits.to_bytes(6, "little") + color_block(c0, c1, indices)


def pixel(rgba, width, x, y):
    start = (y * width + x) * 4
    return tuple(rgba[start:start + 4])


def row(rgba, width, y):
    return [pixel(rgba, width, x, y) for x in range(width)]


# ------------------------------------------------------------------------------ DXT1
def test_dxt1_four_color_mode_when_the_first_end_point_is_larger():
    # red, blue, and the two thirds between them: (2r+b)/3 and (r+2b)/3, in integer arithmetic
    width, height, rgba = blp_decode.decode(blp2(4, 4, dxt1(RED, BLUE, [0, 1, 2, 3] * 4)))
    assert (width, height) == (4, 4)
    expected = [(255, 0, 0, 255), (0, 0, 255, 255), (170, 0, 85, 255), (85, 0, 170, 255)]
    for y in range(4):
        assert row(rgba, 4, y) == expected


def test_dxt1_three_color_mode_has_a_clear_fourth_color_only_with_alpha():
    data = dxt1(BLUE, RED, [0, 1, 2, 3] * 4)           # first end point smaller: three colors + "none"
    with_alpha = blp_decode.decode(blp2(4, 4, data, alpha_depth=1))[2]
    without_alpha = blp_decode.decode(blp2(4, 4, data, alpha_depth=0))[2]
    # blue, red, their middle (255 // 2 = 127), then transparent or opaque black
    assert row(with_alpha, 4, 0) == [(0, 0, 255, 255), (255, 0, 0, 255), (127, 0, 127, 255), (0, 0, 0, 0)]
    assert row(without_alpha, 4, 0) == [(0, 0, 255, 255), (255, 0, 0, 255), (127, 0, 127, 255), (0, 0, 0, 255)]


# ------------------------------------------------------------------------------ DXT3
def test_dxt3_alpha_is_four_bits_per_pixel_and_colors_ignore_the_end_point_order():
    # first end point smaller than the second: DXT3 still uses four colors, so index 2 is (2*blue + red) / 3
    data = dxt3(BLUE, RED, [2] * 16, list(range(16)))
    width, height, rgba = blp_decode.decode(blp2(4, 4, data, alpha_depth=8, alpha_encoding=1))
    for n in range(16):
        assert pixel(rgba, width, n % 4, n // 4) == (85, 0, 170, n * 17)


# ------------------------------------------------------------------------------ DXT5
def test_dxt5_eight_step_alpha_when_the_first_value_is_larger():
    # 255 -> 0 in seven steps: 255, 0, then 218, 182, 145, 109, 72, 36 (integer division)
    data = dxt5(WHITE, WHITE, [0] * 16, 255, 0, [n % 8 for n in range(16)])
    rgba = blp_decode.decode(blp2(4, 4, data, alpha_depth=8, alpha_encoding=7))[2]
    table = [255, 0, 218, 182, 145, 109, 72, 36]
    assert [pixel(rgba, 4, n % 4, n // 4) for n in range(16)] == [(255, 255, 255, table[n % 8]) for n in range(16)]


def test_dxt5_six_step_alpha_with_fixed_ends_when_the_first_value_is_smaller():
    # 0 -> 255 in five steps (0, 255, 51, 102, 153, 204) and the two fixed values 0 and 255
    data = dxt5(WHITE, WHITE, [0] * 16, 0, 255, [n % 8 for n in range(16)])
    rgba = blp_decode.decode(blp2(4, 4, data, alpha_depth=8, alpha_encoding=7))[2]
    table = [0, 255, 51, 102, 153, 204, 0, 255]
    assert [pixel(rgba, 4, n % 4, n // 4)[3] for n in range(16)] == [table[n % 8] for n in range(16)]


# --------------------------------------------------------------------------- the image
def test_blocks_are_laid_out_left_to_right_then_top_to_bottom():
    solid = lambda c: dxt1(c, c, [0] * 16)
    data = solid(RED) + solid(GREEN) + solid(BLUE) + solid(WHITE)
    _width, _height, rgba = blp_decode.decode(blp2(8, 8, data))
    assert pixel(rgba, 8, 0, 0) == pixel(rgba, 8, 3, 3) == (255, 0, 0, 255)
    assert pixel(rgba, 8, 4, 0) == pixel(rgba, 8, 7, 3) == (0, 255, 0, 255)
    assert pixel(rgba, 8, 0, 4) == pixel(rgba, 8, 3, 7) == (0, 0, 255, 255)
    assert pixel(rgba, 8, 4, 4) == pixel(rgba, 8, 7, 7) == (255, 255, 255, 255)


def test_an_icon_sized_texture_decodes_to_the_whole_image():
    data = dxt1(RED, BLUE, [0] * 16) * (16 * 16)
    width, height, rgba = blp_decode.decode(blp2(64, 64, data))
    assert (width, height, len(rgba)) == (64, 64, 64 * 64 * 4)


def test_only_the_first_level_is_read():
    first = dxt1(RED, BLUE, [0] * 16)
    smaller_level_after_it = dxt1(GREEN, BLUE, [0] * 16)
    rgba = blp_decode.decode(blp2(4, 4, first + smaller_level_after_it, size=len(first)))[2]
    assert pixel(rgba, 4, 0, 0) == (255, 0, 0, 255)


# ---------------------------------------------------------------------------- the PNG
def read_png(png):
    """(width, height, RGBA bytes) of a PNG made of the chunks IHDR, IDAT, IEND; checks every CRC."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, position = [], 8
    while position < len(png):
        length = struct.unpack_from(">I", png, position)[0]
        tag = png[position + 4:position + 8]
        payload = png[position + 8:position + 8 + length]
        crc = struct.unpack_from(">I", png, position + 8 + length)[0]
        assert crc == zlib.crc32(tag + payload) & 0xFFFFFFFF
        chunks.append((tag, payload))
        position += 12 + length
    assert [tag for tag, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    assert (depth, color, compression, filtering, interlace) == (8, 6, 0, 0, 0)
    raw = zlib.decompress(chunks[1][1])
    stride = width * 4 + 1
    assert len(raw) == stride * height and all(raw[y * stride] == 0 for y in range(height))
    return width, height, b"".join(raw[y * stride + 1:(y + 1) * stride] for y in range(height))


def test_the_png_holds_exactly_the_decoded_pixels():
    blp = blp2(8, 8, dxt1(RED, BLUE, [0, 1, 2, 3] * 4) * 4)
    assert read_png(blp_decode.blp_to_png(blp)) == blp_decode.decode(blp)


def test_to_png_refuses_pixel_data_of_the_wrong_length():
    with pytest.raises(BlpError):
        blp_decode.to_png(4, 4, bytes(10))


# --------------------------------------------------------------------- what is refused
GOOD_BLOCK = dxt1(RED, BLUE, [0] * 16)

REFUSED = {
    "too short": b"BLP2" + bytes(20),
    "BLP1 magic": blp2(4, 4, GOOD_BLOCK, magic=b"BLP1"),
    "JPEG content": blp2(4, 4, GOOD_BLOCK, content=0),
    "palette encoding": blp2(4, 4, GOOD_BLOCK, encoding=1),
    "uncompressed encoding": blp2(4, 4, GOOD_BLOCK, encoding=3),
    "unknown alpha encoding": blp2(4, 4, GOOD_BLOCK, alpha_encoding=5),
    "width not a multiple of 4": blp2(6, 4, GOOD_BLOCK),
    "no width": blp2(0, 4, GOOD_BLOCK),
    "too large": blp2(1024, 4, GOOD_BLOCK),
    "level size does not fit the image": blp2(4, 4, GOOD_BLOCK, size=16),
    "level starts inside the tables": blp2(4, 4, GOOD_BLOCK, offset=0x10),
    "level runs past the end": blp2(4, 4, GOOD_BLOCK)[:-4],
}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_what_is_not_a_dxt_icon_is_refused_and_never_guessed(name):
    with pytest.raises(BlpError):
        blp_decode.decode(REFUSED[name])
    with pytest.raises(BlpError):
        blp_decode.blp_to_png(REFUSED[name])


def test_the_error_is_a_value_error_so_a_caller_can_catch_it_broadly():
    assert issubclass(BlpError, ValueError)
