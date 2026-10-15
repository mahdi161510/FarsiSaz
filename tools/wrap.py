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
      • نام گوینده: موتور بازی خودش «نام: » را پیش از متن می‌چسباند، پس نام
        همیشه ابتدای رشته (= لبهٔ چپ سطر) می‌افتاد. به خودِ رشتهٔ نام یک شکست
        خط اضافه می‌کنیم تا نام تنها روی سطر اول بنشیند؛ چون سطرهای زیرنویس
        راست‌چین‌اند، نام در لبهٔ راست بالای دیالوگ ظاهر می‌شود.

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
# نام گوینده
# ---------------------------------------------------------------------------
# موتور بازی رشتهٔ «نام: » را پیش از متنِ زیرنویس می‌گذارد و ویجت، سطرها را
# راست‌چین می‌چیند؛ پس هرچه در ابتدای رشته بیاید، در نمایش انتهای سطر (سمت چپ)
# می‌افتد. برای بردنِ نام به سمت راست، به خودِ رشتهٔ نام یک شکست خط اضافه
# می‌کنیم: نام تنها روی سطر اول می‌ماند و چون سطرها راست‌چین‌اند، در لبهٔ راست
# بالای دیالوگ می‌نشیند و متن از سطر بعد شروع می‌شود.
#
# نکته‌ها:
#   * صورت فرارِ \r\n همان شکستی است که خودِ بازی در بقیهٔ رشته‌ها می‌شناسد.
#   * نیم‌فاصلهٔ \u200c بعد از شکست می‌آید تا اگر موتور فاصله‌های انتهایی را
#     trim کند، شکست حذف نشود؛ این نویسه بی‌عرض و بی‌رنگ است و در فونت بازی هم
#     وجود دارد (همه‌جای متن‌های فارسی استفاده می‌شود).
SPEAKER_LABELS = frozenset({
    "Lincoln", "MJ", "Burke", "Cassandra", "Donovan", "Olivia", "Giorgi", "Enzo",
    "Danny", "Vito", "Sammy", "Ellis", "Roxy", "Nicki", "Alma", "Marcano", "Ritchie",
    "Winkler", "Blanche", "Vargas", "Duplass", "Paez", "Connie", "Jackie", "Frank",
    "Alvarez", "Tony", "Merle", "Charlie", "Roy", "Maria", "Tommy", "Sonny", "Harold",
    "Artie",
})

LABEL_BREAK = "\r\n"
LABEL_GUARD = "\u200c"
LABEL_SUFFIX = LABEL_BREAK + LABEL_GUARD

# جداکنندهٔ «: » که خودِ موتور پیش از متن می‌گذارد؛ اولین سطر دیالوگ باید این
# مقدار کمتر از حد بسته‌بندی باشد تا موتور خودش دوباره نشکند.

# ---------------------------------------------------------------------------
# پنل «هدف» گوشهٔ بالا-چپ
# ---------------------------------------------------------------------------
# متن هدف در یک کادر باریک نشان داده می‌شود، نه در کادر پهنِ زیرنویس؛ پس هدف‌های
# بلندتر از عرض آن کادر را خودِ ویجت می‌شکند و چون متن ما پیش‌شکل‌دهی‌شده است،
# ترتیب سطرها برعکس می‌شود (پایین به بالا). مثل زیرنویس‌ها خودمان هدف را در حد
# عرض همان کادر می‌شکنیم.
#
# عرض کادر هدف از اسکرین‌شات خود بازی تخمین زده شده: کادر ≈۲۴۰ پیکسل و هر em
# متریک زیرنویس ≈۱۶٫۶ پیکسل ⇒ ≈۱۴٫۵em؛ کمی کمتر می‌گیریم تا هیچ‌وقت جا نماند.
# جداکنندهٔ «: » که خودِ موتور پیش از متن می‌گذارد؛ اولین سطر دیالوگ باید این
# مقدار کمتر از حد بسته‌بندی باشد تا موتور خودش دوباره نشکند.
SEPARATOR_EM = 0.6

