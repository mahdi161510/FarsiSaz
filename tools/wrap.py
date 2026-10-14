# -*- coding: utf-8 -*-
"""wrap.py - شکستن خطوط فارسی پیش از بسته‌بندی xbin.

چرا لازم است؟
    موتور بازی برای زیرنویس‌ها یک ویجت چپ‌به‌راست است: متنی که به آن می‌دهیم
    را از ابتدای رشته (سمت چپ بصری) می‌خواند و به خطوط می‌شکند. چون ما متن
    فارسی را پیش‌شکل‌دهی و بازچینی کرده‌ایم، «ابتدای رشته» پایانِ منطقی جمله
    است؛ نتیجه اینکه خط اولِ نمایش دنبالهٔ جمله می‌شد و کاربر باید از پایین
    به بالا می‌خواند.

راه‌حل:
    خودمان خطوط را می‌شکنیم؛ پس ویجت دیگر کاری برای شکستن ندارد و هر سطر یک
    «تکهٔ خوانا» به ترتیب منطقی است. نتیجه:
      • خط اول = شروع جمله (در RTL: لبهٔ راست)، خط‌های بعد به ترتیب پایین.
      • نام گوینده («فرانک: ...») طبیعتاً در ابتدای سطر اول می‌ماند، یعنی
        همان‌جایی که چشم فارسی‌خوان شروع می‌کند.

همه‌ی محاسبات عرض با متریک واقعی فونت بازی (fonts_en_pc.gfx) انجام می‌شود.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EM = 20480                      # واحد استاندارد جدول‌های فونت GFx برای هر em
# عرض کادر زیرنویس: با دو نمونهٔ تصویری خود بازی کالیبره شده است.
# در هر دو نمونه (زیرنویس دوخطی Mafia III و Mafia DE) طول سطر اول و «واژهٔ
# بعدی» با متریک Arial محاسبه می‌شود و کادر در بازهٔ [۳۰٫۰، ۳۱٫۳) em می‌افتد؛
# کمی پایین‌تر می‌مانیم تا ویجت هرگز خودش دست به شکستن نزند.
LIMIT_EM = 30.1
DEFAULT_LIMIT = int(round(LIMIT_EM * EM))

SUBTITLE_CATS = ("story", "bark", "ui")

# ---------------------------------------------------------------------------
# برچسب نام گوینده
# ---------------------------------------------------------------------------
# موتور بازی خودش «نام گوینده» را قبل از متنِ زیرنویس می‌چسباند و ویجت آن را
# چپ‌به‌راست می‌کشد؛ چون متن ما پیش‌شکل‌دهی/بازچینی شده، آن نام ته سطر (سمت
# چپ) می‌افتد و آخر از همه خوانده می‌شود. برای بردنش به لبهٔ راست، به انتهای
# خودِ رشتهٔ نام فاصله اضافه می‌کنیم: هنگام بازچینی RTL این فاصله‌ها به ابتدای
# رشتهٔ ذخیره‌شده می‌روند، خط را پر می‌کنند و نام را به راست می‌رانند.
SPEAKER_LABELS = frozenset({
    "Lincoln", "MJ", "Burke", "Cassandra", "Donovan", "Olivia", "Giorgi", "Enzo",
    "Danny", "Vito", "Sammy", "Ellis", "Roxy", "Nicki", "Alma", "Marcano", "Ritchie",
    "Winkler", "Blanche", "Vargas", "Duplass", "Paez", "Connie", "Jackie", "Frank",
    "Alvarez", "Tony", "Merle", "Charlie", "Roy", "Maria", "Tommy", "Sonny", "Harold",
    "Artie",
})

# عرض کل «فاصله‌ها + نام + جداکنندهٔ موتور» روی خط نام (بر حسب em)
LABEL_TARGET_EM = 29.4
LABEL_SEPARATOR_EM = 1.0        # تخمین برای ": " که خودِ موتور می‌گذارد

_METRICS = None

# تگ‌های مارکاپی که نباید دست‌کاری شوند (bold، h1، h2 ...)
_MARKUP_RE = re.compile(r"<[A-Za-z/][^<>]{0,40}>|&#?\w+;")


class Metrics:
    """جدول عرض نویسه‌ها (واحد GFx) + عرض فاصله."""

    def __init__(self, advances: dict, space: int):
        self.advances = advances
        self.space = space

    def width(self, text: str) -> int:
        adv = self.advances
        sp = self.space
        total = 0
        for ch in text:
            w = adv.get(ord(ch))
            if w is None:
                if ch == "\u200c" or ch == "\u200d":
                    continue                       # نیم‌فاصله/اتصال بی‌عرض
                w = sp if ch.isspace() else sp + sp // 4
            total += w
        return total


def load_metrics(gfx_path: str):
    """متریک فونت بدنهٔ رابط (Arial = id 3) را از فایل gfx بازی می‌خواند."""
    global _METRICS
    if _METRICS is not None:
        return _METRICS
    if not gfx_path or not os.path.exists(gfx_path):
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gfx_font", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gfx_font.py"))
        gf = importlib.util.module_from_spec(spec)
        sys.modules["gfx_font"] = gf
        spec.loader.exec_module(gf)
    except Exception as exc:                                     # pragma: no cover
        print("  ! متریک فونت در دسترس نیست (%s)؛ شکستن خطوط انجام نمی‌شود." % exc)
        return None
    with open(gfx_path, "rb") as fh:
        data = fh.read()
    try:
        _code, tags = gf.parse_gfx(data)
    except Exception as exc:                                     # pragma: no cover
        print("  ! خواندن fonts_en_pc.gfx ناموفق بود (%s)." % exc)
        return None
    tables = {}
    for tag in tags:
        if getattr(tag, "code", None) != gf.TAG_DEFINE_FONT3:
            continue
        try:
            font = gf.parse_font3(tag.payload)
        except Exception:                                        # pragma: no cover
            continue
        tables[font.font_id] = font
    if not tables:
        print("  ! جدول فونت در gfx پیدا نشد؛ شکستن خطوط انجام نمی‌شود.")
        return None
    font = tables.get(3) or sorted(tables.items())[0][1]
    advances = {code: glyph.advance for code, glyph in font.glyphs.items()}
    space = advances.get(0x20) or 8000
    _METRICS = Metrics(advances, space)
    return _METRICS


def wrap_line(line: str, metrics: Metrics, limit: int):
    """یک سطر منطقی را به تکه‌های ≤ حد عرض می‌شکند (حریصانه، بر پایه‌ی واژه)."""
    if metrics.width(line) <= limit:
        return [line]
    words = line.split(" ")
    lines, current = [], ""
    for word in words:
        candidate = word if not current else current + " " + word
        if current and metrics.width(candidate) > limit:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def plan_lines(fa: str, metrics: Metrics, limit: int):
    """سطرهای منطقی نهایی را می‌سازد؛ شکست‌های دستی (\\r\\n) حفظ می‌شوند."""
    result = []
    for part in fa.split("\r\n"):
        if metrics.width(part) <= limit:
            result.append(part)
            continue
        result.extend(wrap_line(part, metrics, limit))
    return result


def pad_speaker_label(text: str, metrics: Metrics, limit: int):
    """نام گوینده را با فاصله‌های انتهایی به لبهٔ راست خط می‌راند.

    خروجی، مقدار منطقیِ تازه است؛ هنگام بسته‌بندی، reverse شدن RTL آن
    فاصله‌ها را به ابتدای رشته (سمت چپ کادر) می‌برد و نام به راست می‌رسد.
    """
    if metrics is None or not text:
        return None
    width = metrics.width(text)
    room = int(round((LABEL_TARGET_EM - LABEL_SEPARATOR_EM) * EM)) - width
    if room <= 0:
        return None
    spaces = int(room // metrics.space)
    if spaces < 1:
        return None
    return text + (" " * spaces)


def wrap_entry(en: str, fa: str, cat: str | None, metrics, limit: int):
    """خروجی نهایی: fa با شکست خط‌های درست، یا None اگر تغییری لازم نبود.

    فقط رشته‌های فارسیِ دسته‌های زیرنویس/رابط که خودِ بازی می‌شکند بازچینی
    می‌شوند؛ فهرست‌های مسیر، متن‌های تیتراژ و رشته‌های دارای مارکاپ دست‌نخورده
    می‌مانند.
    """
    if metrics is None or not fa:
        return None
    if cat is not None and cat not in SUBTITLE_CATS:
        return None
    if en and en.strip() in SPEAKER_LABELS:          # برچسب نام گوینده
        return pad_speaker_label(fa, metrics, limit)
    if not any(unicodedata.category(ch) == "Lo" and 0x0600 <= ord(ch) <= 0x06FF for ch in fa):
        return None                                   # فقط متن فارسی
    if _MARKUP_RE.search(fa):
        return None                                   # مارکاپ/تیتراژ دست‌نخورده
    if "[RET]" in fa:
        return None            # شکست خط‌های خودِ بازی (فهرست مسیرها) دست‌نخورده می‌ماند
    lines = plan_lines(fa, metrics, limit)
    joined = "\r\n".join(lines)
    if joined == fa:
        return None
    return joined


def _self_test():
    metrics = Metrics({}, 8000)
    wide = "ً" * 10
    # ترتیب منطقی تکه‌ها حفظ می‌شود و هیچ سطری از حد نمی‌گذرد
    plain = " ".join("واژه" + str(i) for i in range(20))
    lines = plan_lines(plain, metrics, metrics.space * 30)
    assert len(lines) > 1, lines
    assert lines[0].split()[0] == "واژه0", lines[0]
    assert lines[-1].split()[-1] == "واژه19", lines[-1]
    assert all(metrics.width(l) <= metrics.space * 30 for l in lines), lines
    # نام گوینده در ابتدای سطر اول می‌ماند
    named = "فرانک: " + " ".join("واژه" + wide for _ in range(12))
    lines = plan_lines(named, metrics, metrics.space * 40)
    assert lines[0].startswith("فرانک:"), lines[0]
    # شکست‌های دستی حفظ می‌شوند
    manual = "برچسب: مقدار\r\n" + " ".join("واژه" + wide for _ in range(12))
    lines = plan_lines(manual, metrics, metrics.space * 40)
    assert lines[0] == "برچسب: مقدار", lines[0]
    assert len(lines) > 2, lines
    # برچسب نام گوینده: فاصله‌ها به انتهای مقدار منطقی اضافه می‌شوند
    lab = pad_speaker_label("جورجو", metrics, metrics.space * 30)
    assert lab and lab.startswith("جورجو") and lab.strip() == "جورجو", lab
    assert len(lab) > len("جورجو") + 10, lab
    # idempotent
    out = "\r\n".join(plan_lines(plain, metrics, metrics.space * 30))
    assert "\r\n".join(plan_lines(out, metrics, metrics.space * 30)) == out
    print("✔ آزمون شکستن خطوط زیرنویس (ترتیب، نام گوینده، شکست دستی، idempotent) قبول شد")


if __name__ == "__main__":
    _self_test()
