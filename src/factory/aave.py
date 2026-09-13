"""B-5: GHO's liquidation inputs — Aave's own per-reserve risk parameters.

PURE where it can be, reading where it must. GHO has no AMM and no bands: a
position is liquidated when its health factor falls below 1 against the
liquidation threshold Aave itself publishes, so the model reads those
thresholds rather than inventing one (P-6.01 R12).

TWO THINGS THE SHAPE FORCES, both named rather than assumed:

  * THE HEALTH FACTOR IS THE WHOLE POSITION'S, not GHO's slice. A borrower
    with GHO and USDC debt against WETH is liquidated on the whole position or
    not at all, and Aave computes that over ALL collateral and ALL debt. So
    eligibility is computed on the full position, and the RESULT is attributed
    to GHO pro-rata by `gho_debt_base / total_debt_base` — memo §11.1's own
    rule, applied to the outcome rather than to the inputs.
  * TAIL RESERVES ARE IN SOLVENCY AND OUT OF ABSORPTION (R-B5.1). 15 of the
    34 reserves appearing in positions carry no §4 node — the
    `unlabeled_by_threshold` set, 1.549% of attributed weight, left unlabeled
    FOR THE TREE at freeze time for reasons unrelated to solvency. Aave prices
    them, lends against them and does not liquidate on their account, so they
    enter the health factor at that instance's oracle. They never enter
    `collateral_sellable`: we hold no sell-side bound for them. The first cut
    excluded them from health too, which called 65 positions insolvent at base
    and would have booked ~$9M of phantom GHO bad debt in EVERY cell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from factory.rpc import Call

RAY = 10 ** 27
BPS = 10 ** 4                       # Aave publishes LT and bonus in bps
TAIL_LITERAL = (
    "tail reserves (15, 1.549% of attributed weight, unlabeled by threshold) "
    "enter position health at Aave's oracle and are excluded from absorption; "
    "in Member 1 they are shocked as volatile, no LST axis - overstates bad "
    "debt where a tail reserve is a stable."
)
HF_LITERAL = (
    "eligibility is the WHOLE position's Aave health factor over all "
    "collateral and all debt - a borrower is liquidated entire or not at all - "
    "and the resulting bad debt is attributed to GHO pro-rata by "
    "`gho_debt_base / total_debt_base` (memo 11.1)."
)


@dataclass(frozen=True)
class Reserve:
    """One (instance, reserve) pair's published risk parameters."""

    instance: str
    asset: str
    ltv: int                        # bps
    liquidation_threshold: int      # bps
    liquidation_bonus: int          # bps, 10000 + the bonus
    price: int                      # AaveOracle, 8 dp, per instance


@dataclass(frozen=True)
class GhoPos:
    borrower: str
    instance: str
    collateral: dict[str, int]      # reserve -> amount in the reserve's units
    gho_debt_base: int
    total_debt_base: int
    emode: int = 0
    _v: dict = field(default_factory=dict, compare=False)

    @property
    def gho_share(self) -> Decimal:
        """Memo §11.1's pro-rata attribution."""
        return (Decimal(self.gho_debt_base) / Decimal(self.total_debt_base)
                if self.total_debt_base else Decimal(0))


def read_reserve_params(rpc, provider: str, pairs: list[tuple[str, str]],
                        oracle_of: dict[str, str], reads: dict) -> dict:
    """`getReserveConfigurationData` per (instance, reserve), plus the price.

    The provider is per instance; the price comes from that instance's own
    AaveOracle, which is DET-81's rule and P-6.01 R12's price basis.
    """
    out: dict[tuple[str, str], Reserve] = {}
    for inst, asset in pairs:
        prov = provider[inst] if isinstance(provider, dict) else provider
        r = rpc.read([Call(prov, "getReserveConfigurationData(address)",
                           ("uint256", "uint256", "uint256", "uint256", "uint256",
                            "bool", "bool", "bool", "bool", "bool"), (asset,))])[0]
        if not r.ok:
            raise AaveError(f"{inst}/{asset}: getReserveConfigurationData reverted")
        v = r.require()
        p = rpc.read([Call(oracle_of[inst], "getAssetPrice(address)", ("uint256",),
                           (asset,))])[0]
        out[(inst, asset)] = Reserve(
            instance=inst, asset=asset, ltv=int(v[1]),
            liquidation_threshold=int(v[2]), liquidation_bonus=int(v[3]),
            price=int(p.one()) if p.ok else 0)
        reads[f"{inst}.getReserveConfigurationData({asset[:10]})"] = r.provenance
        reads[f"{oracle_of[inst]}.getAssetPrice({asset[:10]})"] = p.provenance
    return out


class AaveError(Exception):
    """A risk parameter the model cannot proceed without."""


def health(p: GhoPos, params: dict, prices: dict, factor: dict[str, Decimal],
           emode_lt: dict[tuple[str, int], int], nodes: set[str]
           ) -> tuple[int, int, Decimal]:
    """`(collateral_base, weighted_threshold_base, health_factor)`.

    Aave's own arithmetic over ALL the position's collateral (R-B5.1): the
    threshold is the COLLATERAL-WEIGHTED average of each reserve's liquidation
    threshold, and the health factor is that weighted collateral over the debt.
    An eMode category, where the position has one, replaces the per-reserve
    threshold with the category's. `nodes` is no longer a filter here — it is
    passed so the caller can still separate node from tail collateral for
    ABSORPTION, which is a different question.
    """
    total, weighted = 0, 0
    for asset, amount in p.collateral.items():
        res = params.get((p.instance, asset))
        if res is None:
            raise AaveError(f"{p.instance}/{asset}: no risk parameters read")
        val = int(Decimal(amount) * Decimal(res.price)
                  * factor.get(asset, Decimal(1))
                  / Decimal(10 ** prices[asset]))
        lt = emode_lt.get((p.instance, p.emode), res.liquidation_threshold)
        total += val
        weighted += val * lt // BPS
    hf = (Decimal(weighted) / Decimal(p.total_debt_base)
          if p.total_debt_base else Decimal(0))
    return total, weighted, hf