HUD_LIMIT_EM = 14.0

# عرض پنل‌های باریکِ ژورنال/پروفایل/اعلان‌ها (اندازه‌گیری‌شده از اسکرین‌شات‌ها ≈۱۴em).
# ردیف‌های فهرست‌شده در translations/panel_rows.tsv در همین عرض شکسته می‌شوند.
PANEL_LIMIT_EM = 14.0

# ---------------------------------------------------------------------------
# عرض ایمنِ پنل — پنل یا زیرنویس؟
# ---------------------------------------------------------------------------
# ویجت هر سطری را که از کادرش پهن‌تر باشد خودش می‌شکند و چون متن ما بصری
# (پیش‌شکل‌دهی‌شده) ذخیره شده، تکه‌های شکسته از آخر جمله به اول می‌افتند
# (کاربر «از پایین به بالا» می‌خواند). پس هر سطر باید در عرضِ کادرِ خودش
# شکسته شده باشد. مسئله این است که یک رشته می‌تواند در ویجت‌های مختلف دیده
# شود: کادر زیرنویس پهن است (۳۰٫۱em) ولی پنل‌های بازی (هدف، اعلان، ژورنال،
# سند) باریک‌اند (۱۴em اندازه‌گیری‌شده).
#
# از داده نمی‌توان فهمید کدام رشته در کدام ویجت می‌آید، ولی از متن می‌شود:
#   * دیالوگِ گفته‌شده نشانه‌ی گفتار دارد — ضمیر اول‌شخص، نقل‌قول، لهجه‌ی
#     محاوره، سه‌نقطه، تعجب/پرسش، یا شروع با صوت.
#   * متنِ پنل/اطلاعیه/دادنامه لحن نوشتاری دارد (و دادنامه‌ها پاراگراف‌بندی
#     شده‌اند و شکست خط دارند).
# پس متنِ گفتاری در عرض کادر پهن می‌ماند و بقیه در عرض ایمنِ پنل شکسته می‌شود.
PANEL_SAFE_LIMIT_EM = 14.0

# دسته‌ی «ui» همیشه در جعبه‌های رابط (ژورنال، فهرست، اعلان، راهنما) دیده می‌شود،
# نه در کادر پهنِ زیرنویس؛ پس لحنِ جمله نباید آن را از قاعدهٔ عرض ایمن بیرون بگذارد.
# نمونه‌های واقعی که با معیار لحن رد می‌شدند: «Look Behind Vehicle: Press …»
# (فعل Look در فهرست اصوات گفتاری است)، نام‌های نقل‌قولی مثل «"Angry White Boys"»
# و مأموریت‌های نام‌دار مثل «Defeat Nick "Boom-Boom" Beaumont». اگر این‌ها پهن
# بمانند، ویجت خودش می‌شکند و ترتیب سطر برعکس می‌شود.
UI_SAFE_CAT = "ui"

_SPOKEN_RE = re.compile(
    r"(?:^|\s)(?:I|I'm|I'll|I've|I'd|me|my|mine|we|we're|we'll|we'd|our|us)\b"
    r"|[\"“”«»]"
    r"|\b(?:ain'?t|gonna|gotta|outta|'em|'bout|'cause|'cuz|'round|'til|y'know|"
    r"ya|dat|dere|yer|dis|mo')\b"
    r"|\b\w+in'\b"
    r"|\.\.\.|…",
    re.I)
_INTERJECTION_RE = re.compile(
    r"^(?:yeah|nope?|what|why|how|who|where|when|okay|ok|right|sure|fine|well|oh|"
    r"hey|damn|dammit|shit|christ|jesus|listen|look|come on|wait|hold on|sorry|"
    r"thanks|please|hello|hi|good|great|maybe|huh)\b",
    re.I)
_QUESTION_TAIL_RE = re.compile(r"[!?][\"”']?$")


