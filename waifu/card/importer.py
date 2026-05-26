from __future__ import annotations

from pathlib import Path

from waifu.card.parser import SUPPORTED_SUFFIXES, CardError, CardParser, NormalizedCard


class CardImporter:
    def __init__(self, soul_dir: Path, parser: CardParser) -> None:
        self._soul_dir = soul_dir
        self._parser = parser

    @property
    def soul_dir(self) -> Path:
        return self._soul_dir

    def scan(self) -> list[Path]:
        if not self._soul_dir.exists():
            return []
        return sorted(p for p in self._soul_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)

    def load(self, path: Path) -> NormalizedCard:
        return self._parser.load(path)

    def load_all(self) -> tuple[list[NormalizedCard], list[tuple[Path, Exception]]]:
        cards: list[NormalizedCard] = []
        errors: list[tuple[Path, Exception]] = []
        for path in self.scan():
            try:
                cards.append(self._parser.load(path))
            except (CardError, FileNotFoundError) as exc:
                errors.append((path, exc))
        return cards, errors
