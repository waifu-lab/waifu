from typing import List, Optional

from waifu.store.models import Character, Relationship


class CharacterRepository:
    def create(
        self,
        name: str,
        soul_path: str,
        avatar_path: Optional[str] = None,
        live2d_dir: Optional[str] = None,
    ) -> Character:
        return Character.create(name=name, soul_path=soul_path, avatar_path=avatar_path, live2d_dir=live2d_dir)

    def get(self, id: str) -> Optional[Character]:
        return Character.get_or_none(Character.id == id)

    def get_active(self) -> Optional[Character]:
        return Character.get_or_none(Character.active == True)  # noqa: E712

    def set_active(self, id: str) -> None:
        Character.update(active=False).execute()  # deactivate all
        Character.update(active=True).where(Character.id == id).execute()

    def update(self, id: str, **fields) -> None:
        Character.update(**fields).where(Character.id == id).execute()

    def delete(self, id: str) -> None:
        Character.delete().where(Character.id == id).execute()

    def list_all(self) -> List[Character]:
        return list(Character.select())


class RelationshipRepository:
    def get_or_create(self, character_id: str, user_id: str, display_name: str) -> Relationship:
        obj, _ = Relationship.get_or_create(
            character_id=character_id,
            user_id=user_id,
            defaults={"display_name": display_name},
        )
        return obj

    def update(self, character_id: str, user_id: str, **fields) -> None:
        Relationship.update(**fields).where(
            Relationship.character_id == character_id,
            Relationship.user_id == user_id,
        ).execute()

    def get(self, character_id: str, user_id: str) -> Optional[Relationship]:
        return Relationship.get_or_none(
            Relationship.character_id == character_id,
            Relationship.user_id == user_id,
        )

    def list_by_character(self, character_id: str) -> List[Relationship]:
        return list(Relationship.select().where(Relationship.character_id == character_id))
