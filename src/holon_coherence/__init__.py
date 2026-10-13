"""Holon Coherence: High-coherence, low-entropy optimization gateway for fractal coding agents.

Core stable primitives:
- HybridCacheStore: Multi-tiered hybrid cache layer.
- JSONContextCleaner: Redundant context cleaning and payload optimization.
- MITMProxyInterceptor: Streaming proxy interceptor for model requests.
- generate_root_ca: Local CA authority generation.

Experimental Phase 4 modules:
- OpenBrainMemory: Cross-session persistent vector memory.
- RAGCodebaseIndexer: AST-aware codebase indexer.
- RingerOrchestrator: Architect/Executor subagent orchestration.
"""

from holon_coherence.ca_generator import generate_root_ca
from holon_coherence.hybrid_cache import HybridCacheStore
from holon_coherence.mitm_addon import MITMProxyInterceptor
from holon_coherence.openbrain_memory import OpenBrainMemory
from holon_coherence.payload_cleaner import JSONContextCleaner
from holon_coherence.rag_indexer import RAGCodebaseIndexer
from holon_coherence.ringer_orchestrator import RingerOrchestrator

# Core stable primitives
__core__ = [
    "HybridCacheStore",
    "JSONContextCleaner",
    "MITMProxyInterceptor",
    "generate_root_ca",
]

# Experimental Phase 4 modules
__experimental__ = [
    "OpenBrainMemory",
    "RAGCodebaseIndexer",
    "RingerOrchestrator",
]

__all__ = [
    "HybridCacheStore",
    "JSONContextCleaner",
    "MITMProxyInterceptor",
    "OpenBrainMemory",
    "RAGCodebaseIndexer",
    "RingerOrchestrator",
    "__core__",
    "__experimental__",
    "generate_root_ca",
]
