# -*- coding: utf-8 -*-
"""audit_boxes.py — بازبینی «هیچ سطری از کادرِ نمایشش پهن‌تر نباشد» + ظرفیت سطر پنل.

چرا لازم است؟
    متن‌ها بصری (پیش‌شکل‌دهی‌شده) در xbin ذخیره می‌شوند. اگر سطری از کادرِ ویجت
    پهن‌تر بماند، خودِ ویجت آن را می‌شکند و چون متن بصری است، تکه‌ها از آخرِ جمله
    به اول می‌افتند (کاربر «از پایین به بالا» می‌خواند). پس باید مطمئن شویم هر خط
    در عرض کادرِ *خودش* شکسته شده است.

    عرضِ هر ردیف با همان تابعی حساب می‌شود که هنگام ساخت استفاده می‌شود
    (`wrap.panel_width_for`)، پس سنجش و ساخت هیچ‌وقت از هم جدا نمی‌افتند.

دسته‌بندی موارد پهن‌تر از کادر
    * [RET]  : خودِ بازی این توکن را به شکست خط تبدیل می‌کند؛ «خط» ما یکی نیست.
    * key-token: خطی که پهنای واقعی‌اش را توکن `#E_…‎` تعیین می‌کند؛ بازی آن را با
      نام کوتاهِ کلید عوض می‌کند، ولی متریک ما طولِ نویسه‌های توکن را می‌شمارد
      (بیش‌برآورد ⇒ سمت امن).
    * credits/markup: تیتراژ و کردیت، در صفحه‌ی پهن و مرکزچین.
    * dev/no-space: رشته‌های آزمون/توسعه‌ی بی‌فاصله.
    * latin: نام خاص، نشانی و عنوان آهنگ؛ شکستنی نیست.
    * UNEXPLAINED: هر چیز دیگری ⇒ باگ واقعی (کد خروج ۱).

بخش دوم گزارش، شمارشِ سطرهای متن‌های پنلی است: پنجره‌ی پنل ارتفاع ثابت دارد و
بیشتر از ``PANEL_LINE_BUDGET`` سطر را می‌بُرد. این عدد اطلاعی است، چون متن‌های
بلندِ ژورنال/پرونده/تیتراژ در پنجره‌های اسکرول‌دار نمایش داده می‌شوند.

استفاده
    python3 tools/audit_boxes.py
    python3 tools/audit_boxes.py stringtable_en_pc_group.xbin --xml source/stringtable_en_pc_group.xml
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


def load_xml(path: str) -> dict:
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
    ap.add_argument("--xml", default=None, help="جدول انگلیسی منبع (پیش‌فرض: هم‌نامِ xbin در source/)")
    ap.add_argument("--fa-xml", default=None, help="جدول فارسی ریشه (پیش‌فرض: هم‌نامِ xbin در ریشه)")
    ap.add_argument("--gfx", default=os.path.join(ROOT, "fonts_en_pc.gfx"))
    ap.add_argument("--wide-em", type=float, default=W.LIMIT_EM)
    args = ap.parse_args()

    name = os.path.basename(args.xbin)
    tables = ("common", "pc")
    table = next((t for t in tables if t in name), "common")
    args.xml = args.xml or os.path.join(ROOT, "source", "stringtable_en_%s_group.xml" % table)
    args.fa_xml = args.fa_xml or os.path.join(ROOT, "stringtable_en_%s_group.xml" % table)

    metrics = W.load_metrics(args.gfx)
    if metrics is None:
        print("! متریک فونت خوانده نشد:", args.gfx)
        return 2
    em = W.EM
    # جدول‌های بیرونِ PANEL_TABLES (مثل جدول تنظیمات `_pc_group`) نوار توضیحِ پهن
    # دارند؛ پس همه‌ی سطرهایشان در کادر پهن سنجیده می‌شوند.
    panel_em = W.PANEL_SAFE_LIMIT_EM if name in X.PANEL_TABLES else None
    en_by_sid = load_xml(args.xml)
    fa_by_sid = load_xml(args.fa_xml)
    cats = load_cats()
    W.load_panel_rows(os.path.join(ROOT, "translations", "panel_rows.tsv"))
    narrow_count = W.load_narrow_rows(os.path.join(ROOT, W.NARROW_ROWS_FILE))
    if narrow_count:
        print("   ردیف‌های با کادرِ باریک‌تر: %d (از %s)" % (narrow_count, W.NARROW_ROWS_FILE))
    items = X.unpack(args.xbin)["items"]

    wide = int(round(args.wide_em * em))
    stats = collections.Counter()
    examples: dict = collections.defaultdict(list)
    budget_rows = []

    for sid, text in items:
        body = en_by_sid.get(sid, "")
        fa = fa_by_sid.get(sid, "")
        cat = next((c for c in cats.get(body, ()) if c in W.SUBTITLE_CATS), None)
        limit, is_panel = W.panel_width_for(fa, body, cat, metrics, wide, panel_em, sid)
        lines = text.split("\r\n")
        rich = "<" in text or "&" in text          # تیتراژ/کردیت: متن مارکاپ‌دار
        stats["rows"] += 1
        stats["lines"] += len(lines)
        # ردیف‌های کادرِ باریک: بودجه در واحدِ «شکل‌دهی‌شده» است، پس جداگانه سنجیده
        # می‌شوند (عرض خطِ ذخیره‌شده = همان چیزی که بازی می‌سنجد).
        # ردیف‌های «هدف/مأموریت» HUD: کادر باریک‌تر از پنل است و باید در واحدِ
        # شکل‌دهی‌شده سنجیده شوند (همان‌طور که خود بازی می‌سنجد).
        cat_row = next((c for c in cats.get(body, ()) if c in W.SUBTITLE_CATS), None)
        if W.is_objective(body, cat_row) and "#" not in text and "%" not in text:
            widest = max((W.shaped_width(line, metrics) for line in lines), default=0)
            budget = int(round(W.OBJECTIVE_HUD_LIMIT_EM * em))
            stats["objective_rows"] += 1
            ratio = widest / budget if budget else 0.0
            if ratio > 1.0:
                stats["objective_over"] += 1
                examples["objective_over"].append((sid, widest / em, budget / em, lines[0]))
            stats["objective_worst"] = max(stats["objective_worst"], ratio)
            continue
        budget_px = W.narrow_budget_px(sid)
        if budget_px is not None:
            widest = max((metrics.width(line) for line in lines), default=0)
            stats["narrow_rows"] += 1
            ratio = widest / budget_px if budget_px else 0.0
            if ratio > 1.0:
                stats["narrow_over"] += 1
                examples["narrow_over"].append((sid, widest / em, budget_px / em, lines[0]))
            stats["narrow_worst"] = max(stats["narrow_worst"], ratio)
            continue
        if is_panel and len(lines) > W.PANEL_LINE_BUDGET:
            budget_rows.append((sid, len(lines), limit / em))
        box = "panel" if is_panel else "wide"
        for line in lines:
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
                examples["%s/%s" % (box, kind)].append((sid, width / em, limit / em, line))

    print("== %s" % os.path.relpath(args.xbin, ROOT))
    print("   %d ردیف، %d سطر | کادر پهن %.1fem" % (stats["rows"], stats["lines"], args.wide_em))
    over = collections.Counter({k: v for k, v in stats.items() if "/" in k})
    print("   سطرهای پهن‌تر از کادرِ خودشان: %d" % sum(over.values()))
    for key in sorted(over):
        lines = ["     %-26s %5d" % (key, over[key])]
        for sid, width, limit, line in examples[key]:
            if key.endswith("UNEXPLAINED"):
                lines.append("\n       %d  %.1fem > %.1fem  %s" % (sid, width, limit, line[:80]))
        print("".join(lines))
    if stats["objective_rows"]:
        print("   ردیف‌های هدف/مأموریت HUD: %d — پهن‌ترین سطر %.0f%% بودجهٔ %.1fem  %s"
              % (stats["objective_rows"], 100.0 * stats["objective_worst"],
                 W.OBJECTIVE_HUD_LIMIT_EM,
                 "✔" if not stats["objective_over"] else "✘ %d سرریز" % stats["objective_over"]))
        for sid, width, budget, line in examples.get("objective_over", [])[:5]:
            print("       %d  %.2fem > %.2fem  %s" % (sid, width, budget, line[:70]))
    if stats["narrow_rows"]:
        print("   ردیف‌های کادرِ باریک: %d — پهن‌ترین سطر %.0f%% بودجهٔ خودش  %s"
              % (stats["narrow_rows"], 100.0 * stats["narrow_worst"],
                 "✔" if not stats["narrow_over"] else "✘ %d سرریز" % stats["narrow_over"]))
        for sid, width, budget, line in examples.get("narrow_over", [])[:5]:
            print("       %d  %.2fem > %.2fem  %s" % (sid, width, budget, line[:70]))
    if budget_rows:
        print("   متن‌های پنلی با بیش از %d سطر (پنجره‌ی ثابت، بیشترشان اسکرول‌دار): %d"
              % (W.PANEL_LINE_BUDGET, len(budget_rows)))
        for sid, n, lim in sorted(budget_rows, key=lambda r: -r[1])[:5]:
            print("     %d: %d سطر (حد %.2fem)" % (sid, n, lim))
    unexplained = sum(v for k, v in over.items() if k.endswith("UNEXPLAINED"))
    unexplained += stats["narrow_over"] + stats["objective_over"]
    print("   %s" % ("✔ هیچ سطر توضیح‌نشده‌ای نیست." if not unexplained
                     else "✘ %d سطر توضیح‌نشده؛ باید رفع شود." % unexplained))
    return 1 if unexplained else 0


if __name__ == "__main__":
    raise SystemExit(main())
