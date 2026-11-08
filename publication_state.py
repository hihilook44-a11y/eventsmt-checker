"""Fail-closed dedup transitions for a future publisher; IDs are stored only as hashes."""
import hashlib
import json
import os
import tempfile
from pathlib import Path


def _digest(source_id: str) -> str:
    if not source_id:
        raise ValueError('Source ID is required')
    return hashlib.sha256(source_id.encode('utf-8')).hexdigest()


class PublicationState:
    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        if not self.path.exists():
            return {'schema': 1, 'items': {}}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError('Publication state is unreadable') from exc
        if (not isinstance(data, dict) or data.get('schema') != 1
                or not isinstance(data.get('items'), dict)):
            raise ValueError('Publication state is invalid')
        for digest, status in data['items'].items():
            if (len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)
                    or status not in {'pending', 'published', 'failed', 'unknown'}):
                raise ValueError('Publication state is invalid')
        return data

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.publication-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, sort_keys=True, separators=(',', ':'))
                stream.write('\n')
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def claim(self, source_id: str) -> bool:
        """Claim a new/confirmed-failed item; pending/unknown/published never auto-retry."""
        data = self._load()
        digest = _digest(source_id)
        status = data['items'].get(digest)
        if status in {'pending', 'published', 'unknown'}:
            return False
        data['items'][digest] = 'pending'
        self._save(data)
        return True

    def record_outcome(self, source_id: str, outcome: str):
        """Only confirmed provider success is published; unknown stays blocked from retry."""
        if outcome not in {'published', 'failed', 'unknown'}:
            raise ValueError('Outcome must be published, failed, or unknown')
        data = self._load()
        digest = _digest(source_id)
        if data['items'].get(digest) != 'pending':
            raise ValueError('Source is not pending')
        data['items'][digest] = outcome
        self._save(data)
