"""Evolutionary Adversarial Multi-Agent System."""

from .adversary import ProgressiveAdversary
from .backends import MockLLMBackend, OpenAICompatibleAsyncBackend
from .competition import CompetitionTrainer
from .ledger import KnowledgeLedger
from .manager import BatchManager, ManagerConfig

__all__ = [
    "BatchManager",
    "CompetitionTrainer",
    "KnowledgeLedger",
    "ManagerConfig",
    "MockLLMBackend",
    "OpenAICompatibleAsyncBackend",
    "ProgressiveAdversary",
]
