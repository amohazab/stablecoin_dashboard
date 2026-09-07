"""crvUSD discovery: mint markets, PegKeepers, node-address confirmation.

Everything enumerable comes from a discovery root at `run_block` (memo §9).
No market, pool, collateral or stabilizer list appears as a literal here.
Outputs are lightweight dataclasses; B-5 maps them into the Pydantic schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from factory.config import Config
from factory.provenance import ContractRead
from factory.rpc import Call, ReadResult, RpcReadError

# --- canonical signatures -------------------------------------------------
N_COLLATERALS = "n_collaterals()"
CONTROLLERS = "controllers(uint256)"
AMMS = "amms(uint256)"
COLLATERALS = "collaterals(uint256)"
DEBT_CEILING = "debt_ceiling(address)"
FACTORY_ADMIN = "admin()"
MONETARY_POLICY = "monetary_policy()"
TOTAL_DEBT = "total_debt()"
N_LOANS = "n_loans()"
DECIMALS = "decimals()"
AMM_A = "A()"
PRICE_ORACLE_CONTRACT = "price_oracle_contract()"
MA_EXP_TIME = "MA_EXP_TIME()"
# peg_keepers is a Vyper DynArray public getter: an INDEXED accessor, not an
# array return, and the struct carries four members. Both facts were established
# at first contact (P-3.20); the zero-arg form reverts.
PEG_KEEPERS_AT = "peg_keepers(uint256)"
PK_INFO = ("address", "address", "bool", "bool")  # peg_keeper, pool, is_inverse, include_index
MAX_KEEPER_INDEX = 64  # runaway guard; the walk ends at the first revert
PK_DEBT = "debt()"
PK_POOL = "POOL()"
BALANCE_OF = "balanceOf(address)"
REG_ALPHA = "alpha()"
REG_BETA = "beta()"
REG_EMERGENCY_ADMIN = "emergency_admin()"
IS_KILLED = "is_killed()"


@dataclass(frozen=True)
class DiscoveredMarket:
    """One market from the controller factory. `origination_class` is assigned
    from the FACTORY ADDRESS in provenance, never from a symbol (DET-07)."""

    index: int
    controller: str
    amm: str
    collateral: str
    origination_class: str  # "mint" | "lend"
    origination_provenance: ContractRead
    discovery_provenance: ContractRead


@dataclass(frozen=True)
class DiscoveredKeeper:
    """One stabilizer operation (DET-20). Discovered from the regulator (P4)."""

    operation_address: str
    paired_pool_address: str
    debt_ceiling: int
    current_debt: int
    balance: int
    discovery_provenance: ContractRead
    reads: dict[str, ContractRead] = field(default_factory=dict)

    @property
    def utilization(self) -> Decimal | None:
        """DET-21 / R-11: None when the ceiling is 0; the 'n/a - ceiling 0'
        string is template-rendered, never stored in a numeric field (O-1)."""
        if self.debt_ceiling == 0:
            return None
        return Decimal(self.current_debt) / Decimal(self.debt_ceiling)

    @property
    def utilization_na_reason(self) -> str | None:
        return "ceiling_zero" if self.debt_ceiling == 0 else None


@dataclass(frozen=True)
class AddressReconciliation:
    """Node-address confirmation against on-chain collaterals (P-3.15)."""

    matched: tuple[str, ...]
    config_not_onchain: tuple[str, ...]
    onchain_not_in_config: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.config_not_onchain and not self.onchain_not_in_config


def _require_all(results: list[ReadResult]) -> list[tuple]:
    """Fail closed: one failed read stops the batch's consumers (P-3.16)."""
    for r in results:
        if not r.ok:
            raise RpcReadError(f"{r.call.target} {r.call.signature}: {r.error}")
    return [r.require() for r in results]


def discover_mint_markets(rpc, cfg: Config) -> list[DiscoveredMarket]:
    """Enumerate markets from the controller factory. Mint by construction:
    this root IS the mint-market factory, so `origination_class` derives from
    the address the enumeration came from (DET-07)."""
    cf = cfg.root("controller_factory")
    (count_row,) = _require_all(rpc.read([Call(cf.address, N_COLLATERALS, ("uint256",))]))
    n = int(count_row[0])

    calls: list[Call] = []
    for i in range(n):
        calls += [
            Call(cf.address, CONTROLLERS, ("address",), (i,)),
            Call(cf.address, AMMS, ("address",), (i,)),
            Call(cf.address, COLLATERALS, ("address",), (i,)),
        ]
    values = _require_all(rpc.read(calls))

    markets: list[DiscoveredMarket] = []
    seen: set[str] = set()
    for i in range(n):
        controller = values[3 * i][0].lower()
        amm = values[3 * i + 1][0].lower()
        collateral = values[3 * i + 2][0].lower()
        if controller in seen:  # DET-01: no duplicate address in a table
            raise ValueError(f"duplicate controller address at index {i}: {controller}")
        seen.add(controller)
        prov = ContractRead(
            source_contract=cf.address, function=CONTROLLERS, args=[str(i)], block=rpc.run_block
        )
        markets.append(
            DiscoveredMarket(
                index=i,
                controller=controller,
                amm=amm,
                collateral=collateral,
                # assignment source is the factory ADDRESS in provenance
                origination_class="mint" if prov.source_contract == cf.address else "lend",
                origination_provenance=prov,
                discovery_provenance=prov,
            )
        )
    return markets


