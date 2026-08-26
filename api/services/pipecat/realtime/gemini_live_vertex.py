"""SpinSci subclass of pipecat's Gemini Live Vertex AI LLM service.

Diamond inheritance: combines the SpinSci engine-integration overrides from
:class:`SpinSciGeminiLiveLLMService` with the Vertex-specific tweaks from
upstream's :class:`GeminiLiveVertexLLMService` (no history config,
``NON_BLOCKING`` tools disabled, service-account credentials).

MRO::

    SpinSciGeminiLiveVertexLLMService
      -> SpinSciGeminiLiveLLMService
      -> GeminiLiveVertexLLMService
      -> GeminiLiveLLMService
      -> LLMService
      -> ...
"""

from api.services.pipecat.realtime.gemini_live import SpinSciGeminiLiveLLMService
from pipecat.services.google.gemini_live.vertex.llm import (
    GeminiLiveVertexLLMService,
)


class SpinSciGeminiLiveVertexLLMService(
    SpinSciGeminiLiveLLMService,
    GeminiLiveVertexLLMService,
):
    """Vertex AI variant of Gemini Live with SpinSci integration quirks."""

    pass


# Guard against MRO regressions: a future refactor that flips inheritance
# order or breaks the diamond would silently bypass the SpinSci overrides.
_mro = SpinSciGeminiLiveVertexLLMService.__mro__
assert _mro[1] is SpinSciGeminiLiveLLMService, (
    f"Expected SpinSciGeminiLiveLLMService at MRO[1], got {_mro[1]}"
)
assert _mro[2] is GeminiLiveVertexLLMService, (
    f"Expected GeminiLiveVertexLLMService at MRO[2], got {_mro[2]}"
)
del _mro
