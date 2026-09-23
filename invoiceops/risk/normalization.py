import unicodedata


def normalize_vendor(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters = [
        character if character.isalnum() else " "
        for character in normalized
    ]
    return " ".join("".join(characters).split())


def normalize_invoice_number(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())
