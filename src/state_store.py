"""Persistence for last successful run timestamp."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Optional


@dataclass
class StateStore:
    path: Path

    def read_last_run(self) -> Optional[str]:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data.get("last_run")

    def write_last_run(self, iso_timestamp: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_run": iso_timestamp}
        content = json.dumps(payload, ensure_ascii=True, indent=2)
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            # Replace in one filesystem operation so a partial write cannot
            # leave last_run.json empty or malformed if the process is stopped.
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def write_now(self) -> str:
        now = datetime.now(timezone.utc).isoformat()
        self.write_last_run(now)
        return now
