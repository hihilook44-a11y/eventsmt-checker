"""Encrypted source retention for compilations; never an audio or publish permission."""
from copy import deepcopy
from candidate_pipeline import _key
from automatic_audio import proofs as audio_proofs


def retain_reviewed_sources(snapshot):
    """Keep source metadata before a published Short leaves the discovery queue.

    The original signed proof and exact media fingerprint are independently checked
    by the assessor/renderer. This archive never modifies reviews or Shorts state.
    """
    archive = snapshot.setdefault('compilation_sources', {})
    if not isinstance(archive, dict):
        raise ValueError('invalid compilation source archive')
    reviews = audio_proofs(snapshot)
    prepared = snapshot.get('prepared_media', {})
    for item in snapshot.get('state', {}).get('pending', []):
        key = _key(item)
        if key in reviews and prepared.get(key, {}).get('sha256'):
            archive[key] = deepcopy(item)


def candidates(snapshot):
    """Merge archived reviewed source metadata with current candidates, once each."""
    archive = snapshot.get('compilation_sources', {})
    pending = snapshot.get('state', {}).get('pending')
    if not isinstance(archive, dict) or not isinstance(pending, list):
        raise ValueError('invalid compilation sources')
    by_key = {}
    for key, item in archive.items():
        if not isinstance(item, dict) or _key(item) != key:
            raise ValueError('invalid archived source identity')
        by_key[key] = item
    seen = set()
    for item in pending:
        if not isinstance(item, dict):
            raise ValueError('invalid pending source')
        key = _key(item)
        if key in seen:
            raise ValueError('duplicate candidate identity')
        seen.add(key)
        by_key[key] = item
    return list(by_key.values())
