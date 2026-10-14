# -*- coding: utf-8 -*-
"""subtitles.py - خواندن جدول زیرنویس بازی (SubtitleTable) و استخراج نگاشت‌ها.

فایل ورودی همان چیزی است که بازی در `SubtitleTable.xbin` نگه می‌دارد و به‌صورت
XML قابل استخراج است. هر رکورد این‌ها را دارد:

    SubtitleID        کلید صوتی (AkHashName، هش ۳۲ بیتی FNV-1)
    SoundID           نام ساند بانک (AkHashName)
    FacialAnimName    انیمیشن صورت (XBinHashName، هش ۶۴ بیتی FNV-1)
    LongStringID      کلیدِ متنِ زیرنویس در جدول رشته‌ها (XBinHashName)
    ShortStringID     کلیدِ متن کوتاه (در نمونه‌ها خالی است)
    SubtitleCharacter نامِ گوینده؛ همان کلیدِ رشتهٔ برچسب نام در جدول رشته‌ها

نکته‌های کلیدی که با این فایل روشن می‌شود:

  * هشِ ۶۴ بیتی بازی `FNV-1` است (نه 1a) و `StringID`های جدول رشته‌ها
    دقیقاً همین هش روی «کلید» هستند. پس می‌توان از نام گوینده (`SubtitleCharacter`)
    کلیدِ ردیفِ برچسب را ساخت:  `id = fnv1_64(name)`.
  * هر ردیف زیرنویس با `LongStringID` به یکی از ردیف‌های جدول رشته‌ها وصل است؛
    یعنی دقیقاً می‌دانیم کدام رشته‌ها زیرنویس‌اند و کدام گوینده دارند.

خروجی‌های ابزار: فهرست گویندگان، ردیف‌های برچسب، ردیف‌های زیرنویس، و گزارش
پوشش/موارد گم‌شده در جدول رشته‌های خودمان.
"""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FNV64_OFFSET = 0xCBF29CE484222325
FNV64_PRIME = 0x100000001B3
FNV32_OFFSET = 2166136261
FNV32_PRIME = 16777619


def fnv1_64(text: str) -> int:
    """هش ۶۴ بیتی FNV-1 — همان چیزی که بازی برای XBinHashName/StringID می‌سازد."""
    value = FNV64_OFFSET
    for byte in text.encode("utf-8"):
        value = (value * FNV64_PRIME) & 0xFFFFFFFFFFFFFFFF
        value ^= byte
    return value


def fnv1_32(text: str) -> int:
    """هش ۳۲ بیتی FNV-1 — همان چیزی که بازی برای XBinAkHashName می‌سازد."""
    value = FNV32_OFFSET
    for byte in text.encode("utf-8"):
        value = (value * FNV32_PRIME) & 0xFFFFFFFF
        value ^= byte
    return value


class Subtitle:
    __slots__ = ("subtitle_id", "sound_id", "text_id", "short_id", "character")

    def __init__(self, subtitle_id: int, sound_id: int, text_id: int, short_id: int, character: str):
        self.subtitle_id = subtitle_id
        self.sound_id = sound_id
        self.text_id = text_id
        self.short_id = short_id
        self.character = character


def _hash_of(node, tag: str, default: int = 0) -> int:
    child = node.find(tag)
    if child is None:
        return default
    raw = child.get("Hash")
    return int(raw) if raw else default


def _name_of(node, tag: str, default: str = "") -> str:
    child = node.find(tag)
    if child is None:
        return default
    return (child.get("Name") or "").strip()


def read_subtitle_table(path: str) -> list[Subtitle]:
    """جدول زیرنویس را می‌خواند (فایل‌های چند ده مگابایتی را هم تحمل می‌کند)."""
    subtitles = []
    for _event, node in ET.iterparse(path, events=("end",)):
        if node.tag != "SubtitleTableItem":
            continue
        subtitles.append(Subtitle(
            subtitle_id=_hash_of(node, "SubtitleID"),
            sound_id=_hash_of(node, "SoundID"),
            text_id=_hash_of(node, "LongStringID"),
            short_id=_hash_of(node, "ShortStringID"),
            character=_name_of(node, "SubtitleCharacter"),
        ))
        node.clear()
    return subtitles


def characters(subtitles: list[Subtitle]) -> dict[str, int]:
    """نام گوینده -> کلید ردیف برچسب در جدول رشته‌ها (`fnv1_64`)."""
    result = {}
    for sub in subtitles:
        if sub.character:
            result.setdefault(sub.character, fnv1_64(sub.character))
    return result


def load_string_ids(*paths: str) -> dict[int, str]:
    """کلیدهای جدول رشته‌ها (common/pc) را از xbinها می‌خواند."""
    import xbin as X

    table = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        items = X.read_items(path) if path.endswith(".xml") else X.unpack(path)["items"]
        for sid, text in items:
            table.setdefault(sid, text)
    return table


def report(table_path: str, xbin_paths: list[str], limit: int = 12) -> None:
    subtitles = read_subtitle_table(table_path)
    chars = characters(subtitles)
    strings = load_string_ids(*xbin_paths)
    print("رکوردهای زیرنویس: %s" % format(len(subtitles), ","))
    print("گویندگان یکتا: %s" % format(len(chars), ","))

    rows = Counter(sub.character for sub in subtitles if sub.character)
    missing = [(name, key) for name, key in sorted(chars.items()) if key not in strings]
    print("گویندگان بدون ردیف برچسب در جدول رشته‌ها: %s" % format(len(missing), ","))
    for name, key in missing[:limit]:
        print("   ! %-14s %d" % (name, key))

    text_ids = {sub.text_id for sub in subtitles if sub.text_id}
    unknown = [sid for sid in text_ids if sid not in strings]
    print("کلیدهای متنِ زیرنویس: %s (موجود در جدول: %s)"
          % (format(len(text_ids), ","), format(len(text_ids) - len(unknown), ",")))
    for sid in unknown[:limit]:
        print("   ! %d بدون ردیف متن" % sid)

    blank = [sid for sid in text_ids if sid in strings and not strings[sid].strip()]
    print("زیرنویس‌های با متن خالی: %d" % len(blank))

    print("\nپرکاربردترین گویندگان (بر پایهٔ تعداد رکورد زیرنویس):")
    for name, count in rows.most_common(limit):
        key = fnv1_64(name)
        state = "✓" if key in strings else "✗"
        print("   %s %-16s %5d رکورد   id=%d" % (state, name, count, key))


def main() -> None:
    parser = argparse.ArgumentParser(description="گزارش جدول زیرنویس بازی (SubtitleTable).")
    parser.add_argument("table", help="مسیر فایل XML جدول زیرنویس")
    parser.add_argument("--strings", nargs="*",
                        default=["stringtable_en_common_group.xbin", "stringtable_en_pc_group.xbin"],
                        help="xbinهای جدول رشته‌ها برای تطبیق")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    report(args.table, args.strings, args.limit)


if __name__ == "__main__":
    main()
