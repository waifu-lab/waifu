import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from waifu.card import CardImporter, NormalizedCard
from waifu.store import CharacterManager
from waifu.store.models import Character, Relationship
from waifu.store.repositories.character import CharacterRepository, RelationshipRepository


@dataclass
class CardImportResult:
    name: str
    source_path: Path
    character_dir: Path
    soul_path: Path
    avatar_path: Optional[Path]
    status: str
    character_id: Optional[str] = None


class CharacterService:
    def __init__(
        self,
        char_repo: CharacterRepository,
        rel_repo: RelationshipRepository,
        manager: Optional[CharacterManager] = None,
        card_importer: Optional[CardImporter] = None,
    ) -> None:
        self._chars = char_repo
        self._rels = rel_repo
        self._manager = manager
        self._card_importer = card_importer

    def create(
        self,
        name: str,
        soul_path: str,
        avatar_path: Optional[str] = None,
        live2d_dir: Optional[str] = None,
    ) -> Character:
        return self._chars.create(name, soul_path, avatar_path, live2d_dir)

    def activate(self, id: str) -> None:
        self._chars.set_active(id)

    def get_active(self) -> Optional[Character]:
        return self._chars.get_active()

    def list_all(self) -> List[Character]:
        return self._chars.list_all()

    def get(self, id: str) -> Optional[Character]:
        return self._chars.get(id)

    def update(self, id: str, **fields) -> None:
        self._chars.update(id, **fields)

    def delete(self, id: str) -> None:
        self._chars.delete(id)

    def get_relationship(self, character_id: str, user_id: str, display_name: str) -> Relationship:
        return self._rels.get_or_create(character_id, user_id, display_name)

    def update_relationship(self, character_id: str, user_id: str, **fields) -> None:
        self._rels.update(character_id, user_id, **fields)

    def list_relationships(self, character_id: str) -> List[Relationship]:
        return self._rels.list_by_character(character_id)

    def get_relationship_detail(self, character_id: str, user_id: str) -> Optional[Relationship]:
        return self._rels.get(character_id, user_id)

    def import_card(self, path: str | Path, *, overwrite: bool = False) -> CardImportResult:
        manager = self._require_manager()
        importer = self._require_importer()
        card = importer.load(Path(path))
        return self._materialize_card(card, manager, overwrite=overwrite)

    def import_all_cards(self, *, overwrite: bool = False) -> tuple[list[CardImportResult], list[tuple[Path, Exception]]]:
        manager = self._require_manager()
        importer = self._require_importer()
        results: list[CardImportResult] = []
        errors: list[tuple[Path, Exception]] = []
        for path in importer.scan():
            try:
                card = importer.load(path)
                results.append(self._materialize_card(card, manager, overwrite=overwrite))
            except Exception as exc:
                errors.append((path, exc))
        return results, errors

    def _materialize_card(
        self,
        card: NormalizedCard,
        manager: CharacterManager,
        *,
        overwrite: bool,
    ) -> CardImportResult:
        name = self._normalize_character_name(card.name)
        existing = self._chars.get_by_name(name)
        char_dir = manager.ensure_character_dir(name)
        soul_path = char_dir / "soul.md"

        if existing is not None and not overwrite:
            avatar = manager.get_avatar(name)
            return CardImportResult(
                name=name,
                source_path=card.source_path,
                character_dir=char_dir,
                soul_path=soul_path,
                avatar_path=avatar,
                status="skipped",
                character_id=str(existing.id),
            )

        soul_path.write_text(self._render_soul(card), encoding="utf-8")
        avatar_path = self._sync_avatar(card, char_dir)
        live2d_dir = char_dir / "live2d"

        if existing is None:
            row = self._chars.create(name, str(soul_path), str(avatar_path) if avatar_path else None, str(live2d_dir))
            status = "created"
        else:
            self._chars.update(
                str(existing.id),
                soul_path=str(soul_path),
                avatar_path=str(avatar_path) if avatar_path else existing.avatar_path,
                live2d_dir=str(live2d_dir),
            )
            row = self._chars.get(str(existing.id))
            status = "updated"

        assert row is not None
        return CardImportResult(
            name=name,
            source_path=card.source_path,
            character_dir=char_dir,
            soul_path=soul_path,
            avatar_path=avatar_path,
            status=status,
            character_id=str(row.id),
        )

    @staticmethod
    def _normalize_character_name(name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\\\|?*]', "_", name).strip().strip(".")
        if not cleaned:
            raise ValueError("Card name is empty after sanitization.")
        return cleaned

    @staticmethod
    def _render_soul(card: NormalizedCard) -> str:
        sections: list[str] = [f"# {card.name}"]

        if card.description:
            sections.append(f"## Description\n{card.description.strip()}")
        if card.personality:
            sections.append(f"## Personality\n{card.personality.strip()}")
        if card.scenario:
            sections.append(f"## Scenario\n{card.scenario.strip()}")
        if card.first_mes:
            sections.append(f"## First Message\n{card.first_mes.strip()}")
        if card.mes_example:
            sections.append(f"## Example Dialogue\n{card.mes_example.strip()}")
        if card.system_prompt:
            sections.append(f"## System Prompt\n{card.system_prompt.strip()}")
        if card.post_history_instructions:
            sections.append(f"## Post History Instructions\n{card.post_history_instructions.strip()}")
        if card.creator_notes:
            sections.append(f"## Creator Notes\n{card.creator_notes.strip()}")
        if card.alternate_greetings:
            sections.append("## Alternate Greetings\n" + "\n".join(f"- {msg}" for msg in card.alternate_greetings))
        if card.tags:
            sections.append("## Tags\n" + ", ".join(card.tags))

        sections.append(
            "## Card Metadata\n"
            f"- source_format: {card.source_format}\n"
            f"- spec: {card.spec}\n"
            f"- spec_version: {card.spec_version or ''}\n"
            f"- creator: {card.creator}\n"
            f"- character_version: {card.character_version}"
        )
        return "\n\n".join(sections).strip() + "\n"

    @staticmethod
    def _sync_avatar(card: NormalizedCard, char_dir: Path) -> Optional[Path]:
        if card.source_format != "png":
            return None
        avatar_path = char_dir / "avatar.png"
        shutil.copy2(card.source_path, avatar_path)
        return avatar_path

    def _require_manager(self) -> CharacterManager:
        if self._manager is None:
            raise RuntimeError("CharacterManager is not configured.")
        return self._manager

    def _require_importer(self) -> CardImporter:
        if self._card_importer is None:
            raise RuntimeError("CardImporter is not configured.")
        return self._card_importer
