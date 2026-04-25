"""Compatibility tombstone for removed Ollama support."""

REMOVAL_MESSAGE = (
    "Ollama has been retired and is no longer supported in public GlyphOS AI Compute. "
    "Use the local llama.cpp runtime via the GLYPHOS_LLAMACPP_* configuration instead."
)


class OllamaClient:
    def __init__(self, *args, **kwargs):
        raise RuntimeError(REMOVAL_MESSAGE)


def create_ollama_client(*args, **kwargs):
    raise RuntimeError(REMOVAL_MESSAGE)
