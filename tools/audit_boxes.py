# -*- coding: utf-8 -*-
"""audit_boxes.py — بازبینی «هیچ سطری از کادرِ نمایشش پهن‌تر نباشد».

چرا لازم است؟
    متن‌ها بصری (پیش‌شکل‌دهی‌شده) در xbin ذخیره می‌شوند. اگر سطری از کادرِ ویجت
    پهن‌تر بماند، خودِ ویجت آن را می‌شکند و چون متن بصری است، تکه‌ها از آخرِ جمله
    به اول می‌افتند (کاربر «از پایین به بالا» می‌خواند). پس باید مطمئن شویم هر خط
    در عرض کادرِ *خودش* شکسته شده است.

کادرها
    باریک = ۱۴em (پنل هدف، اعلان، ژورنال/پروفایل، سند، راهنمای نقشه) برای ردیف‌هایی
    که `wrap.py` آن‌ها را پنلی می‌داند (`panel_like`)، ردیف‌های `panel_rows.tsv`،
    راهنماهای قالبی و همه‌ی ردیف‌های دسته‌ی `ui`.
    پهن = ۳۰٫۱em (کادر زیرنویس) برای بقیه (دیالوگ/بارک).

دسته‌بندی موارد پهن‌تر از کادر
    * [RET]  : خودِ بازی این توکن را به شکست خط تبدیل می‌کند؛ «خط» ما یکی نیست.
    * key-token: خطی که پهنای واقعی‌اش را توکن `#E_…‎` تعیین می‌کند؛ بازی آن را با
      نام کوتاهِ کلید عوض می‌کند، ولی متریک ما طولِ نویسه‌های توکن را می‌شمارد
      (بیش‌برآورد ⇒ سمت امن).
    * markup/credits/latin: تیتراژ، نام‌های تازه‌وارد، رشته‌های توسعه‌دهنده.
    * UNEXPLAINED: هر چیز دیگری ⇒ باگ واقعی و باید رفع شود (کد خروج ۱).

استفاده
    python3 tools/audit_boxes.py [xbin] [--xml source/stringtable_en_common_group.xml]
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fslib          # noqa: E402
import wrap as W      # noqa: E402
import xbin as X      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# متن xbin پیش‌شکل‌دهی‌شده است؛ حروف فارسی در بلوک‌های presentation-form می‌نشینند
# (U+FB50–U+FEFF) نه فقط U+0600–U+06FF. اگر این بلوک‌ها را نشماریم، سطرهای
# فارسیِ پهن به‌اشتباه «لاتین» دسته‌بندی می‌شوند و باگ واقعی پنهان می‌ماند.
FA_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_ID_RE = re.compile(r'StringID="(\d+)">\s*<Content Type="String">(.*?)</Content>', re.S)


def load_en(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return {int(sid): body for sid, body in _ID_RE.findall(handle.read())}


def load_cats() -> dict:
    """متن انگلیسی → دسته‌ها (از indexهای work/)."""
    cats: dict = collections.defaultdict(set)
    for name in ("index_common.tsv", "index_pc.tsv"):
        path = os.path.join(ROOT, "work", name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) >= 3:
                    cats[fslib.unesc(parts[1])].add(parts[2])
    return cats


def main() -> int:
    ap = argparse.ArgumentParser(description="بازبینی پهنای خطوط نسبت به کادرها")
    ap.add_argument("xbin", nargs="?", default=os.path.join(ROOT, "stringtable_en_common_group.xbin"))
    ap.add_argument("--xml", default=os.path.join(ROOT, "source", "stringtable_en_common_group.xml"))
    ap.add_argument("--gfx", default=os.path.join(ROOT, "fonts_en_pc.gfx"))
    ap.add_argument("--narrow-em", type=float, default=W.PANEL_SAFE_LIMIT_EM)
    ap.add_argument("--wide-em", type=float, default=W.LIMIT_EM)
    ap.add_argument("--all-narrow", action="store_true",
                    help="همه‌ی سطرها را با کادر باریک بسنج (پیش‌فرض: طبق PANEL_TABLES)")
    args = ap.parse_args()

    metrics = W.load_metrics(args.gfx)
    if metrics is None:
        print("! متریک فونت خوانده نشد:", args.gfx)
        return 2
    em = W.EM
    # جدول‌های بیرونِ PANEL_TABLES (مثل جدول تنظیمات `_pc_group`) نوار توضیحِ پهن
    # دارند؛ پس همه‌ی سطرهایشان در کادر پهن سنجیده می‌شوند.
    narrow_table = args.all_narrow or os.path.basename(args.xbin) in X.PANEL_TABLES
    en_by_sid = load_en(args.xml)
    cats = load_cats()
    panels = W.load_panel_rows(os.path.join(ROOT, "translations", "panel_rows.tsv"))
    items = X.unpack(args.xbin)["items"]

    narrow = int(round(args.narrow_em * em))
    wide = int(round(args.wide_em * em))
    stats = collections.Counter()
    examples: dict = collections.defaultdict(list)

    for sid, text in items:
        body = en_by_sid.get(sid, "")
        cat = next((c for c in cats.get(body, ()) if c in W.SUBTITLE_CATS), None)
        is_narrow = narrow_table and (sid in W.PANEL_ROWS or cat == W.UI_SAFE_CAT
                                      or W.is_template_panel(body) or W.panel_like(body))
        limit = narrow if is_narrow else wide
        box = "narrow" if is_narrow else "wide"
        rich = "<" in text or "&" in text          # تیتراژ/کردیت: متن مارکاپ‌دار
        stats["rows"] += 1
        for line in text.split("\r\n"):
            stats["lines"] += 1
            width = metrics.width(line)
            if width <= limit:
                continue
            if "[RET]" in line:
                kind = "RET"                       # خودِ بازی این را می‌شکند
            elif rich or "<" in line:
                kind = "credits/markup"            # تیتراژ، در صفحه‌ی پهن و مرکزچین
            elif "#E_" in line:
                kind = "key-token"                 # بازی نامِ کوتاهِ کلید را می‌گذارد
            elif "_" in line and " " not in line:
                kind = "dev/no-space"              # رشته‌ی آزمون/توسعه‌ی بی‌فاصله
            elif not FA_RE.search(line):
                kind = "latin"                     # نام خاص/نشانی، شکستنی نیست
            else:
                kind = "UNEXPLAINED"
            stats["%s/%s" % (box, kind)] += 1
            if len(examples["%s/%s" % (box, kind)]) < 8:
                examples["%s/%s" % (box, kind)].append((sid, width / em, line))

    print("== %s" % os.path.relpath(args.xbin, ROOT))
    print("   %d ردیف، %d سطر | کادر باریک %.1fem، کادر پهن %.1fem"
          % (stats["rows"], stats["lines"], args.narrow_em, args.wide_em))
    over_narrow = sum(v for k, v in stats.items() if k.startswith("narrow/"))
    print("   سطرهای پهن‌تر از کادر: باریک %d، پهن %d"
          % (over_narrow, sum(v for k, v in stats.items() if k.startswith("wide/"))))
    for key in sorted(k for k in stats if "/" in k):
        print("     %-26s %5d" % (key, stats[key]))
    for key in sorted(examples):
        if key.endswith("UNEXPLAINED"):
            print("   ! نمونه‌های توضیح‌نشده (%s):" % key)
            for sid, width, line in examples[key]:
                print("     %d  %.1fem  %s" % (sid, width, line[:90]))
    unexplained = stats["narrow/UNEXPLAINED"] + stats["wide/UNEXPLAINED"]
    print("   %s" % ("✔ هیچ سطر توضیح‌نشده‌ای نیست." if not unexplained
                     else "✘ %d سطر توضیح‌نشده؛ باید رفع شود." % unexplained))
    return 1 if unexplained else 0


if __name__ == "__main__":
    raise SystemExit(main())
