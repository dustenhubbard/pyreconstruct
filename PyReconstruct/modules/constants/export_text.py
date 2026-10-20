## How a text export writes a name. An object or trace name can hold a lone
## surrogate (half of a UTF-16 pair, from an old or damaged file). Strict
## encoding has no bytes for it, so the export raised. "backslashreplace"
## writes it as the text \ud800 instead: the export finishes and the file
## stays valid UTF-8. Exports are for other programs, so they do not need the
## surrogate back; the .jser and existing_log.csv keep it as it is.
EXPORT_ERRORS = "backslashreplace"


def exportText(text : str) -> str:
    """Return text with each lone surrogate written as the text \\ud800.

    For a name that goes through a library that encodes it strictly, where
    no errors handler can be passed.
    """
    return text.encode("utf-8", EXPORT_ERRORS).decode("utf-8")
