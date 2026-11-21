"""Text embeddings for corpus search, computed locally (fastembed, ONNX): no key, no per-query
cost, and the text never leaves the server.

Model: `PRAWDOWID_EMBEDDING_MODEL`, default `intfloat/multilingual-e5-large` (MIT, 1024
dimensions, strong on Polish retrieval). Files are cached in `FASTEMBED_CACHE_PATH`.
"""

import logging
import os
import threading

import numpy as np
from fastembed import TextEmbedding

MODEL_ENV = "PRAWDOWID_EMBEDDING_MODEL"
DEFAULT_MODEL = "intfloat/multilingual-e5-large"
BATCH = 32

_lock = threading.Lock()
_model: TextEmbedding | None = None
_warming = threading.Event()


def model_name() -> str:
    return os.getenv(MODEL_ENV) or DEFAULT_MODEL


def _prefix(kind: str) -> str:
    """e5 models were trained with "query: " and "passage: " in front of the text."""
    return f"{kind}: " if "e5" in model_name().lower() else ""


def _get_model() -> TextEmbedding:
    global _model
    with _lock:  # one load, even when the first queries arrive together
        if _model is None:
            _model = TextEmbedding(
                model_name(), cache_dir=os.getenv("FASTEMBED_CACHE_PATH")
            )
        return _model


def is_ready() -> bool:
    return _model is not None


def warm_up() -> None:
    """Load the model in a background thread, once. Loading takes seconds (minutes when the
    files are not cached yet), so searches report "unavailable" until it is ready instead of
    waiting inside their deadline."""
    if _model is not None or _warming.is_set():
        return
    _warming.set()

    def load() -> None:
        try:
            _get_model()
        except Exception:
            logging.getLogger("prawdowid").exception("embedding model failed to load")
        finally:
            _warming.clear()

    threading.Thread(target=load, name="embedding-model", daemon=True).start()


def dimension() -> int:
    return len(embed_query("test"))


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    prefix = _prefix("passage")
    return list(_get_model().embed([prefix + t for t in texts], batch_size=BATCH))


def embed_query(text: str) -> np.ndarray:
    return next(iter(_get_model().embed([_prefix("query") + text])))
