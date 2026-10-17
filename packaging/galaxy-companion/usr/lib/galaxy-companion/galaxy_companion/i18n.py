# SPDX-License-Identifier: MIT
"""Gettext boundary shared by every Galaxy Companion UI module."""

import gettext
import os

from .translations import LANGUAGE_INDEX, TRANSLATIONS
from .fingerprint_translations import ES as FINGERPRINT_ES
from .update_translations import ES as UPDATE_ES
from .fingerprint_languages import TRANSLATIONS as FINGERPRINT_LANGUAGES
from .update_languages import TRANSLATIONS as UPDATE_LANGUAGES
from .keyboard_translations import TRANSLATIONS as KEYBOARD_TRANSLATIONS

TRANSLATIONS = {**TRANSLATIONS, **KEYBOARD_TRANSLATIONS}


DOMAIN = "galaxy-companion"
LOCALE_DIR = "/usr/share/locale"
# Where the desktop's own translations live (Ubuntu's language packs use the
# second); gnome-shell's catalogue says which languages the desktop shows.
# GALAXY_COMPANION_DESKTOP_LOCALE_DIRS (":"-separated) replaces them in tests.
DESKTOP_LOCALE_DIRS = tuple(filter(None, os.environ.get(
    "GALAXY_COMPANION_DESKTOP_LOCALE_DIRS",
    "/usr/share/locale:/usr/share/locale-langpack").split(":")))
DESKTOP_DOMAIN = "gnome-shell"


def _candidates():
    """The locale names gettext would try, in its order."""
    names = []
    language = os.environ.get("LANGUAGE", "")
    main = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
            or os.environ.get("LANG") or "")
    # gettext ignores LANGUAGE under the C locale
    if main not in ("", "C", "POSIX") and not main.startswith("C."):
        names += [name for name in language.split(":") if name]
    names.append(main)
    for name in names:
        if name in ("", "C", "POSIX") or name.startswith("C."):
            break
        bare = name.split("@", 1)[0].split(".", 1)[0]
        yield name, bare, bare.split("_", 1)[0].split("-", 1)[0].lower()


def _desktop_speaks(*names):
    return any(os.path.exists(os.path.join(directory, name, "LC_MESSAGES",
                                           DESKTOP_DOMAIN + ".mo"))
               for directory in DESKTOP_LOCALE_DIRS for name in names)


def desktop_language():
    """The language Galaxy Companion speaks: the one the desktop shows.

    The locale alone is not enough: a system set to es_ES without GNOME's
    Spanish translations shows English, and so does Galaxy Companion. The
    first wanted language that both the desktop and these catalogues have
    wins; English otherwise."""
    for name, bare, code in _candidates():
        if code == "en":
            return "en"
        if code in LANGUAGE_INDEX and _desktop_speaks(name, bare, code):
            return code
    return "en"


_language = desktop_language()
_translation = gettext.translation(DOMAIN, LOCALE_DIR, languages=[_language], fallback=True)


def _(message):
    translated = _translation.gettext(message)
    if translated != message:
        return translated
    if _language == "es" and message in FINGERPRINT_ES:
        return FINGERPRINT_ES[message]
    if _language == "es" and message in UPDATE_ES:
        return UPDATE_ES[message]
    index = LANGUAGE_INDEX.get(_language)
    if index is not None and index > 0:
        values = FINGERPRINT_LANGUAGES.get(message) or UPDATE_LANGUAGES.get(message)
        if values is not None:
            return values[index - 1]
    values = TRANSLATIONS.get(message)
    return values[index] if index is not None and values is not None else message
ngettext = _translation.ngettext


def N_(message):
    """Mark a deferred string for extraction without translating it yet."""
    return message
