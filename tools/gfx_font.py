#!/usr/bin/env python3
"""Add Vazirmatn Arabic/Persian glyph outlines to existing Mafia III GFx fonts."""
from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

HEADER_SIZE = 8
TAG_DEFINE_FONT3 = 75
FONT_MAPPINGS = {
    1: "Vazirmatn-Medium.ttf",       # Futura MdCn BT -> Medium
    3: "Vazirmatn-Regular.ttf",      # Arial -> Regular
    5: "Vazirmatn-ExtraBold.ttf",    # Lintel Heavy -> ExtraBold
    7: "Vazirmatn-Bold.ttf",         # Lintel XB1 -> Bold
    9: "Vazirmatn-Medium.ttf",       # CompactWhiskey102715 -> Medium
}
TARGET_RANGES = (
    (0x0600, 0x0700),
    (0xFB50, 0xFE00),
    (0xFE70, 0xFF00),
)
EXTRA_CODES = {0x200C, 0x200D}


def u16(data: bytes, pos: int) -> int:
    return struct.unpack_from("<H", data, pos)[0]


def u32(data: bytes, pos: int) -> int:
    return struct.unpack_from("<I", data, pos)[0]


def read_bits(data: bytes, bit_pos: int, width: int) -> int:
    value = 0
    for _ in range(width):
        byte_index = bit_pos >> 3
        if byte_index >= len(data):
            raise ValueError("bit field extends beyond input")
        value = (value << 1) | ((data[byte_index] >> (7 - (bit_pos & 7))) & 1)
        bit_pos += 1
    return value


def read_signed(data: bytes, bit_pos: int, width: int) -> int:
    value = read_bits(data, bit_pos, width)
    if width and value & (1 << (width - 1)):
        value -= 1 << width
    return value


def read_rect(data: bytes, pos: int):
    """Read one byte-aligned SWF RECT; return (xmin,xmax,ymin,ymax), next byte."""
    bit_pos = pos * 8
    width = read_bits(data, bit_pos, 5)
    bit_pos += 5
    if width == 0:
        return (0, 0, 0, 0), pos + 1
    values = []
    for _ in range(4):
        values.append(read_signed(data, bit_pos, width))
        bit_pos += width
    return tuple(values), (bit_pos + 7) // 8


def signed_bits(value: int) -> int:
    for width in range(1, 33):
        if -(1 << (width - 1)) <= value < (1 << (width - 1)):
            return width
    raise ValueError("signed value exceeds 32-bit SWF shape limit: %d" % value)


class BitWriter:
    def __init__(self):
        self.out = bytearray()
        self.byte = 0
        self.used = 0

    def write(self, value: int, width: int):
        if width < 0 or (width == 0 and value):
            raise ValueError("invalid bit field")
        if width and not (0 <= value < (1 << width)):
            raise ValueError("unsigned value %d does not fit in %d bits" % (value, width))
        for shift in range(width - 1, -1, -1):
            self.byte = (self.byte << 1) | ((value >> shift) & 1)
            self.used += 1
            if self.used == 8:
                self.out.append(self.byte)
                self.byte = 0
                self.used = 0

    def write_s(self, value: int, width: int):
        if width < 1 or not (-(1 << (width - 1)) <= value < (1 << (width - 1))):
            raise ValueError("signed value %d does not fit in %d bits" % (value, width))
        self.write(value & ((1 << width) - 1), width)

    def align(self):
        if self.used:
            self.write(0, 8 - self.used)

    def bytes(self) -> bytes:
        self.align()
        return bytes(self.out)


def make_rect(rect) -> bytes:
    writer = BitWriter()
    width = max((signed_bits(v) for v in rect), default=0) if any(rect) else 0
    writer.write(width, 5)
    if width:
        for value in rect:
            writer.write_s(value, width)
    return writer.bytes()

