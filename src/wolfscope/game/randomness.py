"""Stable namespaced random seeds for reproducible independent streams."""

import hashlib


def derive_seed(seed: int, namespace: str) -> int:
    payload = f"wolfscope:{seed}:{namespace}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
