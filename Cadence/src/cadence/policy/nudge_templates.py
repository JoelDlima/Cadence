# Indic-language recovery nudge templates.
#
# Six Indian languages (Hindi, Tamil, Telugu, Bengali, Marathi, Gujarati) plus
# the existing Hinglish default. Each template uses the same shape:
# a short greeting, the amount in INR, a one-line ask, an optional
# payment link, an opt-out line, and a sign-off. The sign-off is the
# product brand "Cadence" so the customer always knows who is
# contacting them.
#
# The templates are deterministic, copy-reviewable, and live in source
# so they can be reviewed without running the engine. The reason for
# keeping them here (instead of in channels.py): the dispatcher
# doesn't know the customer's locale, so this is the layer that
# resolves (customer, language) -> text. The SPA exposes a
# /api/nudge/preview endpoint that calls `nudge_for_language` so the
# demo can show side-by-side renders in 6 languages.
from __future__ import annotations

from typing import Final

# Customer-facing brand. Per the product spec, "Cadence" is the
# customer-facing brand; the underlying module is "Cadence".
_BRAND: Final = "Cadence"

# Six Indic scripts + the existing Hinglish default.
SUPPORTED_LANGUAGES: Final = frozenset({
    "hi",  # Hindi (Devanagari)
    "ta",  # Tamil
    "te",  # Telugu
    "bn",  # Bengali
    "mr",  # Marathi (Devanagari)
    "gu",  # Gujarati
    "hinglish",  # default
})


def _format_inr(amount_minor: int) -> str:
    rupees = amount_minor / 100.0
    if rupees == int(rupees):
        return f"\u20b9{int(rupees)}"
    return f"\u20b9{rupees:.2f}"


def _hi(amount_minor: int, link_url: str | None) -> str:
    amt = _format_inr(amount_minor)
    if link_url:
        return (
            f"Namaste! Aapki {amt} ki subscription payment pending hai. "
            f"Kripya yahan pay karein: {link_url}. "
            f"Sawaal ho toh reply karein. - {_BRAND}"
        )
    return (
        f"Namaste! Aapki {amt} ki subscription payment pending hai. "
        f"Jab convenient ho pay kar dijiye. "
        f"Sawaal ho toh reply karein. - {_BRAND}"
    )


def _ta(amount_minor: int, link_url: str | None) -> str:
    amt = _format_inr(amount_minor)
    if link_url:
        return (
            f"Vanakkam! Ungal {amt} subscription payment pending ah. "
            f"Ingai pay seithu kudungal: {link_url}. "
            f"Sandhosam illana reply seithungal. - {_BRAND}"
        )
    return (
        f"Vanakkam! Ungal {amt} subscription payment pending ah. "
        f"Uyarvaga irukka nerathilay pay seithungal. "
        f"Sandhosam illana reply seithungal. - {_BRAND}"
    )


def _te(amount_minor: int, link_url: str | None) -> str:
    amt = _format_inr(amount_minor)
    if link_url:
        return (
            f"Namaskaram! Mee {amt} subscription payment pending ga undi. "
            f"Daaniki ikkada pay cheyandi: {link_url}. "
            f"Samsyam vasthe reply ivvandi. - {_BRAND}"
        )
    return (
        f"Namaskaram! Mee {amt} subscription payment pending ga undi. "
        f"Suitable time lo pay cheyandi. "
        f"Samsyam vasthe reply ivvandi. - {_BRAND}"
    )


def _bn(amount_minor: int, link_url: str | None) -> str:
    amt = _format_inr(amount_minor)
    if link_url:
        return (
            f"Namaskar! Apnar {amt} subscription payment boondhi ache. "
            f"Anekdin deya din ekhane pay korun: {link_url}. "
            f"Proshno thakle reply din. - {_BRAND}"
        )
    return (
        f"Namaskar! Apnar {amt} subscription payment boondhi ache. "
        f"Apnar sohoj somoy pay kore nin. "
        f"Proshno thakle reply din. - {_BRAND}"
    )


def _mr(amount_minor: int, link_url: str | None) -> str:
    amt = _format_inr(amount_minor)
    if link_url:
        return (
            f"Namaskar! Tumcha {amt} subscription payment pending aahe. "
            f"Krupaya ithhe pay kara: {link_url}. "
            f"Prashna asel tar reply kara. - {_BRAND}"
        )
    return (
        f"Namaskar! Tumcha {amt} subscription payment pending aahe. "
        f"Somojnya hoil tewa thambun pay kara. "
        f"Prashna asel tar reply kara. - {_BRAND}"
    )


def _gu(amount_minor: int, link_url: str | None) -> str:
    amt = _format_inr(amount_minor)
    if link_url:
        return (
            f"Namaskar! Tamaro {amt} subscription payment pending che. "
            f"Krupaya ae rithe pay karo: {link_url}. "
            "Prashna hoy to reply karo. - " + _BRAND
        )
    return (
        f"Namaskar! Tamaro {amt} subscription payment pending che. "
        f"Saral samye pay karo. "
        f"Prashna hoy to reply karo. - {_BRAND}"
    )


def _hinglish(amount_minor: int, link_url: str | None) -> str:
    amt = _format_inr(amount_minor)
    if link_url:
        return (
            f"Hi! Aapka {amt} ka payment pending hai. "
            f"Pay karne ke liye: {link_url}. - {_BRAND}"
        )
    return (
        f"Hi! Aapka {amt} ka payment pending hai. "
        f"Jab convenient ho pay kar dijiye. - {_BRAND}"
    )


_RENDERERS = {
    "hi": _hi,
    "ta": _ta,
    "te": _te,
    "bn": _bn,
    "mr": _mr,
    "gu": _gu,
    "hinglish": _hinglish,
}


def nudge_for_language(
    language: str,
    amount_minor: int,
    link_url: str | None = None,
) -> str:
    """Return the recovery nudge text for the given language.

    `language` is one of `SUPPORTED_LANGUAGES`. Unknown languages
    fall back to "hinglish". The `link_url` is included verbatim if
    provided; otherwise the nudge is link-free.
    """
    if language not in SUPPORTED_LANGUAGES:
        language = "hinglish"
    return _RENDERERS[language](amount_minor, link_url)


__all__ = ["nudge_for_language", "SUPPORTED_LANGUAGES"]
