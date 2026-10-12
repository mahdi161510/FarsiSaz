# -*- coding: utf-8 -*-
"""
fslib - کتابخانه‌ی مشترک خطِ لوله‌ی فارسی‌سازی Mafia III
=====================================================

این ماژول مسئول سه کار است:

1. خواندن/نوشتن فایل‌های stringtable بدون دست‌کاری کوچک‌ترین جزئیات ساختاری
   (BOM، پایان خطوط CRLF، فاصله‌ها، ترتیب StringIDها).
2. رمزگذاری/رمزگشایی متن‌ها برای ذخیره در فایل‌های TSV حافظه‌ی ترجمه.
3. شناسایی «توکن‌های فنی» که باید عیناً در ترجمه حفظ شوند
   (مثلاً #E_CTRL_MAP# یا %s یا &lt;bold&gt; یا [RET]).

هیچ‌کدام از توابع این فایل متن را تغییر نمی‌دهند؛ فقط جابه‌جا و بررسی می‌کنند.
"""

from __future__ import annotations

import os
import re
import sys

# ---------------------------------------------------------------------------
# ثابت‌ها
# ---------------------------------------------------------------------------

BOM_BYTES = b"\xef\xbb\xbf"

# هر آیتم جدول رشته‌ها: <LocalisableString StringID="..."> <Content Type="String">...</Content>
ITEM_RE = re.compile(
    r'(?P<head><LocalisableString StringID="(?P<sid>\d+)">\r?\n'
    r'[ \t]*<Content Type="String">)'
    r'(?P<body>.*?)'
    r'(?P<tail></Content>)',
    re.S,
)

# توکن‌هایی که باید دقیقاً (با همان تعداد و همان ترتیب) در ترجمه باقی بمانند.
TOKEN_RE = re.compile(
    r"&lt;/?[A-Za-z_][A-Za-z0-9_]*(?:\s[^&]*?)?&gt;"  # مارکاپ escaped مثل &lt;bold&gt;
    r"|</?[A-Za-z_][^<>\r\n]*>"                        # مارکاپ خام مثل <color=...>
    r"|#[^#\r\n]{1,80}#"                               # راهنمای دکمه‌ها مثل #E_CTRL_MAP#
    r"|\[(?:RET|ACTION)\]"                             # جداکننده‌های فنی (ترجمه نمی‌شوند)
    r"|%%|%[-+0#]*\d*(?:\.\d+)?[a-zA-Z]"               # قالب‌های printf مثل %s یا %S
    r"|\{\}|\{\d+\}|\{[A-Za-z_][A-Za-z0-9_]*\}"        # قالب‌های آکولادی
    r"|\$\$|\$",                                       # علامت پول
    re.S,
)

# نویسه‌های کنترلی که هیچ‌وقت نباید در خروجی ظاهر شوند (جز \r و \n و \t)
BAD_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ---------------------------------------------------------------------------
# خواندن و نوشتن منبع
# ---------------------------------------------------------------------------

def read_source(path: str) -> str:
    """فایل XML را دقیقاً همان‌طور که هست می‌خواند (BOM حذف، CRLF حفظ می‌شود)."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(BOM_BYTES):
        data = data[len(BOM_BYTES):]
    return data.decode("utf-8")


def write_source(path: str, text: str) -> None:
    """متن را با BOM و encoding=utf-8 می‌نویسد (بدون تغییر پایان خطوط)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(BOM_BYTES)
        fh.write(text.encode("utf-8"))


def iter_items(raw: str):
    """روی همه‌ی آیتم‌ها پیمایش می‌کند: (string_id, body, match)."""
    for m in ITEM_RE.finditer(raw):
        yield m.group("sid"), m.group("body"), m


def item_count(raw: str) -> int:
    return sum(1 for _ in iter_items(raw))


# ---------------------------------------------------------------------------
# رمزگذاری TSV
# ---------------------------------------------------------------------------

_ESCAPES = {
    "\\": "\\\\",
    "\t": "\\t",
    "\r": "\\r",
    "\n": "\\n",
}


def esc(text: str) -> str:
    """متن را برای ذخیره در یک سطر TSV فرار (escape) می‌کند."""
    out = []
    for ch in text:
        out.append(_ESCAPES.get(ch, ch))
    return "".join(out)


