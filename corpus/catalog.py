"""The source catalogue (`corpus/catalog.yaml`): the auditable list of sources and its rules."""

import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from corpus.schema import SourceType, registered_domain

CATALOG_PATH = Path(__file__).parent / "catalog.yaml"

# active: collected into docs.jsonl. live_only: queried at check time, nothing stored.
# candidate: fits the rules, not collected yet (the note says what is missing).
# excluded: not used; the entry stays in the list with the reason and the date.
Status = Literal["active", "live_only", "candidate", "excluded"]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    domain: str  # host we fetch from
    publisher: str
    source_type: SourceType
    licence: str
    licence_url: str | None = None  # where the licence or the terms are stated
    licence_checked: date | None = None  # when we last read them there
    storage: Literal["full_text", "excerpt", "none"]
    language: str = "pl"
    access: str  # how we get the content
    update_interval: str  # e.g. "24h"
    added: date
    status: Status
    note: str | None = None
    excluded_on: date | None = None
    excluded_reason: str | None = None
    collector: str | None = None
    requires_env: str | None = (
        None  # the collector is skipped while this variable is unset
    )
    params: dict[str, Any] = {}

    @model_validator(mode="after")
    def consistent(self) -> "Source":
        if self.status == "excluded" and not (
            self.excluded_on and self.excluded_reason
        ):
            raise ValueError(
                f"{self.id}: an excluded source needs excluded_on and excluded_reason"
            )
        if self.status in ("candidate", "live_only") and not self.note:
            raise ValueError(f"{self.id}: a {self.status} source needs a note")
        if self.status == "active" and not self.collector:
            raise ValueError(f"{self.id}: an active source needs a collector")
        if self.status == "active" and self.storage == "none":
            raise ValueError(
                f"{self.id}: an active source must store full_text or excerpt"
            )
        return self

    @property
    def registered_domain(self) -> str:
        return registered_domain(f"https://{self.domain}")

    @property
    def max_age(self) -> float | None:
        """`update_interval` in seconds ("6h", "7d"): how old a cached list, feed or API answer
        may be before a rebuild fetches it again. None when the entry has no interval."""
        if m := re.fullmatch(r"(\d+)([hd])", self.update_interval):
            return int(m.group(1)) * (3600 if m.group(2) == "h" else 86400)
        return None


class RemovedUrl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    reason: str
    removed_on: date


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: dict[str, list[str]]
    removed_urls: list[RemovedUrl] = []
    sources: list[Source]

    @model_validator(mode="after")
    def unique_ids(self) -> "Catalog":
        ids = [s.id for s in self.sources]
        if dupes := {i for i in ids if ids.count(i) > 1}:
            raise ValueError(f"duplicate source ids: {sorted(dupes)}")
        return self


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.pop("x-shared", None)  # YAML anchors reused by several entries
    return Catalog.model_validate(data)
