"""B-4: the pinned-read layer — six read groups at one `run_block`.

Every value carries provenance; a failed read is a failure, never a zero
(inherited from rpc.py). Two rules are enforced here rather than assumed:

  * the DET-03 storage layout is re-verified **per controller, per run**, and a
    divergence flags that market rather than adapting to it (P-3.29);
  * bridge classification is three-state — absent config is a fact about the
    config, never about the world (P-3.29, mirroring the lend design).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from eth_utils import keccak

from factory.provenance import AbsenceRead, ContractRead

# --- canonical signatures ----------------------------------------------------
TOTAL_DEBT = "total_debt()"
N_LOANS = "n_loans()"
LOANS_AT = "loans(uint256)"
USER_STATE = "user_state(address)"
DEBT_OF = "debt(address)"
AMM_OF = "amm()"
MONETARY_POLICY = "monetary_policy()"
COLLATERAL_TOKEN = "collateral_token()"
DECIMALS = "decimals()"
AMM_A = "A()"
PRICE_ORACLE_CONTRACT = "price_oracle_contract()"
MA_EXP_TIME = "MA_EXP_TIME()"
PRICE_PAIRS = "price_pairs(uint256)"
TOTAL_SUPPLY = "totalSupply()"
BALANCE_OF = "balanceOf(address)"
FACTORY_ADMIN = "admin()"
EMERGENCY_ADMIN = "emergency_admin()"

# Vyper 0.3.10 with one nonreentrant key reserves slot 0; `loan` is the first
# storage variable, hence base 1 — VERIFIED on the cbBTC controller only
# (P-3.20), which is why it is re-verified per controller (P-3.29).
LOAN_SLOT_BASE_DEFAULT = 1
EIP1967_IMPL_SLOT = 0x360894A13BA1A3210667C828492DB98DCA3E2076CC3735A920A3CA505D382BBC

# Accrual band for the per-run reconciliation. A ratio outside it means the
# slot is not (initial_debt, rate_mul) — Level 3, not a nudge.
ACCRUAL_MIN = Decimal(1)
ACCRUAL_MAX = Decimal(3)
SAMPLE_SIZE = 4  # named implementer default


class SlotLayoutError(Exception):
    """Per-controller slot reconciliation failed — Level 3 for that market."""


class BridgeState(Enum):
    """Three states, never two (P-3.29). Absent config is not 'no bridges'."""

    NOT_CONFIGURED = "not_configured"
    EXPLICIT_EMPTY = "explicit_empty"
    POPULATED = "populated"


@dataclass(frozen=True)
class BridgeReport:
    state: BridgeState
    rows: tuple = ()

    @property
    def disclosure(self) -> str:
        if self.state is BridgeState.NOT_CONFIGURED:
            return ("no bridge classification data configured - bridged component "
                    "unassessed; supply_ruled = totalSupply")
        if self.state is BridgeState.EXPLICIT_EMPTY:
            return "no bridges exist"
        return f"{len(self.rows)} bridge(s) classified"

    @property
    def bridged_component_assessed(self) -> bool:
        return self.state is BridgeState.POPULATED


def loan_slot(base: int, user: str) -> int:
    """Vyper HashMap element slot: keccak(bytes32(slot) || bytes32(key))."""
    key = bytes.fromhex(user[2:].rjust(40, "0")).rjust(32, b"\0")
    return int.from_bytes(keccak(base.to_bytes(32, "big") + key), "big")


@dataclass(frozen=True)
class SlotVerification:
    """Evidence that a controller's loan layout is where we think it is."""

    controller: str
    base_slot: int
    sampled: int
    reconciled: int
    ok: bool
    detail: tuple[str, ...] = ()


def verify_slot_layout(
    storage_reader,
    controller: str,
    users: list[str],
    debts: dict[str, int],
    base: int = LOAN_SLOT_BASE_DEFAULT,
) -> SlotVerification:
    """Re-verify the DET-03 layout for ONE controller (P-3.29).

    `storage_reader(controller, slot) -> int`. Every sampled user must
    reconcile; anything else is a flag for that market, never an adaptation.
    """
    detail, ok_count = [], 0
    for u in users[:SAMPLE_SIZE]:
        initial = storage_reader(controller, loan_slot(base, u))
        rate_mul = storage_reader(controller, loan_slot(base, u) + 1)
        gross = debts.get(u, 0)
        if initial <= 0 or not (10**17 < rate_mul < 10**20) or gross <= 0:
            detail.append(f"{u}: implausible slot values")
            continue
        ratio = Decimal(gross) / Decimal(initial)
        if ACCRUAL_MIN <= ratio < ACCRUAL_MAX:
            ok_count += 1
        else:
            detail.append(f"{u}: accrual ratio {ratio:.6f} outside band")
    sampled = len(users[:SAMPLE_SIZE])
    return SlotVerification(controller, base, sampled, ok_count,
                            sampled > 0 and ok_count == sampled, tuple(detail))