def unesc(text: str) -> str:
    """معکوس esc()."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "r":
                out.append("\r")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "\\":
                out.append("\\")
            else:
                # دنباله‌ی ناشناخته: عیناً نگه می‌داریم تا داده‌ای از دست نرود
                out.append(ch)
                out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# حافظه‌ی ترجمه (Translation Memory)
# ---------------------------------------------------------------------------

def load_index(paths):
    """فهرست مادر (خروجی extract.py) را می‌خواند -> dict[id] = en_raw"""
    index = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8", newline="") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                index[parts[0]] = unesc(parts[1])
    return index


def load_batch(path: str):
    """یک فایل بچ ترجمه را می‌خواند -> dict[id] = fa_raw

    فرمت هر سطر:  شناسه <TAB> متن فارسی (escape‌شده)
    سطرهای خالی و سطرهایی که با # شروع شوند نادیده گرفته می‌شوند.
    """
    table = {}
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                print("  ! %s سطر %d: ستون دوم ندارد، رد شد" % (path, lineno),
                      file=sys.stderr)
                continue
            sid, fa = parts[0].strip(), unesc(parts[1])
            if sid in table and table[sid] != fa:
                print("  ! %s سطر %d: شناسه‌ی تکراری %s (مقدار قبلی بازنویسی شد)"
                      % (path, lineno, sid), file=sys.stderr)
            table[sid] = fa
    return table


def load_tm(batch_dir: str, index: dict, verbose: bool = True):
    """همه‌ی بچ‌ها را می‌خواند و حافظه‌ی ترجمه‌ی EN->FA را می‌سازد.

    بازگشت: (tm, ids, problems)
      tm       : dict[en_raw] = fa_raw
      ids      : مجموعه‌ی شناسه‌های ترجمه‌شده
      problems : فهرست مشکلات (شناسه‌ی ناشناخته و ...)
    بچ‌هایی که نامشان بعداً می‌آید اولویت دارند (برای اعمال اصلاحیه).
    """
    tm, ids, problems = {}, set(), []
    if not os.path.isdir(batch_dir):
        return tm, ids, problems
    files = sorted(f for f in os.listdir(batch_dir) if f.endswith(".tsv"))
    for name in files:
        part = load_batch(os.path.join(batch_dir, name))
        if verbose:
            print("  + %-40s %6d رشته" % (name, len(part)))
        for sid, fa in part.items():
            en = index.get(sid)
            if en is None:
                problems.append("شناسه‌ی ناشناخته در %s: %s" % (name, sid))
                continue
            ids.add(sid)
            tm[en] = fa
    return tm, ids, problems


def load_tm_ids(batch_dir: str, index: dict):
    """فقط مجموعه‌ی شناسه‌های ترجمه‌شده را برمی‌گرداند (سریع‌تر)."""
    ids = set()
    if not os.path.isdir(batch_dir):
        return ids
    for name in sorted(f for f in os.listdir(batch_dir) if f.endswith(".tsv")):
        ids.update(load_batch(os.path.join(batch_dir, name)).keys())
    return ids & set(index) if index else ids


# ---------------------------------------------------------------------------
# توکن‌های فنی
# ---------------------------------------------------------------------------

def tokens(text: str):
    """لیست توکن‌های فنی یک رشته (برای مقایسه‌ی انگلیسی و فارسی)."""
    return TOKEN_RE.findall(text)


def token_signature(text: str):
    return tuple(sorted(tokens(text)))


def token_report(en: str, fa: str):
    """اگر توکن‌های فنی ترجمه با متن اصلی یکی نباشد، فهرست اختلاف را برمی‌گرداند.

    یک استثنا: علامت پول ($) را می‌شود در فارسی به «دلار» برگرداند،
    چون چیدمان مبلغ در فارسی برعکس انگلیسی است ($100 -> ۱۰۰ دلار).
    """
    a, b = list(tokens(en)), list(tokens(fa))
    if sorted(a) == sorted(b):
        return []
    money_ok = ("دلار" in fa) or ("$" in fa)
    problems = []
    for tok in a:
        if tok in b:
            b.remove(tok)
        elif money_ok and tok in ("$", "$$"):
            continue
        else:
            problems.append("مفقود: " + tok)
    for tok in b:
        if money_ok and tok in ("$", "$$"):
            continue
        problems.append("اضافه: " + tok)
    return problems


def has_rtl(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" or "\ufb50" <= ch <= "\ufdff"
               or "\ufe70" <= ch <= "\ufeff" for ch in text)


# ---------------------------------------------------------------------------
# جای‌گذاری ترجمه در XML
# ---------------------------------------------------------------------------

def apply_tm(raw: str, tm: dict, stats: dict | None = None):
    """بدنه‌ی هر آیتم را در صورت وجود ترجمه جایگزین می‌کند.

    ساختار فایل (تگ‌ها، StringIDها، فاصله‌ها، CRLF) دست‌نخورده می‌ماند.
    """
    if stats is None:
        stats = {"total": 0, "translated": 0, "kept": 0}

    def repl(m: re.Match) -> str:
        body = m.group("body")
        stats["total"] += 1
        fa = tm.get(body)
        if fa is None:
            stats["kept"] += 1
            return m.group(0)
        stats["translated"] += 1
        return m.group("head") + fa + m.group("tail")

    return ITEM_RE.sub(repl, raw), stats
