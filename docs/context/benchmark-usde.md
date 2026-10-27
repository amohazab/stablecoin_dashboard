# USDe benchmark note (Q35) — report 7b2604e7 against published third-party assessments

**Status:** draft for `docs/context/benchmark-usde.md` (P-10.15), not a publishing gate (Q35).
**Ours:** USDe report `7b2604e7`, block 26285908, disclosures as of 2026-10-27 14:59 UTC;
every figure below is the page's printed value (table.json), or for one row the bundle's read (FR-U09).
**Theirs:**
- **A.** LlamaRisk, *Ethena USDe on Aave X Layer Assessments*, posted 2026-10-12 —
  https://governance.aave.com/t/ethena-usde-on-aave-x-layer-assessments/25827
- **B.** S&P Global Ratings, *Stablecoin Stability Assessment: USDe*, 2026-01-14 (paywalled;
  only the score is public) —
  https://www.alacrastore.com/s-and-p-credit-research/Stablecoin-Stability-Assessment-USDe-3502614

A second Aave governance review (Aave Labs, *USDe on Aave Monad*, 2026-06-30) states no backing,
allocation or stress figure and is not compared.

## Figure by figure

| figure | ours (2026-10-27) | theirs (date) | verdict and why |
|---|---|---|---|
| backing | $4,571,565,339.86 (status route) | A: $4.76B (2026-10-12) | **differ by data**: snapshots of 2026-10-12 and 2026-10-27; supply fell between them (ours 4,567,732,299.22 USDe vs A's 4.76B) |
| backing ratio (headline) | 100.1% of supply (100.08%) | A: "$4.76B against 4.76B USDe outstanding" (2026-10-12) | **agree**: both ≈ 1:1; ours prints the second decimal, under memo #2 §8(d)'s 101% floor (T-07) |
| DeFi lending share | 32.9% of backing | A: 36.9% | **differ by data**: the route's category values moved between the two dates |
| liquid stables share | 28.8% | A: 24.9% | **differ by data**: same cause |
| crypto basis share | 15.5% (+ equity and RWA basis 1.1%) | A: 17.6% | **differ by method and data**: A lists no separate equity and RWA basis category |
| institutional lending share | 15.4% | A: 14.3% | **differ by data** |
| RWA share | 6.2% | A: 6.0% | **agree** within the date gap |
| stress row 1 headline (funding reversal, N = 90) | post-loss ratio 100.1% | none | **no counterpart**: A and B publish no scenario figures |
| stress row 2 headline (largest custody location lost: Copper) | post-loss ratio 89.5% | none | **no counterpart** |
| stress row 3 headline (redemption run) | depeg-pressure ratio 0 | none | **no counterpart**; see the redemption-limit row for the shared input |
| redemption limit per block | 20,000,000 USDe (FR-U09, `globalMaxRedeemPerBlock`) | A: "redemption at 20,000,000 USDe per block" | **agree**: same contract parameter; ours feeds row 3's capacity bound, A notes it is a ceiling, not cash |
| bridge escrow on Ethereum | 2,124,582,255.41 USDe (OFT adapter) | A: 2.28B USDe (undated) | **differ by data**: A's figure carries no date |
| disclosure-age headline | 72.2 days average; worst Liquid Stables, 119.0 days | none | **no counterpart**: A cites LlamaRisk's own PoR attestor role, no age figure |
| on-chain buffer reconciliation gap | 4.4% of backing | none | **no counterpart** |
| overall stability | no grade (DET-88: the report carries no score by design) | B: score 5, "weak" (2026-01-14) | **differ by method**: B is a qualitative peg-stability score; ours is structural figures only |

## Reading

Where both sides measure the same thing (backing, the ≈ 1:1 ratio, the per-block redemption
cap), the figures agree or differ only by the dates of the two snapshots (2026-10-12 and
2026-10-27); the allocation shares differ the way the route's monthly categories move.
Neither assessment publishes stress scenarios, disclosure ages or an on-chain buffer
reconciliation, so the report's three stress rows and its two verifiability figures have no
external benchmark yet. No divergence points to a pipeline defect.
