# -*- coding: utf-8 -*-
"""
credits.py - ترجمه‌ی خودکار تیتراژ پایانی (اسامی دست‌نخورده می‌مانند)

تیتراژ بازی از ۱۶ بلوک بزرگ تشکیل شده که داخل آن‌ها عنوان‌های شغلی با
مارکاپ &lt;bold&gt;…&lt;/bold&gt; (و سربرگ‌ها با &lt;h1&gt;/&lt;h2&gt;) از اسامی جدا شده‌اند.
این ابزار فقط همان عنوان‌ها را با واژه‌نامه‌ی translations/credit_titles.tsv
جایگزین می‌کند، اسامی خاص را دست نمی‌زند و در پایانِ تیتراژ اعتبار
فارسی‌ساز را اضافه می‌کند.

خروجی: translations/batches/b900_credits.tsv  (که build.py خودش مصرف می‌کند)

استفاده:
    python3 tools/credits.py            # ساخت بچ تیتراژ
    python3 tools/credits.py --missing  # فقط فهرست عنوان‌های ترجمه‌نشده
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fslib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
TITLES = os.path.join(ROOT, "translations", "credit_titles.tsv")
BATCH_DIR = os.path.join(ROOT, "translations", "batches")

CREDIT_LINE = "ترجمه و فارسی‌سازی توسط UnrealGame.ir"
# بلوکی که تیتراژ با آن تمام می‌شود (اعتبار فارسی‌ساز اینجا اضافه می‌شود)
LAST_BLOCK = "C35221"

MARK_RE = re.compile(r"&lt;(bold|h1|h2)&gt;(.*?)&lt;/\1&gt;", re.S)


def load_titles():
    table = {}
    if not os.path.exists(TITLES):
        return table
    with open(TITLES, "r", encoding="utf-8", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                table[parts[0].strip()] = parts[1].strip()
    return table


def credit_blocks(index):
    """بلوک‌های تیتراژ: رشته‌هایی که مارکاپ عنوان/سربرگ دارند و بلند هستند."""
    out = []
    for sid, en in index.items():
        if len(en) > 1500 and MARK_RE.search(en):
            out.append((sid, en))
    return sorted(out, key=lambda kv: int(kv[0].lstrip("CP")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--missing", action="store_true")
    args = ap.parse_args()

    index = fslib.load_index([os.path.join(WORK, "index_common.tsv"),
                              os.path.join(WORK, "index_pc.tsv")])
    blocks = credit_blocks(index)
    titles = load_titles()

    found = collections.Counter()
    for sid, en in blocks:
        for m in MARK_RE.finditer(en):
            found[m.group(2).strip()] += 1

    if args.missing:
        miss = [t for t in found if t not in titles]
        print("بلوک‌های تیتراژ: %d | عنوان‌های یکتا: %d | ترجمه‌شده: %d | باقی‌مانده: %d"
              % (len(blocks), len(found), len(found) - len(miss), len(miss)))
        for t in sorted(miss, key=lambda x: -found[x]):
            print("%d\t%s" % (found[t], t))
        return 0

    os.makedirs(BATCH_DIR, exist_ok=True)
    out_path = os.path.join(BATCH_DIR, "b900_credits.tsv")
    done_titles = 0
    rows = []
    for sid, en in blocks:
        def repl(m):
            tag, text = m.group(1), m.group(2)
            fa = titles.get(text.strip())
            if fa is None:
                return m.group(0)
            return "&lt;%s&gt;%s&lt;/%s&gt;" % (tag, fa, tag)

        new = MARK_RE.sub(repl, en)
        if new != en:
            done_titles += 1
        if sid == LAST_BLOCK and CREDIT_LINE not in new:
            new = new + "\r\n\r\n" + CREDIT_LINE
        if new != en:
            rows.append((sid, new))

    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("# بچ ۹۰۰: تیتراژ - عنوان‌های شغلی ترجمه شدند، اسامی خاص دست‌نخورده‌اند\n")
        fh.write("# اعتبار فارسی‌ساز (%s) در پایان بلوک %s اضافه شد\n" % (CREDIT_LINE, LAST_BLOCK))
        for sid, text in rows:
            fh.write(sid + "\t" + fslib.esc(text) + "\n")

    translated_titles = sum(1 for t in found if t in titles)
    print("بلوک‌های تیتراژ      : %d" % len(blocks))
    print("عنوان‌های یکتا       : %d" % len(found))
    print("عنوان‌های ترجمه‌شده  : %d" % translated_titles)
    print("بلوک‌های تغییر یافته : %d" % len(rows))
    print("-> %s" % out_path)
    if translated_titles < len(found):
        print("برای دیدن عنوان‌های باقی‌مانده: python3 tools/credits.py --missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
