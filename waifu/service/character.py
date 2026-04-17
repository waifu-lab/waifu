from typing import List, Optional

from waifu.store.models import Character, Relationship
from waifu.store.repositories.character import CharacterRepository, RelationshipRepository


class CharacterService:
    def __init__(self, char_repo: CharacterRepository, rel_repo: RelationshipRepository) -> None:
        self._chars = char_repo
        self._rels = rel_repo

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