def validate_glyph_shape(shape: bytes) -> None:
    """اعتبارسنجی رکوردهای SHAPE تولیدشده برای هر گلیف فونت."""
    bit = 0

    def read(width):
        nonlocal bit
        value = read_bits(shape, bit, width)
        bit += width
        return value

    fill_bits = read(4)
    line_bits = read(4)
    if fill_bits != 1 or line_bits != 0:
        raise ValueError("font glyph must start with NumFillBits=1, NumLineBits=0")
    first_style_seen = False
    saw_end = False
    while bit < len(shape) * 8:
        edge = read(1)
        if edge:
            straight = read(1)
            width = read(4) + 2
            if straight:
                general = read(1)
                if general:
                    read(width)
                    read(width)
                else:
                    read(1)  # VertLineFlag
                    read(width)
            else:
                for _ in range(4):
                    read(width)
            continue

        flags = read(5)
        if flags == 0:
            saw_end = True
            break
        if flags & 1:  # StateMoveTo
            move_bits = read(5)
            read(move_bits)
            read(move_bits)
        if flags & 2:  # StateFillStyle0
            fill0 = read(fill_bits)
            if not first_style_seen and fill0 != 1:
                raise ValueError("first font glyph style must set FillStyle0=1")
            first_style_seen = True
        if flags & 4:  # StateFillStyle1
            read(fill_bits)
        if flags & 8:  # StateLineStyle
            read(line_bits)
        if flags & 16:
            raise ValueError("NewStyles is not valid in a font glyph")

    if not saw_end:
        raise ValueError("font glyph is missing EndShapeRecord")
    padding_start = (bit + 7) // 8
    if any(shape[padding_start:]):
        raise ValueError("non-zero bytes after font glyph EndShapeRecord")



class OutlinePen(BasePen):
    """Collect closed TrueType contours as exact line/quadratic segments."""
    def __init__(self, glyph_set):
        super().__init__(glyph_set)
        self.contours = []
        self._contour = None

    def _moveTo(self, p0):
        if self._contour is not None:
            self._finish()
        self._contour = [tuple(p0), []]

    def _lineTo(self, p1):
        if self._contour is None:
            raise ValueError("lineTo before moveTo")
        self._contour[1].append(("L", tuple(p1)))

    def _qCurveToOne(self, p1, p2):
        if self._contour is None:
            raise ValueError("qCurveTo before moveTo")
        self._contour[1].append(("Q", tuple(p1), tuple(p2)))

    def _curveToOne(self, p1, p2, p3):
        raise ValueError("CFF/cubic outline is unsupported; expected TrueType quadratic outlines")

    def _closePath(self):
        self._finish()

    def _endPath(self):
        self._finish()

    def _finish(self):
        if self._contour is not None:
            self.contours.append(self._contour)
            self._contour = None


def swf_point(point, scale: float):
    return (int(round(point[0] * scale)), int(round(-point[1] * scale)))


def make_glyph_shape(glyph_set, glyph_name: str, scale: float):
    pen = OutlinePen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    pen._finish()
    contours = []
    bbox_points = []
    for start, segments in pen.contours:
        start = swf_point(start, scale)
        converted = []
        current = start
        bbox_points.append(start)
        for segment in segments:
            if segment[0] == "L":
                end = swf_point(segment[1], scale)
                if end != current:
                    converted.append(("L", end))
                    current = end
                    bbox_points.append(end)
            else:
                control = swf_point(segment[1], scale)
                end = swf_point(segment[2], scale)
                if control != current or end != current:
                    converted.append(("Q", control, end))
                    current = end
                    bbox_points.extend((control, end))
        if current != start:
            converted.append(("L", start))
            bbox_points.append(start)
        if converted:
            contours.append((start, converted))

    writer = BitWriter()
    writer.write(1, 4)   # NumFillBits: one fill style (the font glyph fill)
    writer.write(0, 4)   # NumLineBits
    for contour_index, (start, segments) in enumerate(contours):
        # Font glyphs must select FillStyle0=1 in their first style record.
        # Later contours only move; the active fill style remains unchanged.
        writer.write(0, 1)
        writer.write(0b00011 if contour_index == 0 else 0b00001, 5)
        move_width = max(1, signed_bits(start[0]), signed_bits(start[1]))
        writer.write(move_width, 5)
        writer.write_s(start[0], move_width)
        writer.write_s(start[1], move_width)
        if contour_index == 0:
            writer.write(1, 1)  # FillStyle0 = 1
        current = start
        for segment in segments:
            if segment[0] == "L":
                end = segment[1]
                dx, dy = end[0] - current[0], end[1] - current[1]
                if not (dx or dy):
                    continue
                width = max(2, signed_bits(dx), signed_bits(dy))
                if width > 17:
                    raise ValueError("straight edge delta exceeds SWF's 17-bit range")
                writer.write(1, 1)            # TypeFlag: edge
                writer.write(1, 1)            # StraightFlag
                writer.write(width - 2, 4)     # NumBits - 2
                if dx and dy:
                    writer.write(1, 1)         # GeneralLineFlag
                    writer.write_s(dx, width)
                    writer.write_s(dy, width)
                else:
                    writer.write(0, 1)         # GeneralLineFlag = 0
                    writer.write(1 if dx == 0 else 0, 1)  # VertLineFlag
                    writer.write_s(dy if dx == 0 else dx, width)
                current = end
            else:
                control, end = segment[1], segment[2]
                cdx, cdy = control[0] - current[0], control[1] - current[1]
                adx, ady = end[0] - control[0], end[1] - control[1]
                width = max(2, signed_bits(cdx), signed_bits(cdy), signed_bits(adx), signed_bits(ady))
                if width > 17:
                    raise ValueError("quadratic edge delta exceeds SWF's 17-bit range")
                writer.write(1, 1)            # TypeFlag: edge
                writer.write(0, 1)            # StraightFlag: curved edge
                writer.write(width - 2, 4)     # NumBits - 2
                for value in (cdx, cdy, adx, ady):
                    writer.write_s(value, width)
                current = end

    # EndShapeRecord and byte padding.
    writer.write(0, 1)
    writer.write(0, 5)
    shape = writer.bytes()
    validate_glyph_shape(shape)
    if bbox_points:
        xs = [p[0] for p in bbox_points]
        ys = [p[1] for p in bbox_points]
        bounds = (min(xs), max(xs), min(ys), max(ys))
    else:
        bounds = (0, 0, 0, 0)
    return shape, bounds


