"""Curated fact packs: the source of truth for grounding lessons."""

import re
from pathlib import Path

import yaml

from lessonproof.schemas import FactPack

KNOWLEDGE_DIR = Path(__file__).parent


def find_curated_pack(topic: str) -> FactPack | None:
    for path in sorted(KNOWLEDGE_DIR.glob("*.yaml")):
        pack = FactPack.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if any(re.search(rf"\b{re.escape(a)}\b", topic, re.IGNORECASE) for a in pack.aliases):
            return pack
    return None
