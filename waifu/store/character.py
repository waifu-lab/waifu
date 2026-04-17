from pathlib import Path
from typing import List, Optional


class CharacterManager:
    """
    ```
    characters/
    └── {character_name}/
        ├── soul.md
        ├── avatar.{ext}
        └── live2d/
    ```
    """

    def __init__(self, characters_dir: Path) -> None:
        self._characters_dir = characters_dir

    def load_soul(self, character_name: str) -> Optional[str]:
        path = self._characters_dir / character_name / "soul.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_characters(self) -> List[str]:
        if not self._characters_dir.exists():
            return []
        return sorted(d.name for d in self._characters_dir.iterdir() if d.is_dir())

    def ensure_character_dir(self, character_name: str) -> Path:
        char_dir = self._characters_dir / character_name
        char_dir.mkdir(parents=True, exist_ok=True)
        (char_dir / "live2d").mkdir(exist_ok=True)
        return char_dir

    def get_avatar(self, character_name: str) -> Optional[Path]:
        char_dir = self._characters_dir / character_name
        for ext in ("png", "jpg", "jpeg", "webp"):
            path = char_dir / f"avatar.{ext}"
            if path.exists():
                return path
        return None
