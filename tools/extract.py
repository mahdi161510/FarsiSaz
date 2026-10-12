# -*- coding: utf-8 -*-
"""
extract.py - ساخت «فهرست مادر» رشته‌ها و فهرست کارِ اولویت‌دار

برای هر فایل منبع یک شناسه‌ی پایدار به هر رشته‌ی یکتا می‌دهد:
    رشته‌های فایل common -> C1, C2, ...   (به ترتیب اولین ظهور در فایل)
    رشته‌های فایل pc     -> P1, P2, ...

خروجی‌ها (پوشه‌ی work/):
    index_common.tsv   شناسه \t متن انگلیسی خام \t دسته \t تعداد تکرار
    index_pc.tsv       همان، برای فایل pc
    todo.tsv           شناسه \t دسته \t تعداد \t متن انگلیسی (یک‌خطی) - مرتب‌شده بر اساس اولویت
    stats.txt          خلاصه‌ی آماری

دسته‌ها:
    ui      منو، HUD، اهداف، آموزش، راهنمای دکمه‌ها
    bark    فریادهای کوتاه و پرتکرار نبرد/خیابان
    story   دیالوگ‌ها و متن‌های داستانی
    cue     آواهای داخل کروشه مثل [grunt]
    legal   متن‌های حقوقی/تیتراژ که ترجمه نمی‌شوند

استفاده:
    python3 tools/extract.py
    python3 tools/extract.py --show C1 C2 C3        # نمایش چند رشته
    python3 tools/extract.py --range P1-P90         # نمایش یک بازه
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fslib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
BATCH_DIR = os.path.join(ROOT, "translations", "batches")

SOURCES = [
    ("common", "C", os.path.join(ROOT, "stringtable_en_common_group.xml")),
    ("pc", "P", os.path.join(ROOT, "stringtable_en_pc_group.xml")),
]

# ---------------------------------------------------------------------------
# دسته‌بندی
# ---------------------------------------------------------------------------

CONTROL_TOKEN_RE = re.compile(r"#E_[A-Z0-9_]+#")
FORMAT_TOKEN_RE = re.compile(r"%[-\d]*[sd]|\{\d+\}|\{\}|\[RET\]|&lt;/?bold&gt;")
DIALECT_RE = re.compile(
    r"ain't|gonna|gotta|outta|somethin'|nothin'|doin'|gettin'|'em|fuckin'|goddamn|"
    r"\bya\b|\b'cause\b|nigger|coon\b|\bboy\b|\bmister\b", re.I)
SENTENCE_RE = re.compile(r"\b(I|I'm|you|your|he|she|we|they|it's|that's|there's|"
                         r"don't|can't|won't|isn't|aren't|let's|come on|look|listen|"
                         r"know|think|want|need|got|tell|said|ask|go|get)\b", re.I)

# واژگان رابط کاربری؛ فقط برای رشته‌های «برچسب‌مانند» به کار می‌رود
UI_LEXICON = re.compile(
    r"^(options?|settings?|menu|map|inventory|weapons?|vehicles?|radio|"
    r"station|save|load(ing)?|difficulty|volume|audio|video|graphics|"
    r"controls?|brightness|contrast|gamma|sensitivity|subtitles?|language|"
    r"quit|exit|resume|restart|continue|new game|pause|paused|profile|"
    r"missions?|objectives?|chapters?|upgrades?|rackets?|intel|kickback|"
    r"money|cash|health|ammo|reload|aim assist|cover|sprint|collect|"
    r"purchase|buy|sell|select|cancel|confirm|back|next|previous|yes|no|ok|"
    r"close|stats?|statistics|records?|challenges?|achievements?|trophies?|"
    r"dlc|season pass|bonus|content|controller|keyboard|mouse|gamepad|"
    r"vibration|toggle|press|hold|click|assign|unbind|default|reset|apply|"
    r"camera|hud|notifications?|tutorial|hints?|tips?|help|favorites?|"
    r"wiretap|wiretapped|safehouse|donation|priest|funeral|photographs?|"
    r"magazines?|playboy|comics?|posters?|albums?|tracks?|songs?)", re.I)


def looks_like_credits(text: str) -> bool:
    """تیتراژ: فهرست بلند اسامی - ترجمه نمی‌شود."""
    lines = [ln.strip() for ln in re.split(r"\r?\n", text) if ln.strip()]
    if len(lines) < 6:
        return False
    name_like = 0
    for ln in lines:
        if re.fullmatch(r"[A-Za-z\u00c0-\u017f'’\.\-,&/ ]{2,60}", ln) \
                and not SENTENCE_RE.search(ln):
            name_like += 1
    return name_like / len(lines) > 0.85


CUE_RE = re.compile(r"^\s*\[[^\]\r\n]{1,60}\]\s*[!.]?\s*$")
LEGAL_RE = re.compile(r"©|®|™|All Rights Reserved|trademark", re.I)


def classify(text: str, count: int) -> str:
    plain = text.strip()
    if not plain:
        return "story"
    if looks_like_credits(plain) or (LEGAL_RE.search(plain) and len(plain) > 300):
        return "legal"
    if CUE_RE.match(plain):
        return "cue"
    if CONTROL_TOKEN_RE.search(plain) or FORMAT_TOKEN_RE.search(plain):
        return "ui"
    if "&lt;bold&gt;" in plain:
        return "legal" if looks_like_credits(plain) else "ui"

    # برچسب‌مانند: کوتاه، بدون نقطه‌ی پایان جمله، بدون لهجه و ضمیر
    label_like = (len(plain) <= 70
                  and not re.search(r"[!?]$", plain)
                  and not DIALECT_RE.search(plain)
                  and not SENTENCE_RE.search(plain))
    if label_like and (re.fullmatch(r"[A-Z0-9 !\.\-,/&%'’\(\)\$\+:;\*\"“”]+", plain)
                       or UI_LEXICON.match(plain)):
        return "ui"
    if len(plain) <= 45 and re.search(r"[!?]$|^(Hey|Whoa|Damn|Shit|Oh|Ah|No|Yes)\b", plain):
        return "bark"
    if count >= 8 and len(plain) <= 90:
        return "bark"
    return "story"


# ---------------------------------------------------------------------------
# ابزارها
# ---------------------------------------------------------------------------

def unique_bodies(raw: str):
    order, counts = [], {}
    for _sid, body, _m in fslib.iter_items(raw):
        if body not in counts:
            counts[body] = 0
            order.append(body)
        counts[body] += 1
    return order, counts


def write_tsv(path: str, rows) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            cells = [c if isinstance(c, str) else str(c) for c in row]
            fh.write("\t".join(fslib.esc(c) for c in cells) + "\n")


def one_line(text: str, limit: int = 400) -> str:
    """برای نمایش: شکست خط‌ها با ⏎ و نویسه‌های خاص با نماد خوانا."""
    t = text.replace("\r\n", "⏎").replace("\n", "⏎").replace("\t", "⇥")
    t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return t if len(t) <= limit else t[:limit] + "…"


def build_indexes():
    """فهرست مادر را می‌سازد و (index, todo_rows) را برمی‌گرداند."""
    index = {}          # id -> (en_raw, cat, count, file_key)
    todo = []
    cat_counter = {}
    for key, prefix, path in SOURCES:
        if not os.path.exists(path):
            print("! فایل پیدا نشد: %s" % path)
            continue
        raw = fslib.read_source(path)
        order, counts = unique_bodies(raw)
        rows = []
        for i, body in enumerate(order, 1):
            sid = "%s%d" % (prefix, i)
            cat = classify(body, counts[body])
            index[sid] = (body, cat, counts[body], key)
            rows.append((sid, body, cat, counts[body]))
            cat_counter[cat] = cat_counter.get(cat, 0) + counts[body]
            todo.append((sid, cat, counts[body], one_line(body)))
        write_tsv(os.path.join(WORK, "index_%s.tsv" % key), rows)
        print("== %-7s %6d آیتم / %6d رشته‌ی یکتا -> work/index_%s.tsv"
              % (key, sum(counts.values()), len(order), key))
    return index, todo, cat_counter


PRIORITY = {"ui": 0, "bark": 1, "story": 2, "cue": 3, "legal": 4}


def parse_range(spec: str):
    """بازه‌هایی مثل C1-C200 یا P1-P90 یا C12 را به فهرست شناسه تبدیل می‌کند."""
    m = re.fullmatch(r"([CP])(\d+)(?:-([CP]?)(\d+))?", spec.strip())
    if not m:
        raise SystemExit("بازه‌ی نامعتبر: %s" % spec)
    p1, a, p2, b = m.groups()
    a = int(a)
    b = int(b) if b else a
    p2 = p2 or p1
    if p2 != p1:
        raise SystemExit("بازه باید هم‌پیشوند باشد")
    return ["%s%d" % (p1, i) for i in range(a, b + 1)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", nargs="*", help="نمایش رشته‌های داده‌شده")
    ap.add_argument("--range", help="نمایش یک بازه مثل C1-C100")
    args = ap.parse_args()

    index, todo, cat_counter = build_indexes()

    if args.range or args.show:
        ids = []
        if args.range:
            ids += parse_range(args.range)
        if args.show:
            for spec in args.show:
                ids += parse_range(spec) if "-" in spec or re.fullmatch(r"[CP]\d+", spec) else []
        for sid in ids:
            if sid in index:
                en, cat, cnt, key = index[sid]
                print("%s\t[%s x%d]\t%s" % (sid, cat, cnt, one_line(en)))
            else:
                print("%s\t<ناموجود>" % sid)
        return 0

    done = fslib.load_tm_ids(BATCH_DIR, index) if hasattr(fslib, "load_tm_ids") else set()

    # فهرست کار: اول دسته‌های مهم‌تر، بعد پرتکرارترها
    todo.sort(key=lambda r: (PRIORITY.get(r[1], 9), -r[2], r[0]))
    write_tsv(os.path.join(WORK, "todo.tsv"),
              [r for r in todo if r[0] not in done])

    with open(os.path.join(WORK, "stats.txt"), "w", encoding="utf-8") as fh:
        fh.write("دسته\tتعداد یکتا\tتعداد ظهور\n")
        per_cat_unique = {}
        for sid, (en, cat, cnt, key) in index.items():
            per_cat_unique[cat] = per_cat_unique.get(cat, 0) + 1
        for cat in sorted(cat_counter, key=lambda c: -cat_counter[c]):
            fh.write("%s\t%d\t%d\n" % (cat, per_cat_unique[cat], cat_counter[cat]))

    print("\n-- دسته‌بندی (یکتا / ظهور در بازی) --")
    per_cat_unique = {}
    for sid, (en, cat, cnt, key) in index.items():
        per_cat_unique[cat] = per_cat_unique.get(cat, 0) + 1
    for cat in sorted(cat_counter, key=lambda c: -cat_counter[c]):
        print("   %-7s %7d یکتا  %8d ظهور" % (cat, per_cat_unique[cat], cat_counter[cat]))
    print("\nمجموع رشته‌های یکتا: %d" % len(index))
    print("فهرست کار: work/todo.tsv  (%d ردیف)" % len([r for r in todo if r[0] not in done]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
