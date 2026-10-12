# -*- coding: utf-8 -*-
"""پیش‌شکل‌دهی و بازچینی RTL فقط برای باینری xbin.

XML، بچ‌های TSV و حافظه‌ی ترجمه هرگز از این ماژول عبور نمی‌کنند؛ بنابراین متن
منبع خوانا می‌ماند. توکن‌های فنی با TOKEN_RE محافظت می‌شوند و مارکاپ‌های جفت
شده پس از بازچینی دوباره دور همان نویسه‌ها قرار می‌گیرند.
"""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import re

import fslib

_TAG_INNER_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\s|=|/|$)")
_NEWLINE_RE = re.compile(r"(\r\n|\r|\n)")
# Protect a lone literal percent as well; printf placeholders are already in TOKEN_RE.
_SHAPE_TOKEN_RE = re.compile(
    f"(?:{fslib.TOKEN_RE.pattern})|\\[[A-Z][A-Z0-9_]*\\]|"
    f"%(?![-+0#]*\\d*(?:\\.\\d+)?[a-zA-Z])",
    fslib.TOKEN_RE.flags,
)


@dataclass(frozen=True, eq=False)
class _Style:
    """یک بازه‌ی مارکاپ؛ identity برای تشخیص دقیق مرزهای nested لازم است."""
    name: str
    open_token: str
    close_token: str


@dataclass(frozen=True)
class _Element:
    char: str
    styles: tuple[_Style, ...]
    token: str | None = None


_RESHAPER = None
_BIDI = None


def _load_engines():
    global _RESHAPER, _BIDI
    if _RESHAPER is not None:
        return _RESHAPER, _BIDI
    try:
        import arabic_reshaper
        from bidi import algorithm as bidi
    except ImportError as exc:
        raise SystemExit(
            "برای پیش‌شکل‌دهی فارسی، وابستگی‌ها را نصب کنید: "
            "python3 -m pip install -r requirements-gfx.txt"
        ) from exc
    # لیگچرها خاموش‌اند تا هر نویسه پس از شکل‌دهی دقیقاً با همان نویسه‌ی
    # منطقی متناظر بماند و جای توکن‌ها/مارکاپ‌ها هنگام Bidi گم نشود.
    _RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
        "delete_harakat": False,
        "support_ligatures": False,
        "shift_harakat_position": False,
    })
    _BIDI = bidi
    return _RESHAPER, _BIDI


def _tag_spec(token: str):
    """(name, closing, self-closing) برای تگ خام یا XML-escaped؛ وگرنه None."""
    if token.startswith("&lt;") and token.endswith("&gt;"):
        inner = token[4:-4]
    elif token.startswith("<") and token.endswith(">"):
        inner = token[1:-1]
    else:
        return None
    inner = inner.strip()
    if not inner or inner.startswith(("!", "?")):
        return None
    closing = inner.startswith("/")
    if closing:
        inner = inner[1:].lstrip()
    self_closing = inner.endswith("/")
    if self_closing:
        inner = inner[:-1].rstrip()
    match = _TAG_INNER_RE.match(inner)
    if not match:
        return None
    return match.group(1).lower(), closing, self_closing


def _pair_markup(tokens: list[str]):
    """جفت‌های باز/بسته را می‌یابد؛ تگ‌های نامتوازن به‌صورت توکن حفظ می‌شوند."""
    stack = []
    pairs = {}
    for index, token in enumerate(tokens):
        spec = _tag_spec(token)
        if spec is None:
            continue
        name, closing, self_closing = spec
        if self_closing:
            continue
        if closing:
            if stack and stack[-1][1] == name:
                open_index, _ = stack.pop()
                pairs[open_index] = index
                pairs[index] = open_index
        else:
            stack.append((index, name))
    return pairs


def _marker_codes(text: str, count: int):
    """نشانگرهای یکتای PUA که کلاس Bidi آن‌ها L است و در خروجی نشت نمی‌کنند."""
    if count == 0:
        return []
    used = set(text)
    result = []
    for codepoint in itertools.chain(range(0xE000, 0xF900), range(0xF0000, 0xF1000)):
        ch = chr(codepoint)
        if ch not in used:
            result.append(ch)
            used.add(ch)
            if len(result) == count:
                return result
    raise ValueError("برای محافظت از توکن‌ها نشانگر PUA یکتا پیدا نشد.")


def _reorder_with_indices(elements: list[_Element], bidi):
    """نسخه‌ی get_display که نگاشت هر نویسه به استایل/توکن اصلی را هم نگه می‌دارد."""
    text = "".join(element.char for element in elements)
    storage = bidi.get_empty_storage()
    storage["base_level"] = 1
    storage["base_dir"] = "R"
    bidi.get_embedding_levels(text, storage)
    for index, item in enumerate(storage["chars"]):
        item["_farsisaz_index"] = index
    bidi.explicit_embed_and_overrides(storage, False)
    bidi.resolve_weak_types(storage, False)
    bidi.resolve_neutral_types(storage, False)
    bidi.resolve_implicit_levels(storage, False)
    bidi.reorder_resolved_levels(storage, False)
    bidi.apply_mirroring(storage, False)
    result = []
    for item in storage["chars"]:
        original = elements[item["_farsisaz_index"]]
        result.append(_Element(item["ch"], original.styles, original.token))
    return result


