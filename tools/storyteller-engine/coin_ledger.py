"""
coin_ledger.py
~~~~~~~~~~~~~~
Enforces IBM Bob 40-Coin Budget Funnel with a persistent ledger, strict 40-coin
cap, and 0-coin policy enforcement for bug fixing and automated exploration.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

MAX_COINS_DEFAULT = 40
LEDGER_REL_PATH = Path(".agents") / "coin_budget_ledger.json"

BUG_FIX_KEYWORDS = (
    "fix bug",
    "bugfix",
    "bug fix",
    "fix syntax",
    "syntax error",
    "fix error",
    "fix import",
    "fix lint",
    "patch error",
    "debug error",
    "debug bug",
)

EXPLORATION_KEYWORDS = (
    "explore codebase",
    "codebase exploration",
    "automated exploration",
    "scan files",
    "survey codebase",
)


class CoinBudgetExceededError(ValueError):
    """Raised when coin usage would exceed the 40-coin budget."""


class CoinPolicyViolationError(ValueError):
    """Raised when an operation violates the 0-coin policy (bug fixing/exploration)."""


class CoinBudgetManager:
    """Manages and records coin usage under a strict 40-coin ceiling."""

    def __init__(
        self,
        workspace_root: Optional[Path | str] = None,
        ledger_file: Optional[Path | str] = None,
        max_coins: int = MAX_COINS_DEFAULT,
    ) -> None:
        self.max_coins = max_coins
        self._lock = threading.RLock()

        if workspace_root:
            self.workspace_root = Path(workspace_root).resolve()
        else:
            # Walk up from this file to find workspace root
            curr = Path(__file__).resolve().parent
            while curr != curr.parent:
                if (curr / ".agents").is_dir() or (curr / ".git").is_dir():
                    break
                curr = curr.parent
            self.workspace_root = curr

        if ledger_file:
            self.ledger_file = Path(ledger_file).resolve()
        else:
            self.ledger_file = (self.workspace_root / LEDGER_REL_PATH).resolve()

        self._load()

    def _load(self) -> None:
        with self._lock:
            if self.ledger_file.is_file():
                try:
                    data = json.loads(self.ledger_file.read_text(encoding="utf-8"))
                    self.coins_spent = int(data.get("coins_spent", 0))
                    self.history = list(data.get("transactions", []))
                    return
                except Exception:
                    pass
            self.coins_spent = 0
            self.history = []

    def _save(self) -> None:
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "max_coins": self.max_coins,
            "coins_spent": self.coins_spent,
            "coins_remaining": max(0, self.max_coins - self.coins_spent),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "transactions": self.history,
        }
        # Atomic write
        temp_file = self.ledger_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_file.replace(self.ledger_file)

    @property
    def total_spent(self) -> int:
        with self._lock:
            return self.coins_spent

    @property
    def remaining_coins(self) -> int:
        with self._lock:
            return max(0, self.max_coins - self.coins_spent)

    @staticmethod
    def check_policy(prompt: str = "", purpose: str = "") -> tuple[bool, str]:
        """Verify request does not violate the 0-coin policy."""
        combined = f"{prompt} {purpose}".lower()

        for kw in BUG_FIX_KEYWORDS:
            if kw in combined:
                return (
                    False,
                    f"0-coin policy: '{kw}' detected. Bug fixing must be patched on disk for 0 coins.",
                )

        for kw in EXPLORATION_KEYWORDS:
            if kw in combined:
                return (
                    False,
                    f"0-coin policy: '{kw}' detected. Codebase exploration must be conducted for 0 coins via Antigravity.",
                )

        return True, "Approved"

    def can_spend(self, prompt: str = "", purpose: str = "", cost: int = 1) -> tuple[bool, str]:
        """Check if spending `cost` coins is allowed under budget and policy."""
        if cost < 0:
            return False, "Cost cannot be negative."

        policy_ok, reason = self.check_policy(prompt, purpose)
        if not policy_ok:
            return False, reason

        with self._lock:
            if self.coins_spent + cost > self.max_coins:
                return (
                    False,
                    f"Budget exceeded: {self.coins_spent} coins spent; {cost} requested; "
                    f"limit is {self.max_coins} ({max(0, self.max_coins - self.coins_spent)} remaining).",
                )

        return True, "Approved"

    def record_transaction(
        self,
        prompt: str = "",
        purpose: str = "execution",
        coins: int = 1,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Record a coin transaction. Raises error if budget or policy is violated."""
        policy_ok, policy_reason = self.check_policy(prompt, purpose)
        if not policy_ok:
            raise CoinPolicyViolationError(policy_reason)

        with self._lock:
            if self.coins_spent + coins > self.max_coins:
                raise CoinBudgetExceededError(
                    f"Budget cap reached: cannot spend {coins} coin(s). "
                    f"Spent: {self.coins_spent}/{self.max_coins}."
                )

            self.coins_spent += coins
            tx = {
                "id": f"tx_{len(self.history) + 1:04d}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "purpose": purpose,
                "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16] if prompt else "",
                "prompt_preview": prompt[:120].strip() if prompt else "",
                "coins": coins,
                "total_spent": self.coins_spent,
                "coins_remaining": max(0, self.max_coins - self.coins_spent),
                "metadata": metadata or {},
            }
            self.history.append(tx)
            self._save()
            return tx

    def get_ledger(self) -> dict[str, Any]:
        """Return the current ledger snapshot."""
        with self._lock:
            return {
                "max_coins": self.max_coins,
                "coins_spent": self.coins_spent,
                "coins_remaining": max(0, self.max_coins - self.coins_spent),
                "transactions": list(self.history),
            }

    def reset(self) -> None:
        """Reset the ledger to 0 spent (for testing)."""
        with self._lock:
            self.coins_spent = 0
            self.history = []
            self._save()
