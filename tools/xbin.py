# -*- coding: utf-8 -*-
"""
xbin.py - تبدیل XML جدول رشته‌های Mafia III به فرمت باینری xbin بازی (و برعکس)

بازی متن‌ها را به‌صورت فایل `stringtable_<lang>_<group>_group.xbin` داخل آرشیوهای
`sds_retail/string_tables/*.sds` نگه می‌دارد. این ابزار همان قالب را می‌سازد.

قالب باینری (همه little-endian) - برگرفته از دو پیاده‌سازی مستقل:
  https://github.com/rm-NoobInCoding/MafiaXbinTool   (مخصوص بومی‌سازی Mafia 3)
  https://github.com/midoriiro/MafiaSdk              (کلاس XBin/StringTable)

    آفست  اندازه  محتوا
    0     8       FileID      = 0x5E42EF29E8A3E1D3  (هش نوع StringTable)
    8     8       FileVersion = 4
    16    4       -1
    20    4       EntrySize   = 16
    24    4       count       (int32)
    28    8       count       (uint64؛ ۴ بایت دوم، Unk0 اولین آیتم = 0 است)
    36    16*count  برای هر آیتم: StringID (uint64) + Offset (uint64)
    ...   بقیه    رشته‌های یکتا: UTF-8 + بایت NUL، به ترتیب نخستین استفاده

    Offset_i = (count - i) * 16 + (آفست متن یکتای موردنظر در pool) - 8
    مکان متن_i = (36 + 16*(i+1)) + Offset_i - 8

متن‌های تکراری فقط یک‌بار ذخیره می‌شوند؛ ردیف‌های مختلف می‌توانند به یک متن اشاره کنند.
در `pack` و `patch` متن RTL فقط در باینری پیش‌شکل‌دهی و بصری می‌شود؛ XML دست‌نخورده
می‌ماند. `compare` و `diff` متن خام را بررسی می‌کنند.

ترتیب آیتم‌ها باید صعودی بر اساس StringID باشد (بازی با هش کار می‌کند).

استفاده:
    python3 tools/xbin.py                 # ساخت هر دو فایل xbin در ریشه‌ی مخزن
    python3 tools/xbin.py --test          # تست رفت‌وبرگشت (XML -> xbin -> XML)
    python3 tools/xbin.py --unpack in.xbin out.xml    # تبدیل xbin به XML
    python3 tools/xbin.py --compare original.xbin     # راستی‌آزمایی بایت‌به‌بایت قالب
    python3 tools/xbin.py --diff original.xbin [xml]  # مقایسه‌ی ترجمه با فایل اصلی
    python3 tools/xbin.py --patch original.xbin xml out.xbin  # حفظ هدر و StringID اصلی
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fslib  # noqa: E402
from shape import shape_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILE_ID = 0x5E42EF29E8A3E1D3
FILE_VERSION = 4
ALWAYS_MINUS_ONE = -1
ENTRY_SIZE = 16
HEADER_SIZE = 36          # 8 + 8 + 4 + 4 + 4 + 8

# فایل‌هایی که بسته‌بندی می‌شوند: (xml ورودی، xbin خروجی)
JOBS = [
    ("stringtable_en_common_group.xml", "stringtable_en_common_group.xbin"),
    ("stringtable_en_pc_group.xml", "stringtable_en_pc_group.xbin"),
]

ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos|#\d+|#[xX][0-9a-fA-F]+);")
_ENTITY_MAP = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def xml_unescape(text: str) -> str:
    """entity های XML را به نویسه‌ی واقعی برمی‌گرداند (بدون دست زدن به شکست خط‌ها)."""
    def repl(m):
        ent = m.group(1)
        if ent in _ENTITY_MAP:
            return _ENTITY_MAP[ent]
        if ent.startswith("#x") or ent.startswith("#X"):
            return chr(int(ent[2:], 16))
        return chr(int(ent[1:]))
    return ENTITY_RE.sub(repl, text)


def xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# خواندن آیتم‌ها از XML
# ---------------------------------------------------------------------------

def read_items(xml_path: str):
    """فهرست (StringID, متن) را از XML می‌خواند.

    عمداً از پارسر XML استفاده نمی‌کنیم، چون پارسر طبق استاندارد XML
    همه‌ی \r\n ها را به \n تبدیل می‌کند و متن بازی خراب می‌شود.
    """
    raw = fslib.read_source(xml_path)
    items = []
    for sid, body, _m in fslib.iter_items(raw):
        items.append((int(sid), xml_unescape(body)))
    return items


def write_xml(items, xml_path: str) -> None:
    """دقیقاً همان قالب XML منبع را بازتولید می‌کند (BOM + CRLF)."""
    out = ['<?xml version="1.0" encoding="utf-8"?>\r\n', "<StringTable>\r\n", "  <Items>\r\n"]
    for sid, text in items:
        out.append('    <LocalisableString StringID="%d">\r\n' % sid)
        out.append('      <Content Type="String">%s</Content>\r\n' % xml_escape(text))
        out.append("    </LocalisableString>\r\n")
    out.append("  </Items>\r\n</StringTable>")
    with open(xml_path, "wb") as fh:
        fh.write(fslib.BOM_BYTES)
        fh.write("".join(out).encode("utf-8"))


# ---------------------------------------------------------------------------
# بسته‌بندی / بازکردن xbin
# ---------------------------------------------------------------------------

def pack_bytes(items, verbose: bool = True, *, header_bytes=None, string_id_bytes=None,
               shape_rtl: bool = True):
    """items را به xbin تبدیل می‌کند؛ متن‌های یکسان فقط یک‌بار در داده ذخیره می‌شوند.

    فایل‌های اصلی Mafia III رشته‌های تکراری را intern می‌کنند و چند ردیف
    می‌توانند به یک متن مشترک اشاره کنند. header_bytes و string_id_bytes فقط
    برای --patch هستند تا آن بخش‌ها عیناً از xbin اصلی حفظ شوند.
    """
    items = list(items)
    count = len(items)

    # ترتیب صعودی StringID (بازی بر اساس هش جست‌وجو می‌کند)
    unsorted_at = next((i for i in range(1, count) if items[i][0] < items[i - 1][0]), -1)
    if unsorted_at != -1:
        raise SystemExit("! آیتم‌ها بر اساس StringID صعودی نیستند (اولین مورد در ایندکس %d)."
                         " ترتیب فایل منبع را تغییر ندهید." % unsorted_at)

    if header_bytes is None:
        head = bytearray()
        head += struct.pack("<Q", FILE_ID)
        head += struct.pack("<q", FILE_VERSION)
        head += struct.pack("<i", ALWAYS_MINUS_ONE)
        head += struct.pack("<i", ENTRY_SIZE)
        head += struct.pack("<i", count)
        head += struct.pack("<Q", count)      # count1 + Unk0 اولین آیتم (= 0)
    else:
        head = bytearray(header_bytes)
        if len(head) != HEADER_SIZE:
            raise SystemExit("! اندازه‌ی هدر برای --patch باید دقیقاً %d بایت باشد." % HEADER_SIZE)
        header_count32 = struct.unpack_from("<i", head, 24)[0]
        header_count64 = struct.unpack_from("<Q", head, 28)[0]
        if header_count32 != count or header_count64 != count:
            raise SystemExit("! تعداد آیتم‌ها با هدر اصلی یکی نیست (%d، هدر: %d/%d)."
                             % (count, header_count32, header_count64))

    if string_id_bytes is not None:
        string_id_bytes = list(string_id_bytes)
        if len(string_id_bytes) != count or any(len(sid) != 8 for sid in string_id_bytes):
            raise SystemExit("! داده‌ی StringID اصلی برای --patch ناقص یا نامعتبر است.")

    entries = bytearray()
    chunk = bytearray()
    string_offsets = {}
    for i, (sid, text) in enumerate(items):
        # فقط باینری بازی شکل‌دهی می‌شود؛ XML، بچ‌ها و حافظه‌ی ترجمه خوانا می‌مانند.
        wire_text = shape_text(text) if shape_rtl else text
        data = wire_text.encode("utf-8") + b"\x00"
        string_offset = string_offsets.get(data)
        if string_offset is None:
            string_offset = len(chunk)
            string_offsets[data] = string_offset
            chunk += data

        # offset نسبت به فیلد آفست است؛ متن تکراری به نسخه‌ی نخست اشاره می‌کند.
        offset = (count - i) * ENTRY_SIZE + string_offset - 8
        if string_id_bytes is None:
            entries += struct.pack("<Q", sid)
        else:
            raw_sid = bytes(string_id_bytes[i])
            if struct.unpack("<Q", raw_sid)[0] != sid:
                raise SystemExit("! StringID ردیف %d با فایل اصلی یکی نیست." % i)
            entries += raw_sid
        entries += struct.pack("<Q", offset)

    blob = bytes(head) + bytes(entries) + bytes(chunk)

    info = {
        "blob": blob,
        "count": count,
        "bytes": len(blob),
        "header": HEADER_SIZE,
        "entries": len(entries),
        "strings": len(chunk),
        "unique_strings": len(string_offsets),
    }
    if verbose:
        print("     آیتم‌ها: %s | متن‌های یکتا: %s | اندازه: %.2f MB (هدر %d + جدول %d + متن‌ها %d)"
              % (format(count, ","), format(len(string_offsets), ","),
                 len(blob) / 1048576.0, HEADER_SIZE, len(entries), len(chunk)))
    return info


def pack(items, xbin_path: str, verbose: bool = True, *, shape_rtl: bool = True) -> dict:
    """items را بسته‌بندی کرده و در xbin_path می‌نویسد.

    به‌طور پیش‌فرض متن RTL فقط در باینری پیش‌شکل‌دهی و بصری می‌شود.
    """
    info = pack_bytes(items, verbose=False, shape_rtl=shape_rtl)
    with open(xbin_path, "wb") as fh:
        fh.write(info["blob"])
    if verbose:
        print("  -> %s" % xbin_path)
        print("     آیتم‌ها: %s | اندازه: %.2f MB (هدر %d + جدول %d + متن‌ها %d)"
              % (format(info["count"], ","), info["bytes"] / 1048576.0, HEADER_SIZE,
                 info["entries"], info["strings"]))
    return info


def compare(original_path: str) -> int:
    """یک xbin اصلیِ بازی را باز کرده، دوباره می‌سازد و بایت‌به‌بایت مقایسه می‌کند.

    اگر خروجی با فایل اصلی یکی باشد، یعنی این ابزار دقیقاً همان فرمت بازی را
    می‌سازد و فایل‌های فارسی با اطمینان کامل در بازی کار می‌کنند.
    """
    with open(original_path, "rb") as fh:
        orig = fh.read()
    print("== مقایسه با %s (%s بایت)" % (original_path, format(len(orig), ",")))
    print("   هدر اصلی: FileID=0x%X version=%d field16=%d EntrySize=%d count32=%d count64=%d"
          % struct.unpack_from("<QqiIiQ", orig, 0))
    items = unpack(original_path)["items"]
    mine = pack_bytes(items, verbose=False, shape_rtl=False)["blob"]
    print("   آیتم‌ها: %s" % format(len(items), ","))
    if mine == orig:
        print("   ✔ خروجی این ابزار بایت‌به‌بایت با فایل اصلیِ بازی یکی است.")
        return 0
    print("   ✘ تفاوت وجود دارد: طول %d در برابر %d" % (len(orig), len(mine)))
    for i, (a, b) in enumerate(zip(orig, mine)):
        if a != b:
            lo = max(0, i - 16)
            print("     اولین تفاوت در بایت %d" % i)
            print("     اصلی : %s" % orig[lo:i + 24].hex(" "))
            print("     ما   : %s" % mine[lo:i + 24].hex(" "))
            break
    return 1


def unpack(xbin_path: str):
    """یک فایل xbin را می‌خواند و فهرست (StringID, متن) را برمی‌گرداند."""
    with open(xbin_path, "rb") as fh:
        blob = fh.read()

    if len(blob) < HEADER_SIZE:
        raise SystemExit("! فایل xbin کوتاه‌تر از هدر %d بایتی است." % HEADER_SIZE)
    file_id, version, minus_one, entry_size, count32, count64 = struct.unpack_from(
        "<QqiIiQ", blob, 0)
    if file_id != FILE_ID:
        raise SystemExit("! FileID ناشناخته: 0x%X (انتظار 0x%X)" % (file_id, FILE_ID))
    if entry_size != ENTRY_SIZE:
        raise SystemExit("! EntrySize غیرمنتظره: %d" % entry_size)
    if count32 < 0:
        raise SystemExit("! تعداد آیتم‌ها منفی است: %d" % count32)
    if count32 != count64:
        raise SystemExit("! تعداد آیتم‌ها هم‌خوان نیست: %d در برابر %d" % (count32, count64))

    table_end = HEADER_SIZE + count32 * ENTRY_SIZE
    if table_end > len(blob):
        raise SystemExit("! جدول آیتم‌ها ناقص است: انتظار %d بایت، فایل %d بایت است."
                         % (table_end, len(blob)))

    items = []
    pos = HEADER_SIZE
    for i in range(count32):
        sid, offset = struct.unpack_from("<QQ", blob, pos)
        str_pos = pos + ENTRY_SIZE + offset - 8
        if str_pos < table_end or str_pos >= len(blob):
            raise SystemExit("! آفست متن ردیف %d خارج از محدوده است: %d" % (i, str_pos))
        try:
            end = blob.index(b"\x00", str_pos)
        except ValueError:
            raise SystemExit("! پایان NUL متن ردیف %d پیدا نشد." % i)
        try:
            text = blob[str_pos:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SystemExit("! متن ردیف %d UTF-8 معتبر نیست: %s" % (i, exc))
        items.append((sid, text))
        pos += ENTRY_SIZE
    return {"version": version, "minus_one": minus_one, "items": items}


def _xml_for_xbin(xbin_path: str) -> str:
    """XML هم‌نام را پیدا می‌کند؛ در حالت عادی خروجی فارسی ریشه اولویت دارد."""
    name = os.path.basename(xbin_path)
    if name.lower().endswith(".xbin"):
        name = name[:-5] + ".xml"
    candidates = [os.path.join(ROOT, name), os.path.join(ROOT, "source", name)]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    raise SystemExit("! XML متناظر پیدا نشد؛ مسیر XML را بعد از نام xbin بدهید.")


def diff(original_path: str, xml_path: str | None = None, limit: int = 20) -> int:
    """متن XML را با xbin اصلی مقایسه می‌کند؛ تغییر متن خطا محسوب نمی‌شود."""
    if xml_path is None:
        xml_path = _xml_for_xbin(original_path)
    original = unpack(original_path)["items"]
    translated = read_items(xml_path)
    print("== مقایسه‌ی متن‌ها: %s ↔ %s" % (original_path, xml_path))
    print("   تعداد اصلی: %s | تعداد XML: %s" % (format(len(original), ","), format(len(translated), ",")))

    count_mismatch = len(original) != len(translated)
    if count_mismatch:
        print("   ✘ تعداد آیتم‌ها یکی نیست؛ ردیف‌های مشترک با هم مقایسه می‌شوند.")

    id_diffs = []
    text_diffs = []
    for i, (old, new) in enumerate(zip(original, translated)):
        old_sid, old_text = old
        new_sid, new_text = new
        if old_sid != new_sid:
            id_diffs.append((i, old_sid, new_sid))
        elif old_text != new_text:
            text_diffs.append((i, old_sid, old_text, new_text))

    print("   شناسه/ترتیب متفاوت: %s | متن متفاوت با شناسه‌ی یکسان: %s"
          % (format(len(id_diffs), ","), format(len(text_diffs), ",")))
    for i, old_sid, new_sid in id_diffs[:limit]:
        print("   ! #%d: StringID اصلی %d، XML %d" % (i, old_sid, new_sid))
    for i, sid, old_text, new_text in text_diffs[:limit]:
        print("   • #%d / %d: %r → %r" % (i, sid, old_text, new_text))
    omitted = max(0, len(id_diffs) - limit) + max(0, len(text_diffs) - limit)
    if omitted:
        print("   … %s تفاوت دیگر نمایش داده نشد." % format(omitted, ","))

    if not count_mismatch and not id_diffs:
        print("   ✔ تعداد و ترتیب StringIDها دقیقاً مطابق فایل اصلی است.")
        return 0
    return 1


def patch(original_path: str, xml_path: str, output_path: str) -> int:
    """XML را با حفظ هدر و بایت‌های StringID اصلی، به xbin تبدیل می‌کند."""
    paths = {os.path.realpath(original_path), os.path.realpath(xml_path)}
    if os.path.realpath(output_path) in paths:
        raise SystemExit("! فایل خروجی --patch نباید روی فایل اصلی یا XML نوشته شود.")

    with open(original_path, "rb") as fh:
        original_blob = fh.read()
    original_items = unpack(original_path)["items"]
    translated = read_items(xml_path)
    if len(original_items) != len(translated):
        raise SystemExit("! تعداد آیتم‌ها برای --patch برابر نیست: %d در برابر %d."
                         % (len(original_items), len(translated)))

    for i, (old, new) in enumerate(zip(original_items, translated)):
        if old[0] != new[0]:
            raise SystemExit("! ترتیب/شناسه در ردیف %d فرق دارد: %d در برابر %d."
                             " برای --patch ترتیب XML را تغییر ندهید."
                             % (i, old[0], new[0]))

    raw_ids = [original_blob[HEADER_SIZE + i * ENTRY_SIZE:
                             HEADER_SIZE + i * ENTRY_SIZE + 8]
               for i in range(len(original_items))]
    info = pack_bytes(translated, verbose=False, header_bytes=original_blob[:HEADER_SIZE],
                      string_id_bytes=raw_ids, shape_rtl=True)
    with open(output_path, "wb") as fh:
        fh.write(info["blob"])

    expected_wire_items = [(sid, shape_text(text)) for sid, text in translated]
    if unpack(output_path)["items"] != expected_wire_items:
        raise SystemExit("! بازخوانی فایل --patch با متنِ پیش‌شکل‌داده‌شده یکی نیست.")
    print("✔ --patch: %s آیتم، هدر و تمام بایت‌های StringID حفظ شد؛ خروجی %s (%.2f MB)"
          % (format(info["count"], ","), output_path, info["bytes"] / 1048576.0))
    return 0


# ---------------------------------------------------------------------------
# تست و اصلی
# ---------------------------------------------------------------------------

def self_test() -> int:
    ok = True
    for xml_name, xbin_name in JOBS:
        xml_path = os.path.join(ROOT, xml_name)
        if not os.path.exists(xml_path):
            print("! پیدا نشد: %s" % xml_path)
            continue
        print("== تست رفت‌وبرگشت %s" % xml_name)
        items = read_items(xml_path)
        tmp_xbin = os.path.join(ROOT, "release", "_test_" + xbin_name)
        os.makedirs(os.path.dirname(tmp_xbin), exist_ok=True)
        pack(items, tmp_xbin, verbose=False, shape_rtl=False)
        back = unpack(tmp_xbin)["items"]

        if len(back) != len(items):
            print("   ! تعداد آیتم‌ها عوض شد: %d -> %d" % (len(items), len(back)))
            ok = False
        diff = [(i, a, b) for i, (a, b) in enumerate(zip(items, back)) if a != b]
        if diff:
            ok = False
            print("   ! %d آیتم متفاوت است؛ اولین: #%d" % (len(diff), diff[0][0]))
            print("     درون: %r" % (diff[0][1],))
            print("     بیرون: %r" % (diff[0][2],))
        else:
            print("   ✔ %s آیتم بدون تغییر بازخوانی شد" % format(len(items), ","))

        tmp_xml = os.path.join(ROOT, "release", "_test_" + xml_name)
        write_xml(back, tmp_xml)
        with open(xml_path, "rb") as fh:
            a = fh.read()
        with open(tmp_xml, "rb") as fh:
            b = fh.read()
        print("   %s XML بازتولیدشده بایت‌به‌بایت مثل ورودی است"
              % ("✔" if a == b else "✘"))
        if a != b:
            ok = False
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print("     اولین تفاوت در بایت %d" % i)
                    print("     ورودی : %r" % a[max(0, i - 60):i + 60])
                    print("     خروجی : %r" % b[max(0, i - 60):i + 60])
                    break
            if len(a) != len(b):
                print("     طول: %d در برابر %d" % (len(a), len(b)))
        os.remove(tmp_xbin)
        os.remove(tmp_xml)

        # مسیر نهایی بازی: shaping/Bidi فقط داخل xbin اعمال و بازخوانی می‌شود.
        tmp_shaped = os.path.join(ROOT, "release", "_shape_test_" + xbin_name)
        pack(items, tmp_shaped, verbose=False, shape_rtl=True)
        expected = [(sid, shape_text(text)) for sid, text in items]
        shaped_back = unpack(tmp_shaped)["items"]
        if shaped_back != expected:
            ok = False
            first = next((i for i, (a, b) in enumerate(zip(expected, shaped_back)) if a != b), -1)
            print("   ✘ بازخوانی متن پیش‌شکل‌داده‌شده نابرابر است؛ اولین ردیف: #%d" % first)
        else:
            print("   ✔ شکل‌دهی RTL و Bidi در xbin برای %s آیتم تأیید شد"
                  % format(len(expected), ","))
        os.remove(tmp_shaped)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="تست رفت‌وبرگشت")
    ap.add_argument("--unpack", nargs=2, metavar=("XBIN", "XML"),
                    help="تبدیل یک فایل xbin به XML")
    ap.add_argument("--pack", nargs=2, metavar=("XML", "XBIN"),
                    help="تبدیل یک فایل XML به xbin")
    ap.add_argument("--compare", metavar="XBIN",
                    help="مقایسه‌ی بایت‌به‌بایت با یک فایل xbin اصلیِ بازی")
    ap.add_argument("--diff", nargs="+", metavar="PATH",
                    help="مقایسه‌ی --diff XBIN [XML]؛ اگر XML نیاید، فایل هم‌نام در ریشه انتخاب می‌شود")
    ap.add_argument("--patch", nargs=3, metavar=("ORIG.xbin", "XML", "OUT.xbin"),
                    help="ساخت xbin با حفظ هدر و StringIDهای فایل اصلی")
    args = ap.parse_args()

    if args.test:
        return self_test()
    if args.compare:
        return compare(args.compare)
    if args.diff is not None:
        if len(args.diff) not in (1, 2):
            ap.error("--diff باید یک یا دو مسیر بگیرد: XBIN [XML]")
        return diff(args.diff[0], args.diff[1] if len(args.diff) == 2 else None)
    if args.patch:
        return patch(*args.patch)
    if args.unpack:
        res = unpack(args.unpack[0])
        write_xml(res["items"], args.unpack[1])
        print("-> %s (%d آیتم، نسخه‌ی فایل %d)"
              % (args.unpack[1], len(res["items"]), res["version"]))
        return 0
    if args.pack:
        pack(read_items(args.pack[0]), args.pack[1])
        return 0

    print("ساخت فایل‌های xbin از XMLهای فارسی...")
    total = 0
    for xml_name, xbin_name in JOBS:
        xml_path = os.path.join(ROOT, xml_name)
        if not os.path.exists(xml_path):
            print("! پیدا نشد: %s" % xml_path)
            continue
        items = read_items(xml_path)
        fa = sum(1 for _s, t in items if fslib.has_rtl(t))
        print("== %s: %s آیتم، %s فارسی (%.1f%%)"
              % (xml_name, format(len(items), ","), format(fa, ","),
                 100.0 * fa / max(len(items), 1)))
        info = pack(items, os.path.join(ROOT, xbin_name))
        total += info["bytes"]

        # بررسی درجا: XML خام است؛ باینری متن‌های RTL را پیش‌شکل‌دهی می‌کند.
        back = unpack(os.path.join(ROOT, xbin_name))["items"]
        expected = [(sid, shape_text(text)) for sid, text in items]
        assert back == expected, "بازخوانی xbin با متن خام/شکل‌دهی‌شده‌ی مورد انتظار یکی نیست!"
        print("     ✔ بازخوانی xbin و شکل‌دهی RTL تأیید شد")
    print("مجموع: %.2f MB" % (total / 1048576.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
