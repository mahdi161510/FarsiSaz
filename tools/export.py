# -*- coding: utf-8 -*-
"""
export.py - خروجی گرفتن از حافظه‌ی ترجمه به شکل خوانا برای بازبینی انسانی

خروجی:
    release/translation_memory_en_fa.tsv    ستون‌ها: شناسه | دسته | انگلیسی | فارسی
    release/progress.md                     گزارش پیشرفت تفکیک‌شده بر اساس دسته

استفاده:
    python3 tools/export.py
"""

from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fslib  # noqa: E402
import extract  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
BATCH_DIR = os.path.join(ROOT, "translations", "batches")
OUT_DIR = os.path.join(ROOT, "release")

CATS = ["ui", "bark", "story", "cue", "legal"]
CAT_FA = {
    "ui": "رابط کاربری/منوها/آموزش",
    "bark": "فریادهای کوتاه نبرد و خیابان",
    "story": "دیالوگ و متن داستانی",
    "cue": "آواهای داخل کروشه",
    "legal": "حقوقی/تیتراژ (بدون ترجمه)",
}


def main() -> int:
    # فهرست مادر با جزئیات (شناسه -> متن/دسته/تکرار)
    index, todo, cat_counter = extract.build_indexes()
    en_index = fslib.load_index([os.path.join(WORK, "index_common.tsv"),
                                 os.path.join(WORK, "index_pc.tsv")])
    tm, ids, problems = fslib.load_tm(BATCH_DIR, en_index, verbose=False)

    os.makedirs(OUT_DIR, exist_ok=True)

    rows = []
    for sid, (en, cat, cnt, key) in sorted(index.items(),
                                           key=lambda kv: (kv[1][3], int(kv[0].lstrip("CP")))):
        rows.append((sid, cat, cnt, en, tm.get(en, "")))
    with open(os.path.join(OUT_DIR, "translation_memory_en_fa.tsv"), "w",
              encoding="utf-8-sig", newline="") as fh:
        fh.write("id\tcategory\tcount\ten\tfa\n")
        for sid, cat, cnt, en, fa in rows:
            fh.write("\t".join([sid, cat, str(cnt), fslib.esc(en), fslib.esc(fa)]) + "\n")

    # آمار پیشرفت
    per_cat = collections.defaultdict(lambda: [0, 0, 0, 0])  # uniq, done, occ, occ_done
    for sid, (en, cat, cnt, key) in index.items():
        st = per_cat[cat]
        st[0] += 1
        st[2] += cnt
        if en in tm:
            st[1] += 1
            st[3] += cnt

    lines = ["# پیشرفت فارسی‌سازی Mafia III", ""]
    lines.append("| دسته | توضیح | رشته‌های یکتا | ترجمه‌شده | درصد یکتا | ظهور در بازی | پوشش ظهور |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    tot = [0, 0, 0, 0]
    for cat in CATS:
        st = per_cat.get(cat)
        if not st:
            continue
        for i in range(4):
            tot[i] += st[i]
        lines.append("| `%s` | %s | %d | %d | %.1f%% | %d | %.1f%% |" % (
            cat, CAT_FA[cat], st[0], st[1], 100.0 * st[1] / max(st[0], 1),
            st[2], 100.0 * st[3] / max(st[2], 1)))
    lines.append("| **جمع** | | **%d** | **%d** | **%.1f%%** | **%d** | **%.1f%%** |" % (
        tot[0], tot[1], 100.0 * tot[1] / max(tot[0], 1),
        tot[2], 100.0 * tot[3] / max(tot[2], 1)))
    lines.append("")
    if problems:
        lines.append("## مشکلات حافظه‌ی ترجمه")
        lines += ["- " + p for p in problems]
    with open(os.path.join(ROOT, "PROGRESS.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    print("\n-> release/translation_memory_en_fa.tsv")
    print("-> PROGRESS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