@dataclass
class FontGlyph:
    code: int
    shape: bytes
    advance: int
    bounds: bytes


@dataclass
class Font3:
    font_id: int
    flags: int
    name: bytes
    prefix: bytes
    glyphs: dict[int, FontGlyph]
    metrics: bytes
    kerning: bytes
    wide_offsets: bool
    wide_codes: bool


def parse_font3(payload: bytes) -> Font3:
    if len(payload) < 7:
        raise ValueError("DefineFont3 payload is too short")
    font_id = u16(payload, 0)
    flags = payload[2]
    name_len = payload[4]
    prefix_end = 5 + name_len
    count_pos = prefix_end
    count = u16(payload, count_pos)
    table_start = count_pos + 2
    wide_offsets = bool(flags & 0x08)
    wide_codes = bool(flags & 0x04)
    offset_width = 4 if wide_offsets else 2
    code_width = 2 if wide_codes else 1
    offsets_end = table_start + count * offset_width
    if offsets_end + offset_width > len(payload):
        raise ValueError("truncated DefineFont3 offset table")
    offsets = [int.from_bytes(payload[table_start + i * offset_width:
                                       table_start + (i + 1) * offset_width], "little")
               for i in range(count)]
    code_offset = int.from_bytes(payload[offsets_end:offsets_end + offset_width], "little")
    code_start = table_start + code_offset
    if code_start < offsets_end + offset_width or code_start + count * code_width > len(payload):
        raise ValueError("invalid DefineFont3 CodeTableOffset")
    code_values = [int.from_bytes(payload[code_start + i * code_width:
                                          code_start + (i + 1) * code_width], "little")
                   for i in range(count)]

    glyph_shapes = []
    for i, offset in enumerate(offsets):
        begin = table_start + offset
        end = table_start + (offsets[i + 1] if i + 1 < count else code_offset)
        if begin > end or end > code_start:
            raise ValueError("invalid glyph shape offset %d" % i)
        glyph_shapes.append(payload[begin:end])

    glyphs = {}
    if flags & 0x80:
        layout_start = code_start + count * code_width
        if layout_start + 6 + 2 * count > len(payload):
            raise ValueError("truncated DefineFont3 layout data")
        metrics = payload[layout_start:layout_start + 6]
        advance_start = layout_start + 6
        advances = [struct.unpack_from("<h", payload, advance_start + 2 * i)[0]
                    for i in range(count)]
        bounds_pos = advance_start + 2 * count
        bounds = []
        for _ in range(count):
            rect, next_pos = read_rect(payload, bounds_pos)
            bounds.append(payload[bounds_pos:next_pos])
            bounds_pos = next_pos
        kerning = payload[bounds_pos:]
        if len(kerning) < 2:
            raise ValueError("missing DefineFont3 KerningCount")
        kerning_count = u16(kerning, 0)
        record_width = 2 * code_width + 2
        if len(kerning) != 2 + kerning_count * record_width:
            raise ValueError("invalid DefineFont3 kerning table length")
        for code, shape, advance, bound in zip(code_values, glyph_shapes, advances, bounds):
            if code in glyphs:
                raise ValueError("duplicate codepoint U+%04X in font %d" % (code, font_id))
            glyphs[code] = FontGlyph(code, shape, advance, bound)
    else:
        raise ValueError("font %d has no layout; this build expects HasLayout" % font_id)

    if code_values != sorted(code_values):
        raise ValueError("font %d CodeTable is not sorted" % font_id)
    return Font3(font_id, flags, payload[5:prefix_end], payload[:prefix_end], glyphs,
                 metrics, kerning, wide_offsets, wide_codes)