def safe_limit(limit: int, panel_em: float | None = PANEL_SAFE_LIMIT_EM) -> int:
    """حدِ ایمنِ پنل؛ هرگز پهن‌تر از باریک‌ترین کادرِ شناخته‌شده‌ی بازی."""
    if panel_em is None:
        return limit
    return min(limit, int(round(panel_em * EM)))


def panel_like(en: str | None) -> bool:
    """متنِ پنل/اطلاعیه/سند است (نه دیالوگِ گفته‌شده)؟"""
    if not en:
        return False
    if "\r\n" in en:
        return True                     # پاراگراف‌بندی‌شده: پنل/سند/راهنما
    text = en.strip()
    if _QUESTION_TAIL_RE.search(text):
        return False                    # پرسش/تعجب: گفتاری
    if _INTERJECTION_RE.match(text):
        return False
    if _SPOKEN_RE.search(text):
        return False
    return True


PANEL_ROWS: set = set()


def load_panel_rows(path: str) -> int:
    """فهرست ردیف‌های پنل‌های باریک را از TSV می‌خواند (خطوط شروع‌شده با # نادیده)."""
    global PANEL_ROWS
    rows = set()
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                sid = line.split("\t", 1)[0].strip()
                if sid.isdigit():
                    rows.add(int(sid))
    except FileNotFoundError:
        return 0
    PANEL_ROWS = rows
    return len(rows)

# فعل‌های امری که با آن‌ها «هدف/مأموریت»های رابط ساخته می‌شوند (Title Case و
# بدون نقطهٔ پایانی). این‌ها همان رشته‌هایی هستند که در پنل هدف و فهرست اهداف
# ژورنال دیده می‌شوند.
OBJECTIVE_VERBS = (
    "Find", "Clear", "Kill", "Reach", "Destroy", "Steal", "Escape", "Recover",
    "Return", "Talk", "Meet", "Deliver", "Retrieve", "Eliminate", "Take", "Bring",
    "Follow", "Speak", "Collect", "Disable", "Sabotage", "Infiltrate", "Protect",
    "Defend", "Rescue", "Wiretap", "Interrogate", "Locate", "Lose", "Drive",
    "Smash", "Blow", "Purchase", "Visit", "Rendezvous", "Regroup", "Confront",
    "Dismantle", "Pick", "Plant", "Bribe", "Recruit", "Ambush", "Raid", "Survive",
    "Flee", "Assassinate", "Track", "Search", "Grab", "Open", "Place", "Arm",
    "Wait", "Lure", "Escort", "Chase", "Tail", "Stash", "Wire", "Hack", "Rob",
    "Hunt", "Free", "Release", "Stop", "Save", "Repair", "Set", "Use", "Call",
    "Enter", "Exit", "Activate", "Enable", "Trade", "Sell", "Buy", "Distract",
    "Sneak", "Turn", "Jump", "Climb", "Swim", "Eat", "Drink", "Answer", "Send",
    "Play", "Pay", "Leave", "Give", "Hold", "Hide", "Knock", "Ride", "Reload",
)
_OBJECTIVE_RE = re.compile(r"^(%s)\b" % "|".join(OBJECTIVE_VERBS))


# ---------------------------------------------------------------------------
# پنل‌ها/راهنماهای قالبی (نقشه و HUD)
# ---------------------------------------------------------------------------
# چند ردیف جدول، متن چندخطیِ قالبی‌اند که بازی مقادیر را در %s/{} می‌گذارد و در
# کادرهای باریک (مثلاً راهنمای شناور نقشه) نشان می‌دهد: «%s رکت / %s محله»،
# «ورودی‌های پیدا‌شده: %s/%s / مزدورها: %s/%s» و … . سطرهای این ردیف‌ها پهن‌تر از
# کادر باریک‌اند و خودِ ویجت آن‌ها را می‌شکند؛ چون متن پیش‌شکل‌دهی‌شده است، ترتیب
# سطر برعکس می‌شود. این‌ها را هم خودمان در همان حد باریک می‌شکنیم.
_PLACEHOLDER_RE = re.compile(r"%[-+0#]*\d*(?:\.\d+)?[a-zA-Z]|\{[^}]*\}")


