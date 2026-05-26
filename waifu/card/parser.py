from __future__ import annotations

import base64
import hashlib
import json
import struct
import zipfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUPPORTED_SUFFIXES = {".png", ".json", ".yml", ".yaml", ".charx"}


class CardError(Exception):
    pass


class UnsupportedFormatError(CardError):
    pass


class CardParseError(CardError):
    pass


class NormalizedCard(BaseModel):
    source_path: Path
    source_format: Literal["png", "json", "yaml", "charx"]
    spec: str
    spec_version: str | None = None

    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""

    creator_notes: str = ""
    system_prompt: str = ""
    post_history_instructions: str = ""
    alternate_greetings: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    creator: str = ""
    character_version: str = ""

    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            return [x.strip() for x in value.split(",") if x.strip()]
        return [str(value).strip()]

    @field_validator("alternate_greetings", mode="before")
    @classmethod
    def normalize_alt_greetings(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value]
        if isinstance(value, str):
            return [value]
        return [str(value)]


class CardParser:
    def load(self, path: str | Path) -> NormalizedCard:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"File not found: {p}")
        raw, source_format = self._load_raw(p)
        card = self._normalize(raw, p, source_format)
        if not card.name:
            raise CardParseError("Card is missing a character name.")
        return card

    def fingerprint(self, card: NormalizedCard) -> str:
        payload = {
            "spec": card.spec,
            "spec_version": card.spec_version,
            "name": card.name,
            "description": card.description,
            "personality": card.personality,
            "scenario": card.scenario,
            "first_mes": card.first_mes,
            "mes_example": card.mes_example,
            "creator_notes": card.creator_notes,
            "system_prompt": card.system_prompt,
            "post_history_instructions": card.post_history_instructions,
            "alternate_greetings": card.alternate_greetings,
            "tags": card.tags,
            "creator": card.creator,
            "character_version": card.character_version,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_raw(self, path: Path) -> tuple[dict[str, Any], str]:
        suffix = path.suffix.lower()

        if suffix == ".png":
            payload = self._extract_png_payload(path)
            try:
                return json.loads(payload), "png"
            except json.JSONDecodeError as exc:
                raise CardParseError(f"Failed to parse embedded JSON in PNG: {exc}") from exc

        if suffix == ".json":
            try:
                return json.loads(path.read_text(encoding="utf-8")), "json"
            except json.JSONDecodeError as exc:
                raise CardParseError(f"Failed to parse JSON: {exc}") from exc

        if suffix in {".yml", ".yaml"}:
            try:
                obj = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise CardParseError(f"Failed to parse YAML: {exc}") from exc
            if not isinstance(obj, dict):
                raise CardParseError("YAML root must be a mapping/object.")
            return obj, "yaml"

        if suffix == ".charx":
            return self._extract_charx_payload(path), "charx"

        raise UnsupportedFormatError(f"Unsupported file extension: {suffix}")

    @staticmethod
    def _iter_png_chunks(data: bytes):
        if not data.startswith(PNG_SIGNATURE):
            raise CardParseError("Not a valid PNG file.")
        i = len(PNG_SIGNATURE)
        data_len = len(data)
        while i + 12 <= data_len:
            length = struct.unpack(">I", data[i : i + 4])[0]
            i += 4
            chunk_type = data[i : i + 4].decode("latin-1")
            i += 4
            chunk_data = data[i : i + length]
            i += length
            i += 4  # skip CRC
            yield chunk_type, chunk_data
            if chunk_type == "IEND":
                break

    def _extract_png_payload(self, path: Path) -> str:
        data = path.read_bytes()
        text_chunks: dict[str, str] = {}

        for chunk_type, chunk_data in self._iter_png_chunks(data):
            if chunk_type != "tEXt":
                continue
            if b"\x00" not in chunk_data:
                continue
            keyword, text = chunk_data.split(b"\x00", 1)
            key = keyword.decode("latin-1", errors="ignore").lower().strip()
            text_chunks[key] = text.decode("latin-1", errors="ignore")

        for key in ("ccv3", "chara"):
            if key in text_chunks:
                try:
                    return base64.b64decode(text_chunks[key]).decode("utf-8")
                except Exception as exc:
                    raise CardParseError(f"Failed to decode PNG metadata Base64/UTF-8: {exc}") from exc

        raise CardParseError("No ccv3 or chara tEXt chunk found in PNG.")

    @staticmethod
    def _extract_charx_payload(path: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                raw = zf.read("card.json")
        except KeyError as exc:
            raise CardParseError("card.json not found in CHARX archive.") from exc
        except zipfile.BadZipFile as exc:
            raise CardParseError("Not a valid CHARX/ZIP file.") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise CardParseError(f"Failed to parse CHARX card.json: {exc}") from exc

    @staticmethod
    def _normalize(raw: dict[str, Any], source_path: Path, source_format: str) -> NormalizedCard:
        spec = raw.get("spec")
        data = raw.get("data", {}) if isinstance(raw.get("data"), dict) else {}

        if spec in {"chara_card_v2", "chara_card_v3"} and data:
            return NormalizedCard(
                source_path=source_path,
                source_format=source_format,  # type: ignore[arg-type]
                spec=spec,
                spec_version=str(raw.get("spec_version")) if raw.get("spec_version") is not None else None,
                name=str(data.get("name", raw.get("name", ""))).strip(),
                description=str(data.get("description", "")),
                personality=str(data.get("personality", "")),
                scenario=str(data.get("scenario", "")),
                first_mes=str(data.get("first_mes", "")),
                mes_example=str(data.get("mes_example", "")),
                creator_notes=str(data.get("creator_notes", "")),
                system_prompt=str(data.get("system_prompt", "")),
                post_history_instructions=str(data.get("post_history_instructions", "")),
                alternate_greetings=data.get("alternate_greetings", []),
                tags=data.get("tags", []),
                creator=str(data.get("creator", "")),
                character_version=str(data.get("character_version", "")),
                raw=raw,
            )

        if "name" in raw and "first_mes" in raw:
            return NormalizedCard(
                source_path=source_path,
                source_format=source_format,  # type: ignore[arg-type]
                spec="tavern_card_v1",
                spec_version=None,
                name=str(raw.get("name", "")).strip(),
                description=str(raw.get("description", "")),
                personality=str(raw.get("personality", "")),
                scenario=str(raw.get("scenario", "")),
                first_mes=str(raw.get("first_mes", "")),
                mes_example=str(raw.get("mes_example", "")),
                creator_notes=str(raw.get("creatorcomment", raw.get("creator_notes", ""))),
                tags=raw.get("tags", []),
                creator=str(raw.get("creator", "")),
                raw=raw,
            )

        if "char_name" in raw:
            return NormalizedCard(
                source_path=source_path,
                source_format=source_format,  # type: ignore[arg-type]
                spec="pygmalion_gradio",
                spec_version=None,
                name=str(raw.get("char_name", "")).strip(),
                description=str(raw.get("char_persona", "")),
                personality="",
                scenario=str(raw.get("world_scenario", "")),
                first_mes=str(raw.get("char_greeting", "")),
                mes_example=str(raw.get("example_dialogue", "")),
                creator_notes=str(raw.get("creatorcomment", raw.get("creator_notes", ""))),
                tags=raw.get("tags", []),
                creator=str(raw.get("creator", "")),
                raw=raw,
            )

        if "name" in raw and ("context" in raw or "greeting" in raw):
            return NormalizedCard(
                source_path=source_path,
                source_format=source_format,  # type: ignore[arg-type]
                spec="yaml_interchange",
                spec_version=None,
                name=str(raw.get("name", "")).strip(),
                description=str(raw.get("context", "")),
                first_mes=str(raw.get("greeting", "")),
                raw=raw,
            )

        raise CardParseError("Unrecognized card data structure.")
