"""Secret values replaced by their names: `[NAME]`. Values shorter than MIN_LENGTH are left alone (blanking them would
mangle ordinary text); the longest value goes first, so one that contains another is blanked whole."""

MIN_LENGTH = 4


def _pairs(secrets: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(((v, f"[{k}]") for k, v in secrets.items() if len(v) >= MIN_LENGTH), key=lambda p: -len(p[0]))


def blank(text: str, secrets: dict[str, str]) -> str:
    for value, label in _pairs(secrets):
        text = text.replace(value, label)
    return text


def blank_json(obj, secrets: dict[str, str]):
    """`blank` in every string of nested dicts and lists; keys are left as they are."""
    if isinstance(obj, str):
        return blank(obj, secrets)
    if isinstance(obj, list):
        return [blank_json(v, secrets) for v in obj]
    if isinstance(obj, dict):
        return {k: blank_json(v, secrets) for k, v in obj.items()}
    return obj
