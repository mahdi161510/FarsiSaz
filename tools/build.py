# -*- coding: utf-8 -*-
"""
build.py - ساخت فایل نهایی XML فارسی از روی حافظه‌ی ترجمه

کارها:
  1. خواندن stringtable_en_*.xml (دست‌نخورده)
  2. جای‌گذاری ترجمه‌های پوشه‌ی translations/ (رشته‌های ترجمه‌نشده انگلیسی می‌مانند)
  3. اعتبارسنجی کامل: ساختار XML، تعداد و ترتیب StringIDها، حفظ توکن‌های فنی
     (#E_CTRL_MAP#, %s, {0}, [RET], &lt;bold&gt;, $) و پایان خطوط CRLF و BOM
  4. نوشتن خروجی در پوشه‌ی release/

استفاده:
    python3 tools/build.py                  # خروجی با نام en (جایگزین مستقیم فایل بازی)
    python3 tools/build.py --lang fa        # خروجی با نام fa
    python3 tools/build.py --check          # فقط اعتبارسنجی، بدون نوشتن فایل
    python3 tools/build.py --strict         # در صورت خطای توکن، خروجی نمی‌دهد
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fslib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH_DIR = os.path.join(ROOT, "translations", "batches")
WORK = os.path.join(ROOT, "work")
OUT_DIR = ROOT   # خروجی نهایی: ریشه‌ی مخزن (جایگزین مستقیم فایل‌های بازی)
REPORT_DIR = os.path.join(ROOT, "release")   # گزارش‌های تولیدی

SOURCES = [
    ("common", os.path.join(ROOT, "source", "stringtable_en_common_group.xml")),
    ("pc", os.path.join(ROOT, "source", "stringtable_en_pc_group.xml")),
]

INDEX_FILES = [os.path.join(WORK, "index_common.tsv"), os.path.join(WORK, "index_pc.tsv")]


def validate(source_raw: str, out_raw: str, tm: dict, label: str):
    """خروجی را با منبع مقایسه می‌کند و فهرست مشکلات را برمی‌گرداند."""
    errors, warnings = [], []

    # ۱) XML باید خوش‌ساخت باشد
    try:
        ET.fromstring(out_raw)
    except ET.ParseError as exc:
        errors.append("XML خوش‌ساخت نیست: %s" % exc)

    # ۲) تعداد و ترتیب StringIDها باید دقیقاً مثل منبع باشد
    src_ids = [sid for sid, _b, _m in fslib.iter_items(source_raw)]
    out_ids = [sid for sid, _b, _m in fslib.iter_items(out_raw)]
    if len(src_ids) != len(out_ids):
        errors.append("تعداد آیتم‌ها تغییر کرد: %d -> %d" % (len(src_ids), len(out_ids)))
    else:
        diff = [i for i, (a, b) in enumerate(zip(src_ids, out_ids)) if a != b]
        if diff:
            errors.append("ترتیب/مقدار StringID در %d آیتم عوض شده (اولین: #%d)"
                          % (len(diff), diff[0]))

    # ۳) بررسی تک‌تک رشته‌های ترجمه‌شده
    src_bodies = [b for _s, b, _m in fslib.iter_items(source_raw)]
    out_bodies = [b for _s, b, _m in fslib.iter_items(out_raw)]
    changed = 0
    rtl_missing = 0
    for en, fa in zip(src_bodies, out_bodies):
        if en == fa:
            continue
        changed += 1
        problems = fslib.token_report(en, fa)
        if problems:
            errors.append("توکن فنی [%s] -> %s | %r"
                          % (label, "، ".join(problems), en[:70]))
        bad = fslib.BAD_CTRL_RE.findall(fa)
        if bad:
            errors.append("نویسه‌ی کنترلی مجاز نیست [%s]: %r در %r" % (label, bad, fa[:60]))
        if not fslib.has_rtl(fa) and fa.strip() != en.strip():
            rtl_missing += 1
        # طول ترجمه نباید نجومی بیشتر از متن اصلی باشد (نشانه‌ی اشتباه)
        if len(fa) > len(en) * 6 + 40:
            warnings.append("ترجمه خیلی بلندتر از متن اصلی [%s]: %r" % (label, en[:50]))
        # تعداد شکست خط‌ها: کم شدن شکست خط نشانه‌ی از دست رفتن متن است
        # (بیشتر شدن مجاز است، چون مثلاً اعتبار فارسی‌ساز به تیتراژ اضافه می‌شود)
        if fa.count("\n") < en.count("\n"):
            warnings.append("شکست خط کمتر از متن اصلی [%s]: %d در برابر %d | %r"
                            % (label, en.count("\n"), fa.count("\n"), en[:50]))
        # & خام (بدون entity) رشته را می‌شکند
        for m in re.finditer(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", fa):
            errors.append("& بدون escape در ترجمه [%s]: %r" % (label, fa[:60]))
            break

    # ۴) پایان خطوط باید CRLF باشد و LF تنها نداشته باشیم
    crlf = out_raw.count("\r\n")
    lf = out_raw.count("\n")
    if lf != crlf:
        errors.append("پایان خطوط یکدست نیست: CRLF=%d ولی LF=%d" % (crlf, lf))

    if rtl_missing:
        warnings.append("%d ترجمه بدون نویسه‌ی فارسی/عربی است (اسم خاص؟)" % rtl_missing)

    return errors, warnings, changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en", help="کد زبان در نام فایل خروجی (پیش‌فرض: en)")
    ap.add_argument("--out", default=OUT_DIR, help="پوشه‌ی خروجی")
    ap.add_argument("--check", action="store_true", help="فقط اعتبارسنجی")
    ap.add_argument("--strict", action="store_true", help="با خطا خروجی ننویس")
    args = ap.parse_args()

    print("خواندن فهرست مادر از %s ..." % WORK)
    index = fslib.load_index(INDEX_FILES)
    if not index:
        print("! فهرست مادر پیدا نشد. اول این را اجرا کنید:\n    python3 tools/extract.py")
        return 2
    print("خواندن حافظه‌ی ترجمه از %s ..." % BATCH_DIR)
    tm, ids, problems = fslib.load_tm(BATCH_DIR, index)
    print("مجموع: %d رشته‌ی یکتای ترجمه‌شده (از %d)\n" % (len(ids), len(index)))
    for p in problems[:20]:
        print("   ! %s" % p)
    all_errors = list(problems)
    all_warnings = []
    report_lines = ["گزارش اعتبارسنجی فارسی‌ساز Mafia III", "=" * 46, ""]
    grand_total = grand_changed = 0

    for label, path in SOURCES:
        if not os.path.exists(path):
            print("! پیدا نشد: %s" % path)
            continue
        source_raw = fslib.read_source(path)
        stats = {"total": 0, "translated": 0, "kept": 0}
        out_raw, stats = fslib.apply_tm(source_raw, tm, stats)

        errors, warnings, changed = validate(source_raw, out_raw, tm, label)
        all_errors += errors
        all_warnings += warnings
        grand_total += stats["total"]
        grand_changed += changed

        pct = 100.0 * stats["translated"] / max(stats["total"], 1)
        print("== %-7s آیتم‌ها: %6d | ترجمه‌شده: %6d (%5.1f%%) | انگلیسی مانده: %6d"
              % (label, stats["total"], stats["translated"], pct, stats["kept"]))
        for w in warnings[:10]:
            print("   ~ %s" % w)
        for e in errors[:15]:
            print("   ! %s" % e)

        report_lines += [
            "فایل: %s" % os.path.basename(path),
            "  تعداد آیتم          : %d" % stats["total"],
            "  آیتم با متن فارسی    : %d (%.1f%%)" % (stats["translated"], pct),
            "  آیتم باقی‌مانده انگلیسی: %d" % stats["kept"],
            "  خطاها                : %d" % len(errors),
            "  هشدارها              : %d" % len(warnings),
            "",
        ]
        report_lines += ["  ! " + e for e in errors]
        report_lines += ["  ~ " + w for w in warnings]
        report_lines.append("")

        if not args.check:
            if errors and args.strict:
                print("   به دلیل --strict و وجود خطا، فایل نوشته نشد.")
                continue
            out_path = os.path.join(
                args.out, "stringtable_%s_%s_group.xml" % (args.lang, label))
            fslib.write_source(out_path, out_raw)
            size = os.path.getsize(out_path)
            print("   -> نوشتن %s (%.1f MB)" % (out_path, size / 1048576.0))

    report_lines += [
        "مجموع آیتم‌ها        : %d" % grand_total,
        "مجموع تغییر یافته    : %d" % grand_changed,
        "کل خطاها            : %d" % len(all_errors),
        "کل هشدارها          : %d" % len(all_warnings),
    ]

    if not args.check:
        os.makedirs(REPORT_DIR, exist_ok=True)
        with open(os.path.join(REPORT_DIR, "VALIDATION.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(report_lines) + "\n")

    print("\nجمع کل: %d آیتم، %d مورد فارسی شد، %d خطا، %d هشدار"
          % (grand_total, grand_changed, len(all_errors), len(all_warnings)))
    if not args.check:
        print("یادآوری: فایل‌های xbin هنوز از روی این XMLها ساخته نشده‌اند؛"
              " اجرای `python3 tools/xbin.py` فراموش نشود.")
    return 1 if (all_errors and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