def discover_pegkeepers(rpc, cfg: Config) -> list[DiscoveredKeeper]:
    """Read the live keeper set from the regulator — never a list (P4)."""
    reg = cfg.root("pegkeeper_regulator")
    cf = cfg.root("controller_factory")
    crvusd = cfg.root("crvusd_token")

    # Index-walk until the getter reverts; the revert IS the end of the array.
    keepers: list[tuple[str, str]] = []
    for i in range(MAX_KEEPER_INDEX):
        r = rpc.read([Call(reg.address, PEG_KEEPERS_AT, PK_INFO, (i,))])[0]
        if not r.ok:
            break
        pk_addr, pool_addr, _is_inverse, _include_index = r.require()
        keepers.append((pk_addr, pool_addr))
    else:
        raise RpcReadError(
            f"keeper enumeration did not terminate within {MAX_KEEPER_INDEX} indices"
        )

    out: list[DiscoveredKeeper] = []
    for pk_addr, pool_addr in keepers:
        pk = pk_addr.lower()
        calls = [
            Call(pk, PK_DEBT, ("uint256",)),
            Call(crvusd.address, BALANCE_OF, ("uint256",), (pk,)),
            Call(cf.address, DEBT_CEILING, ("uint256",), (pk,)),
        ]
        (debt,), (bal,), (ceiling,) = _require_all(rpc.read(calls))
        disc = ContractRead(
            source_contract=reg.address, function=PEG_KEEPERS_AT, args=[], block=rpc.run_block
        )
        out.append(
            DiscoveredKeeper(
                operation_address=pk,
                paired_pool_address=pool_addr.lower(),
                debt_ceiling=int(ceiling),
                current_debt=int(debt),
                balance=int(bal),
                discovery_provenance=disc,
                reads={
                    "current_debt": ContractRead(
                        source_contract=pk, function=PK_DEBT, args=[], block=rpc.run_block
                    ),
                    "balance": ContractRead(
                        source_contract=crvusd.address,
                        function=BALANCE_OF,
                        args=[pk],
                        block=rpc.run_block,
                    ),
                    "debt_ceiling": ContractRead(
                        source_contract=cf.address,
                        function=DEBT_CEILING,
                        args=[pk],
                        block=rpc.run_block,
                    ),
                },
            )
        )
    return out


def confirm_node_addresses(
    markets: list[DiscoveredMarket], cfg: Config
) -> AddressReconciliation:
    """Reconcile config label addresses against on-chain collaterals.

    A config address absent on-chain is a stale/incorrect config row; an
    on-chain collateral absent from config becomes an unlisted node at label
    time (§8.2 / DET-08). Both are flags, never silent.
    """
    onchain = {m.collateral for m in markets if m.origination_class == "mint"}
    configured = set(cfg.labels)
    return AddressReconciliation(
        matched=tuple(sorted(onchain & configured)),
        config_not_onchain=tuple(sorted(configured - onchain)),
        onchain_not_in_config=tuple(sorted(onchain - configured)),
    )


def discover_lend_markets(rpc, cfg: Config) -> list[tuple[str, str, int]]:
    """3.1b: enumerate lend markets from the signed factory roots.

    FR-10/FR-11 - enumerated ONLY to exclude (DET-07). Returns
    `(market_address, factory_address, index)` triples, sorted by address.

    The count comes from the chain, never from the rows' `vaults` field: that
    field is provenance for why a factory is non-originating (zero ceiling,
    zero held) and is never emitted as a figure. If the chain total differs
    from the 2026-09-05 verification's 52, the chain total is what is
    disclosed - lend counts are logged, never triggered (DET-63).
    """
    out: list[tuple[str, str, int]] = []
    for row in cfg.lend.rows:
        f = row["address"].lower()
        n = int(rpc.read([Call(f, row["count_getter"], ("uint256",))])[0].one())
        addrs = rpc.read([Call(f, row["market_getter"], ("address",), (i,))
                          for i in range(n)])
        for i, res in enumerate(addrs):
            out.append((res.require()[0].lower(), f, i))
    return sorted(out)