# ---------------------------------------------------------------------------
# سقفِ خطِ انگلیسی
# ---------------------------------------------------------------------------
# بازی خیلی از متن‌های چندخطی را از پیش شکسته است (عنوان + متن راهنما، فهرست‌ها،
# تیتراژ…). آن خط‌های انگلیسی داخل کادر جا می‌شوند؛ پس اگر خط فارسی از معادل
# انگلیسی‌اش پهن‌تر شود، ویجت مجبور می‌شود خودش بشکند و ترتیب برعکس می‌شود.
# قاعده: هیچ خط فارسی از خط انگلیسیِ متناظرش پهن‌تر نمی‌شود (کف ۱۴em تا لبه‌های
# بی‌خطرِ کادرهای پهن دست‌نخورده بمانند).
EN_BOUND_FLOOR_EM = 14.0
EN_BOUND_TOLERANCE_EM = 0.5


def wrap_lines_to_english(fa: str, en: str, metrics: Metrics, limit: int):
    """خطوط فارسی را در عرضِ کادرِ ثابت‌شده با متن انگلیسی می‌شکند.

    کادر دست‌کم به‌قدر پهن‌ترین خطِ انگلیسیِ همان رشته است؛ اگر آن پهن‌ترین خط
    کوچک باشد (راهنما/پنل باریک)، خطوط فارسی هم در همان حد می‌شکنند تا ویجت
    مجبور نشود خودش بشکند و ترتیب را برعکس کند.
    """
    fa_lines = fa.split("\r\n")
    en_lines = en.split("\r\n")
    if not en_lines:
        return None
    widest_en = max(metrics.width(line) for line in en_lines) / EM
    cap_em = max(EN_BOUND_FLOOR_EM, widest_en)
    if cap_em + EN_BOUND_TOLERANCE_EM >= limit / EM:
        return None            # کادر پهن است؛ قاعدهٔ معمولِ زیرنویس کافی است
    cap = int(round((cap_em + EN_BOUND_TOLERANCE_EM) * EM))
    if all(metrics.width(line) <= cap for line in fa_lines):
        return None
    result = []
    for fa_line in fa_lines:
        if metrics.width(fa_line) <= cap:
            result.append(fa_line)
            continue
        result.extend(wrap_line(fa_line, metrics, cap))
    return "\r\n".join(result)


def is_template_panel(en: str) -> bool:
    """آیا این رشته یک متن قالبیِ چندخطی است که در کادر باریک نشان داده می‌شود؟"""
    if not en or "\r\n" not in en:
        return False
    return bool(_PLACEHOLDER_RE.search(en))


def _template_units(line: str) -> list[str]:
    """واژه‌ها را به واحدهایی می‌شکند که جای‌نگهدار (%s/{}‌) وسطشان نباشد.

    «%s کسب‌وکار خلاف» باید یک واحد بماند تا جای‌نگهدارِ نام از برچسبش جدا نشود.
    """
    words = line.split(" ")
    units: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        if _PLACEHOLDER_RE.search(word):
            if index + 1 < len(words) and words[index + 1]:
                units.append(word + " " + words[index + 1])
                index += 2
                continue
            if units:
                units[-1] = units[-1] + " " + word
                index += 1
                continue
        units.append(word)
        index += 1
    return units