def rebuild_font3(font: Font3, ttf_path: Path) -> tuple[bytes, int]:
    ttfont = TTFont(str(ttf_path), recalcBBoxes=False, recalcTimestamp=False)
    if "glyf" not in ttfont:
        raise ValueError("%s is not a TrueType glyf font" % ttf_path)
    units_per_em = ttfont["head"].unitsPerEm
    scale = 20480.0 / units_per_em
    cmap = ttfont.getBestCmap()
    existing = set(font.glyphs)
    requested = set(EXTRA_CODES)
    for start, end in TARGET_RANGES:
        requested.update(range(start, end))
    additions = sorted((requested & set(cmap)) - existing)

    merged = dict(font.glyphs)
    glyph_set = ttfont.getGlyphSet()
    for code in additions:
        glyph_name = cmap[code]
        shape, rect = make_glyph_shape(glyph_set, glyph_name, scale)
        advance_units = ttfont["hmtx"].metrics[glyph_name][0]
        advance = int(round(advance_units * scale))
        if not -32768 <= advance <= 32767:
            raise ValueError("U+%04X advance %d does not fit SI16" % (code, advance))
        merged[code] = FontGlyph(code, shape, advance, make_rect(rect))

    codes = sorted(merged)
    if len(codes) > 65535:
        raise ValueError("DefineFont3 NumGlyphs exceeds 65535")
    new_flags = font.flags | 0x0C  # wide offsets + UCS-2 code table
    offset_width = 4
    table_start = len(font.prefix) + 2
    first_glyph = (len(codes) + 1) * offset_width
    offsets = []
    cursor = first_glyph
    shape_bytes = bytearray()
    for code in codes:
        glyph = merged[code]
        offsets.append(cursor)
        shape_bytes.extend(glyph.shape)
        cursor += len(glyph.shape)
    code_offset = cursor
    if code_offset >= 2 ** 32 or any(value >= 2 ** 32 for value in offsets):
        raise ValueError("DefineFont3 offset exceeds 32-bit range")

    prefix = bytearray(font.prefix)
    prefix[2] = new_flags
    out = bytearray(prefix)
    out += struct.pack("<H", len(codes))
    for offset in offsets:
        out += struct.pack("<I", offset)
    out += struct.pack("<I", code_offset)
    out += shape_bytes
    for code in codes:
        out += struct.pack("<H", code)
    out += font.metrics
    for code in codes:
        out += struct.pack("<h", merged[code].advance)
    for code in codes:
        out += merged[code].bounds
    out += font.kerning

    # Parse the rebuilt payload again; this checks offsets, bounds and kerning.
    rebuilt = parse_font3(bytes(out))
    if sorted(rebuilt.glyphs) != codes:
        raise AssertionError("rebuilt CodeTable verification failed")
    for code, old_glyph in font.glyphs.items():
        if rebuilt.glyphs[code] != old_glyph:
            raise AssertionError("original glyph U+%04X changed in font %d" % (code, font.font_id))
    return bytes(out), len(additions)


@dataclass
class Tag:
    code: int
    start: int
    end: int
    payload: bytes
    header_size: int


def parse_gfx(data: bytes) -> tuple[int, list[Tag]]:
    if len(data) < 12 or data[:3] != b"GFX":
        raise ValueError("expected an uncompressed GFX file")
    if u32(data, 4) != len(data):
        raise ValueError("GFX file length header does not match file size")
    nbits = read_bits(data, 8 * 8, 5)
    rect_size = (5 + 4 * nbits + 7) // 8
    pos = 8 + rect_size + 4  # RECT + frame rate + frame count
    tags = []
    saw_end = False
    while pos + 2 <= len(data):
        start = pos
        record = u16(data, pos)
        pos += 2
        code, length = record >> 6, record & 0x3F
        header_size = 2
        if length == 0x3F:
            if pos + 4 > len(data):
                raise ValueError("truncated long tag header")
            length = u32(data, pos)
            pos += 4
            header_size = 6
        end = pos + length
        if end > len(data):
            raise ValueError("tag %d at %d extends past file end" % (code, start))
        tags.append(Tag(code, start, end, data[pos:end], header_size))
        pos = end
        if code == 0:
            saw_end = True
            break
    if not saw_end or pos != len(data):
        raise ValueError("GFX tag stream has no final End tag or trailing bytes")
    return 8 + rect_size + 4, tags