def _render_styled(elements: list[_Element]) -> str:
    """تگ‌های مارکاپ را روی خوشه‌های بصریِ دارای همان استایل بازسازی می‌کند."""
    output = []
    active: tuple[_Style, ...] = ()
    for element in elements:
        wanted = element.styles
        shared = 0
        while (shared < len(active) and shared < len(wanted)
               and active[shared] is wanted[shared]):
            shared += 1
        for style in reversed(active[shared:]):
            output.append(style.close_token)
        for style in wanted[shared:]:
            output.append(style.open_token)
        active = wanted
        output.append(element.token if element.token is not None else element.char)
    for style in reversed(active):
        output.append(style.close_token)
    return "".join(output)


def _shape_line(line: str) -> str:
    if not fslib.has_rtl(line):
        return line
    reshaper, bidi = _load_engines()

    token_matches = list(_SHAPE_TOKEN_RE.finditer(line))
    tokens = [match.group(0) for match in token_matches]
    pairs = _pair_markup(tokens)
    open_styles = {}
    for open_index, close_index in pairs.items():
        if open_index < close_index:
            name = _tag_spec(tokens[open_index])[0]
            open_styles[open_index] = _Style(name, tokens[open_index], tokens[close_index])

    markers = _marker_codes(line, len(tokens))
    elements = []
    raw_chars = []
    style_stack: list[_Style] = []

    def flush_text():
        if not raw_chars:
            return
        raw = "".join(char for char, _styles in raw_chars)
        shaped = reshaper.reshape(raw)
        if len(shaped) != len(raw):
            raise ValueError(
                "arabic_reshaper طول متن را تغییر داد؛ لیگچرها باید خاموش باشند."
            )
        for char, (_original, styles) in zip(shaped, raw_chars):
            elements.append(_Element(char, styles))
        raw_chars.clear()

    cursor = 0
    for token_index, match in enumerate(token_matches):
        for char in line[cursor:match.start()]:
            raw_chars.append((char, tuple(style_stack)))
        token = match.group(0)
        if token_index in open_styles:
            style_stack.append(open_styles[token_index])
        elif token_index in pairs:
            open_index = pairs[token_index]
            if style_stack and style_stack[-1] is open_styles.get(open_index):
                style_stack.pop()
            else:
                # تگ تو‌در‌تو/نامتوازن غیرمنتظره: به‌جای خراب‌کردن مارکاپ،
                # آن را به‌صورت یک توکن فنی نگه می‌داریم.
                flush_text()
                elements.append(_Element(markers[token_index], tuple(style_stack), token))
        else:
            # Placeholderها، کدهای دکمه و تگ‌های نامتوازن یک‌تکه می‌مانند.
            flush_text()
            elements.append(_Element(markers[token_index], tuple(style_stack), token))
        cursor = match.end()
    for char in line[cursor:]:
        raw_chars.append((char, tuple(style_stack)))
    flush_text()

    # اگر یک نشانگر از مسیر استایل عبور کرده باشد، باز هم جایگزینی اتمی انجام می‌شود.
    if not elements:
        return line
    visual = _reorder_with_indices(elements, bidi)
    return _render_styled(visual)


def shape_text(text: str) -> str:
    """متن را برای موتور LTR بازی به فرم بصریِ پیش‌شکل‌داده‌شده تبدیل می‌کند.

    پایان‌خط‌های CRLF/LF/CR عیناً حفظ می‌شوند. متن بدون RTL دست‌نخورده است.
    """
    if not fslib.has_rtl(text):
        return text
    parts = _NEWLINE_RE.split(text)
    return "".join(part if part in ("\r\n", "\r", "\n") else _shape_line(part)
                   for part in parts)


def _self_test():
    """چند حالت حساس: شکل‌دهی، RTL، توکن‌ها، مارکاپ و CRLF."""
    cases = [
        ("سلام", None),
        ("قبل %s بعد", "%s"),
        ("برای #E_CTRL_MAP# باز کن", "#E_CTRL_MAP#"),
        ("&lt;bold&gt;سلام&lt;/bold&gt;", None),
        ("خط اول\r\nخط دوم", "\r\n"),
        ("متن (۱۲۳) سلام", None),
        ("آزمایش [HORN]، [ROAR]، [RT] و [X]", "[HORN]"),
    ]
    for source, must_keep in cases:
        result = shape_text(source)
        if must_keep and must_keep not in result:
            raise AssertionError("توکن/پایان‌خط از دست رفت: %r -> %r" % (source, result))
        for marker in ("[HORN]", "[ROAR]", "[RT]", "[X]"):
            if marker in source and marker not in result:
                raise AssertionError("توکن براکتی جابه‌جا/خراب شد: %s" % marker)
        if fslib.token_signature(source) != fslib.token_signature(result):
            raise AssertionError("امضای توکن عوض شد: %r -> %r" % (source, result))
    print("✔ پیش‌شکل‌دهی، Bidi، توکن‌ها، مارکاپ و CRLF تأیید شد")


if __name__ == "__main__":
    _self_test()