def wrap_template(fa: str, metrics: Metrics, limit: int) -> str:
    """متن قالبیِ چندخطی را با حفظ جای‌نگه‌دارها در حد کادر باریک می‌شکند.

    جای‌نگه‌دارها به واژهٔ چسبیده‌شان قفل شده‌اند (`_template_units`)، پس
    مقدارها هرگز از برچسبشان جدا نمی‌شوند؛ خودِ شکستن هم متعادل است.
    """
    result: list[str] = []
    for line in fa.split("\r\n"):
        if metrics.width(line) <= limit:
            result.append(line)
            continue
        result.extend(_balanced_breaks(_template_units(line), metrics, limit))
    return "\r\n".join(result)


def is_objective(en: str, cat: str | None) -> bool:
    """آیا این رشته یک «هدف/مأموریت» رابط است که در کادر باریک نشان داده می‌شود؟"""
    if cat != "ui" or not en:
        return False
    text = en.strip()
    if not text or len(text) > 70:
        return False
    if text.endswith(".") or text.endswith("!") or text.endswith("?"):
        return False                    # جملهٔ کامل ⇒ دیالوگ/توضیح، نه هدف
    if text.endswith("Desc") or " Desc" in text:
        return False                    # توضیح تنظیمات، در فهرست پهن دیده می‌شود
    if "\r\n" in text or "[RET]" in text:
        return False
    return bool(_OBJECTIVE_RE.match(text))

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


def _balanced_breaks(units, metrics: Metrics, limit: int, first_limit: int | None = None):
    """واحدها را به سطرهای ≤ حد می‌شکند و سطرها را هم‌عرض نگه می‌دارد.

    برنامه‌ریزی پویا روی مرز واحدها: هزینهٔ هر سطر = مربع فضای خالیِ آن، به‌علاوهٔ
    جریمهٔ سنگین برای سطر تک‌واحدی و واژهٔ ناچاربلند. چون با افزودن هر سطر مجموع
    فضای خالی بزرگ‌تر می‌شود، این روش تعداد سطر را زیاد نمی‌کند و فقط تقسیم را
    متعادل می‌کند.
    """
    if not units:
        return []
    if len(units) <= 1:
        return [units[0]]
    n = len(units)
    widths = [metrics.width(u) for u in units]
    space = metrics.space
    single_penalty = (limit / EM) ** 2 * 6.0
    INF = float("inf")
    best = [INF] * (n + 1)
    choice = [0] * (n + 1)
    best[n] = 0.0
    for i in range(n - 1, -1, -1):
        cap = first_limit if (i == 0 and first_limit) else limit
        width = 0.0
        for j in range(i, n):
            width = widths[j] if j == i else width + space + widths[j]
            if width > cap and j > i:
                break
            slack = (limit - width) / EM
            cost = slack * slack
            if j == i and n > 1:
                cost += single_penalty
            if width > cap:                      # واژهٔ بسیار بلند: ناچار
                cost += single_penalty * 4
            total = cost + best[j + 1]
            if total < best[i]:
                best[i] = total
                choice[i] = j + 1
    result, i = [], 0
    while i < n:
        j = choice[i]
        if j <= i:
            j = i + 1
        result.append(" ".join(units[i:j]))
        i = j
    return result


def wrap_line(line: str, metrics: Metrics, limit: int, first_limit: int | None = None):
    """یک سطر منطقی را به تکه‌های ≤ حد عرض می‌شکند — با سطرهای هم‌عرض.

    شکستنِ حریصانه (پر کردن هر سطر تا آخرین واژهٔ جا‌شده) ته سطرها یک واژهٔ
    تنها می‌گذاشت («… پیدا کنید و / بکشید») و همان چیزی است که کاربر «باگ
    چندخطی» می‌بیند.
    """
    if metrics.width(line) <= (first_limit or limit):
        return [line]
    words = line.split(" ")
    if len(words) <= 1:
        return [line]
    return _balanced_breaks(words, metrics, limit, first_limit)


