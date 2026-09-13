# DuckDB SQL performance benchmark

Generated: `2026-09-13T02:59:24.342001+00:00`

This snapshot is machine-specific evidence from a local analytical database. It is not a distributed MPP benchmark.

## Environment and data

- DuckDB `1.5.5` on `Windows-11-10.0.26200-SP0`
- Python `3.14.2`; 16 logical CPUs visible
- Database: `mlb_pitch_analytics.duckdb` (1,665,675,264 bytes)
- `silver.fact_pitch`: 1,355,356 rows, 2025-03-18 through 2026-09-09
- `silver.fact_game_context`: 4,626 rows
- Recent-filter cutoff: `2026-08-11` (inclusive)
- Recent-filter input: 120,746 rows (8.909% of pitch facts)

## Results

| Query | Workload | Threads | Median ms | p95 ms | Speedup vs 1 thread | Result rows |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `full_scan_aggregate` | scan + grouped aggregate | 1 | 56.151 | 57.062 | 1.000x | 5,323 |
| `full_scan_aggregate` | scan + grouped aggregate | 2 | 34.210 | 34.669 | 1.641x | 5,323 |
| `full_scan_aggregate` | scan + grouped aggregate | 4 | 32.679 | 35.598 | 1.718x | 5,323 |
| `full_scan_aggregate` | scan + grouped aggregate | 8 | 29.094 | 32.840 | 1.930x | 5,323 |
| `recent_filter_aggregate` | selective date filter + aggregate | 1 | 16.049 | 16.579 | 1.000x | 2,557 |
| `recent_filter_aggregate` | selective date filter + aggregate | 2 | 15.324 | 16.023 | 1.047x | 2,557 |
| `recent_filter_aggregate` | selective date filter + aggregate | 4 | 12.592 | 17.741 | 1.275x | 2,557 |
| `recent_filter_aggregate` | selective date filter + aggregate | 8 | 12.850 | 13.408 | 1.249x | 2,557 |
| `game_context_join` | fact-to-dimension hash join + aggregate | 1 | 40.672 | 44.928 | 1.000x | 973 |
| `game_context_join` | fact-to-dimension hash join + aggregate | 2 | 37.474 | 38.679 | 1.085x | 973 |
| `game_context_join` | fact-to-dimension hash join + aggregate | 4 | 25.590 | 27.644 | 1.589x | 973 |
| `game_context_join` | fact-to-dimension hash join + aggregate | 8 | 20.818 | 21.712 | 1.954x | 973 |
| `partitioned_window` | grouped input + partitioned window | 1 | 155.185 | 156.043 | 1.000x | 39,561 |
| `partitioned_window` | grouped input + partitioned window | 2 | 142.795 | 145.271 | 1.087x | 39,561 |
| `partitioned_window` | grouped input + partitioned window | 4 | 137.632 | 143.838 | 1.128x | 39,561 |
| `partitioned_window` | grouped input + partitioned window | 8 | 133.200 | 142.605 | 1.165x | 39,561 |

## Interpretation boundaries

- Median warm-run wall-clock latency is the comparison metric; `first_observed_ms` is retained in JSON but is not called cold-cache latency.
- The date-filter query demonstrates predicate selectivity in this DuckDB file; it does not claim physical partition pruning.
- More threads can be slower for small or coordination-heavy queries. Report the observed result rather than assuming linear scaling.
- Timings include complete result materialization into Python and will vary with hardware, cache state, background load and DuckDB version.
- Every query's row count and SHA-256 matched across thread counts during this run.

See `docs/SQL_PERFORMANCE.md` for the reproducible command, query rationale and interview framing.
