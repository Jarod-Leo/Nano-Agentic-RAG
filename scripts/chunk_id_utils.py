import re


_CHUNK_ID_RE = re.compile(r"^(?P<prefix>.+)_(?P<index>\d{4})$")


def get_doc_prefix(chunk_id: str) -> str:
    match = _CHUNK_ID_RE.match(chunk_id)
    if not match:
        raise ValueError(f"Invalid chunk_id: {chunk_id!r}")
    return match.group("prefix")
