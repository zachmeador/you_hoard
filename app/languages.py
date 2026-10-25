"""Common YouTube language codes for the subtitle and audio pickers."""

LANGUAGES = [
    ("en", "English"),
    ("en-GB", "English (United Kingdom)"),
    ("es", "Spanish"),
    ("es-419", "Spanish (Latin America)"),
    ("pt", "Portuguese"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("pt-PT", "Portuguese (Portugal)"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("nl", "Dutch"),
    ("sv", "Swedish"),
    ("no", "Norwegian"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("pl", "Polish"),
    ("cs", "Czech"),
    ("sk", "Slovak"),
    ("hu", "Hungarian"),
    ("ro", "Romanian"),
    ("bg", "Bulgarian"),
    ("el", "Greek"),
    ("uk", "Ukrainian"),
    ("ru", "Russian"),
    ("tr", "Turkish"),
    ("ar", "Arabic"),
    ("iw", "Hebrew"),
    ("fa", "Persian"),
    ("hi", "Hindi"),
    ("bn", "Bengali"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("mr", "Marathi"),
    ("ur", "Urdu"),
    ("th", "Thai"),
    ("vi", "Vietnamese"),
    ("id", "Indonesian"),
    ("ms", "Malay"),
    ("fil", "Filipino"),
    ("zh-Hans", "Chinese (Simplified)"),
    ("zh-Hant", "Chinese (Traditional)"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
]
NAMES = {code.lower(): name for code, name in LANGUAGES}


def language_options() -> list[dict[str, str]]:
    return [{"code": code, "name": name} for code, name in LANGUAGES]


def language_name(code: str) -> str | None:
    return NAMES.get(code.lower())