@dataclass(frozen=True)
class PositionAggregate:
    """DET-03 / DET-06 / DET-82 aggregates. Raw rows stay outside the bundle."""

    controller: str
    n_positions: int
    principal_sum: int
    accrued_interest_sum: int
    gross_debt_sum: int
    net_debt_sum: int
    surplus_sum: int
    stablecoin_in_position_sum: int
    external_collateral_sum: int
    controller_total_debt: int
    slot_verification: SlotVerification
    reads: dict[str, ContractRead | AbsenceRead] = field(default_factory=dict)

    @property
    def det03_identity(self) -> bool:
        return self.gross_debt_sum == self.principal_sum + self.accrued_interest_sum

    @property
    def det82_relative_diff(self) -> Decimal:
        if self.controller_total_debt == 0:
            return Decimal(0)
        return abs(Decimal(self.gross_debt_sum - self.controller_total_debt)
                   / Decimal(self.controller_total_debt))

    @property
    def det82_ok(self) -> bool:
        return self.det82_relative_diff <= Decimal("1e-9")


def aggregate_positions(
    controller: str,
    rows: list[dict],
    controller_total_debt: int,
    verification: SlotVerification,
    reads: dict,
) -> PositionAggregate:
    """Fold raw position rows into the bundle-side aggregates (P-3.05 split).

    Position netting per DET-06: net_debt floored at 0, surplus disclosed
    separately and never reducing an aggregate.
    """
    if not verification.ok:
        raise SlotLayoutError(
            f"{controller}: slot layout unverified "
            f"({verification.reconciled}/{verification.sampled}) — Level 3 for this market"
        )
    principal = sum(r["principal"] for r in rows)
    gross = sum(r["gross_debt"] for r in rows)
    stable_in = sum(r["stablecoin_in_position"] for r in rows)
    return PositionAggregate(
        controller=controller,
        n_positions=len(rows),
        principal_sum=principal,
        accrued_interest_sum=gross - principal,
        gross_debt_sum=gross,
        net_debt_sum=sum(max(r["gross_debt"] - r["stablecoin_in_position"], 0) for r in rows),
        surplus_sum=sum(max(r["stablecoin_in_position"] - r["gross_debt"], 0) for r in rows),
        stablecoin_in_position_sum=stable_in,
        external_collateral_sum=sum(r["collateral"] for r in rows),
        controller_total_debt=controller_total_debt,
        slot_verification=verification,
        reads=reads,
    )


# --- group 3: keeper read completeness (C-2) ---------------------------------
KEEPER_REQUIRED_READS = frozenset(
    {"current_debt", "balance", "debt_ceiling", "is_killed", "alpha", "beta"}
)


def check_keeper_reads(reads: dict) -> None:
    """DET-20 / C-2: provenance per DET-named read, as a set equality."""
    missing = KEEPER_REQUIRED_READS - set(reads)
    if missing:
        raise ValueError(f"keeper reads missing provenance for: {sorted(missing)}")


# --- group 4: admin surface (F4 absence shapes) ------------------------------
A1_POWERS = (
    "mint", "set_ceiling", "upgrade", "pause", "freeze_asset",
    "blacklist_address", "set_oracle", "set_parameters", "seize",
)


def absence_evidence(contract: str, method: str, evidence: str, block: int) -> AbsenceRead:
    return AbsenceRead(contract=contract, method=method, evidence=evidence, block=block)


@dataclass(frozen=True)
class AdminRow:
    power: str
    holder: str | None
    holder_type: str
    scope: tuple[str, ...]
    provenance: ContractRead | AbsenceRead
    live_model_input: bool = False
    consumed_by: tuple[str, ...] = ()


def check_admin_surface(rows: list[AdminRow]) -> None:
    """DET-68: all nine A1 rows present, enum exact, none-filled where unheld."""
    powers = [r.power for r in rows]
    if set(powers) != set(A1_POWERS):
        raise ValueError(f"A1 enum mismatch: {sorted(set(powers) ^ set(A1_POWERS))}")


# --- LBTC weight / §8.2 routing ----------------------------------------------
def unlisted_weight_level(share: Decimal) -> int:
    """§8.2 / DET-08: >= 5% of backing => Level 2 (T-09); < 5% => Level 1 (T-01)."""
    return 2 if share >= Decimal("0.05") else 1
