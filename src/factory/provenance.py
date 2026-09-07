"""Provenance primitives, pulled forward from B-5's schema.

Only the three provenance shapes and the lineage enum land here — rpc.py cannot
emit provenance without them. The rest of the common schema arrives at B-5.
Shapes ruled at P-3.08; `storage_slot_read` added by P-3.07 ruling (i) branch 2.
"""

from __future__ import annotations

import datetime as _dt
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Address = Annotated[str, StringConstraints(pattern=r"^0x[0-9a-f]{40}$")]  # DET-01, lowercase


class ContractRead(BaseModel):
    """A value read from a contract at the run's pinned block (DET-04, R-13)."""

    kind: Literal["contract_read"] = "contract_read"
    source_contract: Address
    function: str  # canonical signature, e.g. "debt_ceiling(address)"
    args: list[str] = []
    block: int  # always header.run_block


class AnalystSupplied(BaseModel):
    """A staleness-tracked analyst input (DET-04 permitted form; DET-74 class I)."""

    kind: Literal["analyst_supplied"] = "analyst_supplied"
    source: str
    date: _dt.date  # > 92 d => T-16 (R-1)


class AbsenceRead(BaseModel):
    """Evidence that something is *not* there (F4, P-3.06; DET-71 precedent)."""

    kind: Literal["absence_read"] = "absence_read"
    contract: Address
    function: None = None
    method: Literal["selector_absence_scan", "eip1967_slot_read", "storage_slot_read"]
    evidence: str  # code_hash | slot_value
    block: int


Provenance = Annotated[
    ContractRead | AnalystSupplied | AbsenceRead, Field(discriminator="kind")
]

Lineage = Literal[
    "collateral_read",
    "debt_read",
    "price_read",
    "position_netting",
    "attribution",
    "sell_side_parameter",
    "depth_model",
    "gsm_read",
    "supply_attribution",
    "gsm_supply",
    "liquidation_model",
    # prefixes below carry R-15's positive-membership exclusions
    "stabilizer_lp",
    "stabilizer_debt",
    "offvenue_llama",
    "reference_price",
]
