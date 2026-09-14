"""Bounded parsing of a hash-pinned Classic DF interface binding file."""

from dataclasses import dataclass
import hashlib
import re

MAX_FILE_BYTES = 1024 * 1024
MAX_EVENTS = 4096
MAX_EVENTS_PER_KEY = 512
_REPEAT = frozenset({"REPEAT_NOT", "REPEAT_SLOW", "REPEAT_FAST"})
_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,100}")


@dataclass(frozen=True)
class BindingIndex:
    sha256: str
    characters: dict[str, tuple[str, ...]]
    symbols: dict[tuple[int, str], tuple[str, ...]]
    repeat_policy: dict[str, str]
    mouse_bindings: int

    def resolve(self, event: object) -> tuple[str, ...]:
        """Resolve exactly one declared character OR symbol, never select a job."""
        if not isinstance(event, dict):
            raise ValueError("A key event must be an object")
        if set(event) == {"type", "value"} and event["type"] == "character":
            value = event["value"]
            if not isinstance(value, str) or len(value) != 1 or ord(value) < 32:
                raise ValueError("Expected one KEY character")
            found = self.characters.get(value, ())
        elif set(event) == {"type", "value", "modifiers"} and event["type"] == "symbol":
            value, modifiers = event["value"], event["modifiers"]
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= 48
                or type(modifiers) is not int
                or not 0 <= modifiers <= 7
            ):
                raise ValueError("Invalid symbol or modifier mask")
            found = self.symbols.get((modifiers, value), ())
        else:
            raise ValueError("Unsupported keyboard event shape")
        if not found or len(found) > MAX_EVENTS_PER_KEY:
            raise ValueError("Key has no bounded binding set")
        return found


def parse_bindings(raw: bytes) -> BindingIndex:
    """Parse KEY/SYM records while recognizing but not dispatching mouse bindings.

    This describes a fixed interface.txt, not proof of the game's live in-memory
    binding map or physical-device equivalence. The native experiment must bind
    the exact file digest and dispatch the resolved events as ONE simultaneous set.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_FILE_BYTES:
        raise ValueError("Binding file is missing or too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError("Binding file must be UTF-8") from error
    characters: dict[str, set[str]] = {}
    symbols: dict[tuple[int, str], set[str]] = {}
    repeats: dict[str, str] = {}
    current = None
    mouse_bindings = 0
    # Legacy STRING_A records include U+0085; str.splitlines would split that key.
    for number, line in enumerate(text.split("\n"), 1):
        line = line.strip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        bind = re.fullmatch(r"\[BIND:([^:]+):([^:]+)\]", line)
        if bind:
            name, repeat = bind.groups()
            if not _NAME.fullmatch(name) or repeat not in _REPEAT:
                raise ValueError(f"Invalid binding declaration at line {number}")
            if name in repeats and repeats[name] != repeat:
                raise ValueError("Conflicting repeat policies")
            repeats[name], current = repeat, name
            if len(repeats) > MAX_EVENTS:
                raise ValueError("Too many native events")
            continue
        if current is None:
            raise ValueError(f"Input before BIND at line {number}")
        character = re.fullmatch(r"\[KEY:(.*)\]", line)
        if character:
            value = character.group(1)
            if len(value) != 1 or ord(value) < 32:
                raise ValueError(f"Invalid character at line {number}")
            characters.setdefault(value, set()).add(current)
            continue
        symbol = re.fullmatch(r"\[(SYM|BUTTON):([0-7]):([^\r\n]+)\]", line)
        if symbol:
            kind, modifiers, value = symbol.groups()
            if len(value) > 48 or "[" in value or "]" in value:
                raise ValueError(f"Invalid symbol at line {number}")
            if kind == "BUTTON":
                if not value.isascii() or not value.isdecimal() or int(value) > 255:
                    raise ValueError(f"Invalid mouse button at line {number}")
                mouse_bindings += 1
            else:
                symbols.setdefault((int(modifiers), value), set()).add(current)
            continue
        raise ValueError(f"Unknown binding record at line {number}")
    if not repeats or not (characters or symbols):
        raise ValueError("No keyboard bindings")
    return BindingIndex(
        hashlib.sha256(raw).hexdigest(),
        {key: tuple(sorted(values)) for key, values in characters.items()},
        {key: tuple(sorted(values)) for key, values in symbols.items()},
        repeats,
        mouse_bindings,
    )