def pack_tag(code: int, payload: bytes) -> bytes:
    if len(payload) < 0x3F:
        return struct.pack("<H", (code << 6) | len(payload)) + payload
    return struct.pack("<HI", (code << 6) | 0x3F, len(payload)) + payload


def add_persian(input_path: Path, font_dir: Path, output_path: Path):
    data = input_path.read_bytes()
    tags_start, tags = parse_gfx(data)
    found = {}
    rebuilt_tags = []
    counts = {}
    for tag in tags:
        if tag.code == TAG_DEFINE_FONT3:
            font = parse_font3(tag.payload)
            if font.font_id in FONT_MAPPINGS:
                if font.font_id in found:
                    raise ValueError("duplicate DefineFont3 id %d" % font.font_id)
                ttf_path = font_dir / FONT_MAPPINGS[font.font_id]
                if not ttf_path.is_file():
                    raise FileNotFoundError(ttf_path)
                payload, added = rebuild_font3(font, ttf_path)
                found[font.font_id] = True
                counts[font.font_id] = added
                rebuilt_tags.append(pack_tag(tag.code, payload))
                continue
        rebuilt_tags.append(data[tag.start:tag.end])

    missing = sorted(set(FONT_MAPPINGS) - set(found))
    if missing:
        raise ValueError("expected embedded font IDs were not found: %s" % missing)
    out = bytearray(data[:tags_start])
    for raw_tag in rebuilt_tags:
        out.extend(raw_tag)
    struct.pack_into("<I", out, 4, len(out))
    # Validate the final file and every rebuilt font's full Arabic coverage.
    _, final_tags = parse_gfx(bytes(out))
    if len(final_tags) != len(tags) or [t.code for t in final_tags] != [t.code for t in tags]:
        raise AssertionError("SWF tag sequence changed while embedding glyphs")
    for old_tag, new_tag in zip(tags, final_tags):
        if old_tag.code != TAG_DEFINE_FONT3:
            if data[old_tag.start:old_tag.end] != bytes(out)[new_tag.start:new_tag.end]:
                raise AssertionError("non-font tag %d was modified" % old_tag.code)
        elif u16(old_tag.payload, 0) not in FONT_MAPPINGS:
            if old_tag.payload != new_tag.payload:
                raise AssertionError("unselected DefineFont3 tag was modified")
    by_id = {}
    for tag in final_tags:
        if tag.code == TAG_DEFINE_FONT3:
            font = parse_font3(tag.payload)
            if font.font_id in FONT_MAPPINGS:
                by_id[font.font_id] = font
    requested = set(EXTRA_CODES)
    for start, end in TARGET_RANGES:
        requested.update(range(start, end))
    for font_id, font in by_id.items():
        ttf = TTFont(str(font_dir / FONT_MAPPINGS[font_id]))
        expected = requested & set(ttf.getBestCmap())
        missing_codes = expected - set(font.glyphs)
        if missing_codes:
            raise AssertionError("font %d is missing U+%04X" % (font_id, min(missing_codes)))
        if sorted(font.glyphs) != list(font.glyphs):
            raise AssertionError("font %d CodeTable is not sorted" % font_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(out)
    print("Input: %s (%s bytes)" % (input_path, len(data)))
    print("Output: %s (%s bytes)" % (output_path, len(out)))
    for font_id in sorted(counts):
        print("Font ID %d: added %d mapped Persian/Arabic glyphs" % (font_id, counts[font_id]))


def main():
    parser = argparse.ArgumentParser(
        description="افزودن گلیف‌های عربی/فارسی Vazirmatn به پنج DefineFont3 در فایل GFx.",
        epilog=("نمونه: python3 tools/gfx_font.py originals/fonts_en_pc.gfx "
                "work/vazirmatn-ttf fonts_en_pc.gfx"),
    )
    parser.add_argument("input", type=Path, help="فایل اصلی fonts_en_pc.gfx")
    parser.add_argument("font_dir", type=Path,
                        help="پوشه‌ی TTFهای ثابت Vazirmatn (Regular/Medium/Bold/ExtraBold)")
    parser.add_argument("output", type=Path, help="مسیر خروجی GFX")
    args = parser.parse_args()
    add_persian(args.input, args.font_dir, args.output)


if __name__ == "__main__":
    main()