def plan_lines(fa: str, metrics: Metrics, limit: int, first_limit: int | None = None):
    """سطرهای منطقی نهایی را می‌سازد؛ شکست‌های دستی (\r\n) حفظ می‌شوند.

    ``first_limit`` (اختیاری) حد باریک‌تری برای اولین سطر است؛ چون موتور بازی
    «نام: » را پیش از متن می‌گذارد و سطر اولِ دیالوگ را پهن‌تر می‌کند.
    """
    result = []
    for part in fa.split("\r\n"):
        part_limit = limit
        if first_limit is not None and not result:
            part_limit = min(limit, first_limit)
        if metrics.width(part) <= part_limit:
            result.append(part)
            continue
        result.extend(wrap_line(part, metrics, part_limit,
                                part_limit if part_limit != limit else None))
    return result


def speaker_label_value(text: str):
    """رشتهٔ نام گوینده را با یک شکست خط تمام می‌کند (idempotent)."""
    if not text:
        return None
    if text.endswith(LABEL_SUFFIX):
        return None
    return text.rstrip("\r\n") + LABEL_SUFFIX


def wrap_entry(en: str, fa: str, cat: str | None, metrics, limit: int,
               sid: int | None = None, panel_em: float | None = PANEL_SAFE_LIMIT_EM):
    """خروجی نهایی: fa با شکست خط‌های درست، یا None اگر تغییری لازم نبود.

    فقط رشته‌های فارسیِ دسته‌های زیرنویس/رابط که خودِ بازی می‌شکند بازچینی
    می‌شوند؛ فهرست‌های مسیر، متن‌های تیتراژ و رشته‌های دارای مارکاپ دست‌نخورده
    می‌مانند.
    """
    if metrics is None or not fa:
        return None
    if sid is not None and sid in PANEL_ROWS:        # پنل باریک ژورنال/اعلان
        lines = plan_lines(fa, metrics, int(round(PANEL_LIMIT_EM * EM)))
        joined = "\r\n".join(lines)
        return joined if joined != fa else None
    if en and en.strip() in SPEAKER_LABELS:          # برچسب نام گوینده
        return speaker_label_value(fa)
    if is_template_panel(en):                         # راهنمای قالبی (نقشه/HUD)
        joined = wrap_template(fa, metrics, int(round(HUD_LIMIT_EM * EM)))
        return joined if joined != fa else None
    if cat is not None and cat not in SUBTITLE_CATS:
        return None
    if is_objective(en, cat):                          # هدف در کادر باریک پنل
        hud = int(round(HUD_LIMIT_EM * EM))
        lines = plan_lines(fa, metrics, hud)
        joined = "\r\n".join(lines)
        return joined if joined != fa else None
    if not any(unicodedata.category(ch) == "Lo" and 0x0600 <= ord(ch) <= 0x06FF for ch in fa):
        return None                                   # فقط متن فارسی
    if _MARKUP_RE.search(fa):
        return None                                   # مارکاپ/تیتراژ دست‌نخورده
    if "[RET]" in fa:
        return None            # شکست خط‌های خودِ بازی (فهرست مسیرها) دست‌نخورده می‌ماند
    # هر متنِ جدول مشترک در عرض ایمنِ پنل شکسته می‌شود (نه فقط متن‌های پنلی):
    # تا وقتی ویجت‌های بازی دست‌کم ۱۴em عرض دارند، هیچ سطری را خودشان نمی‌شکنند.
    if panel_em is not None and (panel_like(en) or cat == UI_SAFE_CAT):
        limit = safe_limit(limit, panel_em)
    if "\r\n" in fa and "\r\n" in (en or ""):       # متن از پیش شکسته (پنل/راهنما)
        bounded = wrap_lines_to_english(fa, en, metrics, limit)
        if bounded is not None:
            return bounded
        # وگرنه قاعدهٔ معمولِ زیرنویس/کادر پهن اعمال می‌شود
    lines = plan_lines(fa, metrics, limit,
                       first_limit=limit - int(round(SEPARATOR_EM * EM)))
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
    # برچسب نام گوینده: شکست خط انتهایی اضافه می‌شود و تابع idempotent است
    lab = speaker_label_value("جورجو")
    assert lab == "جورجو" + LABEL_SUFFIX, repr(lab)
    assert speaker_label_value(lab) is None, repr(lab)
    assert speaker_label_value("جورجو\r\n") == "جورجو" + LABEL_SUFFIX
    # هدف‌ها: تشخیص درست + شکستن در کادر باریک
    assert is_objective("Find the Crash Site", "ui")
    assert is_objective("Track down and Kill Dixie Patrols", "ui")
    assert not is_objective("Find the Crash Site", "bark")
    assert not is_objective("Take a walk back over dere again.", "ui")
    assert not is_objective("Drive Shooting Accuracy Desc", "ui")
    # متن‌های قالبیِ چندخطی (راهنمای نقشه/HUD)
    assert is_template_panel("%s Racket \r\n%s District")
    assert is_template_panel("Entrances Found %s/%s\r\nEnforcers %s/%s")
    assert not is_template_panel("%s Racket")
    assert not is_template_panel("Watch you don\u2019t end up in one of those cells, soldier boy.")
    # ردیف‌های پنل باریک: همیشه در عرض PANEL_LIMIT_EM شکسته می‌شوند
    PANEL_ROWS.add(1)
    lab_lines = plan_lines("الف ب پ ت ث ج چ ح خ د ذ ر ز ژ س ش ص ض ط ظ ع غ ف ق ک گ ل م ن و ه ی " * 3,
                           metrics, metrics.space * 6)
    assert len(lab_lines) > 1, lab_lines
    PANEL_ROWS.clear()
    # سقف خط انگلیسی: خط فارسی از معادل انگلیسی پهن‌تر نمی‌شود
    en_line = "Hold " + wide * 3
    fa_line = " ".join("واژه" + wide for _ in range(12))
    bounded = wrap_lines_to_english(fa_line + "\r\nدوم", en_line + "\r\nدوم", metrics, 10 ** 9)
    assert bounded and len(bounded.split("\r\n")) > 2, bounded
    # اگر پهن‌ترین خط انگلیسی پهن باشد (کادر پهن)، خط فارسیِ کوتاه‌تر دست‌نخورده می‌ماند
    wide_en = " ".join("word" + wide for _ in range(40))
    short_fa = "خط کوتاه"
    assert wrap_lines_to_english(short_fa, wide_en + "\r\n" + wide_en, metrics, 10 ** 9) is None
    # جای‌نگهدار از برچسبش جدا نمی‌شود
    units = _template_units("%s کسب‌وکار خلاف %s محله")
    assert units and units[0] == "%s کسب‌وکار" and units[1] == "خلاف" and units[2] == "%s محله", units
    assert _template_units("سلام %s دنیا") == ["سلام", "%s دنیا"]
    label = "خبرچین‌های بازجویی‌شده: %s/%s"
    assert wrap_template(label, metrics, metrics.space * 40) == label
    long_line = "مزدورها " + " ".join("واژه" + wide for _ in range(6))
    wrapped = wrap_template(long_line, metrics, metrics.space * 10)
    assert len(wrapped.split("\r\n")) > 1, wrapped
    assert wrapped.split("\r\n")[0].startswith("مزدورها"), wrapped
    # سطر اول دیالوگ با حد باریک‌تر بسته می‌شود (جا برای «: » موتور)
    narrow = plan_lines(plain, metrics, metrics.space * 30,
                        first_limit=metrics.space * 10)
    assert metrics.width(narrow[0]) <= metrics.space * 10, narrow[0]
    # idempotent
    out = "\r\n".join(plan_lines(plain, metrics, metrics.space * 30))
    assert "\r\n".join(plan_lines(out, metrics, metrics.space * 30)) == out
    print("✔ آزمون شکستن خطوط زیرنویس (ترتیب، نام گوینده، شکست دستی، idempotent) قبول شد")


if __name__ == "__main__":
    _self_test()
