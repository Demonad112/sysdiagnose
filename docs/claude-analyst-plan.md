# Claude as a sysdiagnose analyst — implementation plan

## Context

The goal is to make Claude Code *interrogate* a large Apple sysdiagnose conversationally — "what ran at 02:00", "which app got camera access", "show me every persistence point" — not to build an app or a report generator. The blocker is scale: a sysdiagnose is a few hundred MB compressed, expands to gigabytes, and the interesting files are exactly the unreadable ones (binary plists, SQLite, `.asl`, `.caar`, unified-log `tracev3`).

The fix is **convert-once, query-many**: an unattended pipeline that turns the whole archive into structured columnar data, plus a CLI (`sdq`) whose every output is bounded so Claude can ask hundreds of questions without exhausting context. A Skill teaches Claude to reach for `sdq` automatically and forbids it from touching raw case files.

### What we're working with (probed, not assumed)

| | |
|---|---|
| Archive | `sysdiagnose_2026.07.13_13-52-59-0600_macOS_MacBookPro17-1_24G720.tar.gz` |
| Drive id | `1HDkaGL4qLvtzOcX9KAnK7hcjBi4XdFZw` (folder `mac new`) |
| Compressed | 256,986,065 B (245 MB) — raw `application/x-gzip`, **not** Docs-converted |
| Extracted | ~2.18 GB (from the gzip ISIZE trailer) |
| Device | MacBook Pro 17,1 (M1), macOS build **24G720**, captured 2026-07-13 13:52 −0600 |
| Repo | `/home/user/sysdiagnose` = SAF (EC-DIGIT-CSIRC), 47 parsers, 12 analysers, **iOS-targeted** |
| Branch | `claude/sysdiagnose-analyzer-plan-tpp1ul` |
| Container | Linux x86_64, 4 vCPU, 15 GB RAM, **30 GB free**, ephemeral |

Decisions taken: run in **this cloud session**; source via **Google Drive**; **hybrid** unified-log depth; new code as a **separate layer**; **full macOS residual coverage**; **open-ended exploration**; and — your mid-flight addition — **push distilled results back to Drive** so work survives the container.

### Five findings that shape the plan

1. **The data is macOS, SAF is iOS.** ~Half of the 47 parsers key off iOS paths and will find nothing. They degrade quietly (`logger.warning` + empty), so it isn't fatal — but the residual sweep (Phase 5) is what makes the case complete, not a nice-to-have.
2. **APOLLO is the macOS rescue.** `utils/apollo.py` ships **247 module definitions** covering `knowledgeC.db`, `TCC.db`, `CurrentPowerlog.PLSQL`, `netusage.sqlite`, `interactionC.db` and ~25 more — databases that exist on **macOS too**. Your Drive listing already shows `powerlog_2026-07-13_13-54_13CAFDBA.PLSQL`. Auto-routing residual SQLite through APOLLO recovers most of the macOS coverage gap for free.
3. **Unified logs may be absent or damaged.** The exploded copy of this same sysdiagnose in your `Reports` folder contains `oslog_archive_error.log`, and no `tracev3` appears anywhere in Drive. Detect at ingest and say so loudly rather than shipping a thin timeline as a complete one.
4. **The Docs-converted copies are unusable.** The `Reports` folder holds this same sysdiagnose exploded into Google Docs; that conversion destroys binary plists and mangles text. The `.tar.gz` is the only authoritative source. (This is also why every write-back in Phase 9 sets `disableConversionToGoogleType: true`.)
5. **`static.crates.io` returns 403 through the agent proxy but 200 direct.** The cargo build of the unified-log extractor *will* fail unless `no_proxy` is augmented for that step. This is the single highest-risk task in the whole plan.

---

## Connectors, resources, prerequisites

All probed live. **Nothing further is required from you** — Phases 0–8 run unattended.

| Need | Status |
|---|---|
| Google Drive connector | Connected. Used for discovery *and* for the Phase 9 write-back (`create_file` supports `textContent` + `disableConversionToGoogleType`). |
| Bulk download | **Anonymous HTTPS works** — `drive.usercontent.google.com` returned `206 Partial Content`, gzip magic `1f 8b 08 00`. No OAuth, no MCP streaming, resumable via range. |
| PyPI | Direct (in `no_proxy`). `duckdb` 1.5.5 `cp311-manylinux_2_28_x86_64` wheel downloaded as a live test. |
| `index.crates.io` | 200 direct. |
| `static.crates.io` | **403 proxied / 200 direct** — see finding 5. |
| GitHub | `git ls-remote` works (git proxy injection). But `github.com`/`api.github.com` over plain HTTPS return 403 ⇒ **use `git`, never `curl`/`gh`, for third-party repos.** |
| Ubuntu apt | `archive.ubuntu.com` 200; running as root, `sudo` present. |
| Disk | 30 GB free; projected peak ~6–11 GB. |

> **Never** use `mcp__Google_Drive__download_file_content` for the archive — it returns base64 into the conversation (245 MB ⇒ ~327 MB of context). MCP for discovery, `curl` for bulk.

**Optional, high value:** YARA rules for the tamper playbook (`./yara/*.yar`). Without them `yarascan` is skipped. Say the word and I'll add a vetted fetch step.

---

## Architecture

New code lives outside `src/sysdiagnose/` so the fork keeps merging upstream cleanly.

```
CLAUDE.md                                  # ~30 lines: skill pointer + hard rules
.claude/skills/sysdiagnose-analyst/
    SKILL.md                               # triggers, rules, the investigation loop
    references/cli.md                      # full sdq contract
    references/data-dictionary.md          # artifact -> questions it answers
    references/schema.md                   # index schema + join keys
    references/cookbook.md                 # ~30 copy-paste SQL recipes
    references/playbooks/*.md              # apps, network, crashes, persistence, power, timeline
scripts/sdq                                # shim: finds .venv, execs the CLI
scripts/claude_analyst/
    cli.py  env.py  bootstrap.py  ingest.py
    saf_runner.py                          # subprocess-per-module, timeout, crash isolation
    logarchive_index.py                    # streaming tracev3 -> Parquet (never JSONL)
    residual.py                            # the macOS/everything-else sweep
    normalise.py  index.py  store.py  render.py  reports.py  schema.py
    fixtures.py  selftest.py               # data-free validation
    drive_sync.py                          # Phase 9 write-back
```

**Query engine: DuckDB** over Parquet. Reads files in place, no server, bounded memory, and Parquet row-group zone maps make `WHERE ts BETWEEN …` fast with no index. Verified installable here.

Fallback ladder behind `store.py`, with the active tier recorded in the case manifest and reported by `sdq doctor` (never switched silently mid-case):
1. `duckdb` → Parquet + SQL *(preferred)*
2. `pyarrow` only → Parquet + fixed subcommands, no `sdq sql`
3. stdlib `sqlite3` + `rg` → logarchive capped by `--max-events`

Note: `json` and `parquet` are statically linked into the DuckDB wheel; **`fts` is not** and may not install. Full-text search must degrade to `LIKE` + ripgrep rather than being a hard dependency.

---

## Corrections to the obvious assumptions

These were verified by reading the source and would each have caused a real bug:

- Summaries live at **`cases/<id>/logs/summary-<module>.json`**, not `parsed_data/<module>.summary.json` (`utils/base.py:138`).
- `Event.to_dict()` emits exactly **five** keys: `datetime` (ISO µs), `message`, `timestamp_desc`, `module`, `data`. There is **no top-level `timestamp` float** in the written JSONL — it exists only via `__getitem__`. The normaliser must parse `datetime`.
- **`PlistParser` writes one JSON per plist** into `parsed_data/plists/<path_with_underscores>.json` and overrides `output_exists`/`_write_result`/`_load_output`. The indexer must special-case it.
- **`YaraScanAnalyser` raises `FileNotFoundError`** if `./yara` doesn't exist — a hard crash, not a soft skip. Bootstrap must `mkdir -p yara`.
- **`packaging` and `pytest` are not in `pyproject.toml`** (`packaging` arrives transitively via matplotlib; `pytest` is missing from the `dev` extra despite the Makefile using it). Install both explicitly.
- `Sysdiagnose.parse()` uses `self.cases().get(case_id, {"case_id": case_id})` — an **unregistered case_id still works**. That's the documented escape hatch when `create_case()` refuses a corrupt archive.
- `.github/workflows/unittest.yml` holds the **upstream-blessed `unifiedlog_iterator` build recipe** — copy it verbatim; the binary may land in either `target/release/` or `examples/target/release/`, so probe both.

---

## The one design decision that makes this fit on disk

**Never materialise `logarchive.jsonl`.** SAF's writer emits uncompressed JSONL where `message` is duplicated inside `data` — ~1.0–2.5 KB/event. At 10–30M events that's **10–40 GB**, which does not fit in 30 GB.

Instead, reuse SAF's decode logic but bypass its writer. Both platforms converge on one mapper:

- **Linux:** `LogarchiveHelper._convert_using_unifiedlogparser_generator(folder)` — already a generator, already shells out to `unifiedlog_iterator --mode log-archive --input <dir> --format jsonl` (`parsers/logarchive.py:266`).
- **macOS:** the same `["/usr/bin/log","show",folder,"--style","ndjson","--info","--debug","--signpost"]` array (`:213`) through `LogarchiveHelper._execute_cmd_and_yield_result()`, mapped by `convert_entry_to_unifiedlog_format()`.

Stream in 250k-row batches straight to Parquet with typed columns and **`data` dropped for logarchive rows** (~90% redundant with the typed columns). Difference: ~3 GB instead of ~30 GB.

**Consequence — the `apps` analyser must be excluded by default.** It calls `LogarchiveParser.get_result()`, which would trigger exactly the giant JSONL write we're avoiding. `sdq report apps` reimplements its bundle-id sweep as one SQL query over the Parquet instead.

---

## Phases

Phases 0–8 run unattended end to end.

**Phase 0 — `sdq doctor`.** Stdlib-only, zero writes. Capability table, recommended store tier, estimated disk. Build this first; it's the prereq for everything.

**Phase 1 — Bootstrap.** Idempotent, order matters:
1. `apt-get install -y libmagic1 graphviz libyara-dev sqlite3` (python-magic needs libmagic; ps_matrix needs dot).
2. `python3 -m venv .venv` → `pip install -e .` → `pip install duckdb pyarrow pytest packaging`.
3. `mkdir -p yara` — silences the `YaraScanAnalyser` crash.
4. Unified-log extractor (Linux only), per the CI recipe, **with the proxy fix**:
   ```
   git clone --depth 1 https://github.com/mandiant/macos-UnifiedLogs tools/macos-UnifiedLogs
   cd tools/macos-UnifiedLogs/examples/unifiedlog_iterator
   NO_PROXY="$NO_PROXY,static.crates.io,crates.io" \
   no_proxy="$no_proxy,static.crates.io,crates.io" cargo build --release
   # probe ../target/release/ AND ../../target/release/
   ```
5. Write `.sdq/env.json`. **Never abort on a single failure** — a missing extractor costs unified logs only.

**Phase 2 — Skill + docs.** Written against the frozen CLI contract. Needs no data; can land before ingestion works.

**Phase 3 — Fetch + ingest.** Preflight free disk ≥ 4× compressed. `curl -L -C - --retry 5` (resumable), verify `1f 8b`, record sha256, read ISIZE, and reject Google's HTML interstitial rather than writing it as a "corrupt archive". Then `Sysdiagnose.create_case()`. Immediately assert and report: is `system_logs.logarchive/` present with `*.tracev3`? Is `oslog_archive_error.log` present?

**Phase 4 — SAF parsers.** `saf_runner.py`, subprocess-per-module with per-module timeout and disk guard so one segfault or hang doesn't kill ingest. Excluded by default: `logarchive` (Phase 6), `apps` (see above), `coverage` (matplotlib HTML — replaced by `sdq report coverage`), `yarascan` (unless rules supplied). Expect many parsers to report zero events; that's the expected shape on macOS data, not a bug.

**Phase 5 — Residual sweep (the "fully dive in" part).** Walk `cases/<id>/data/**`, classify by magic + mime + extension, route:

| Detected | Handler | Reuses |
|---|---|---|
| `bplist00` / XML plist | `misc.load_plist_file_as_json()`, NSKeyedArchiver via `nska_deserialize` | `utils/misc.py` |
| `SQLite format 3` | copy DB + `-wal`/`-shm`, open read-only, dump each table to Parquet | `utils/sqlite2json.py` |
| SQLite ∈ `Apollo.supported_database_names` | **additionally** `Apollo(...).parse_db()` → real `Event`s | `utils/apollo.py` + 247 modules |
| `.ips` / `.panic` outside `crashes_and_spins/` | `CrashLogsParser.parse_ips_file()` (static) | `parsers/crashlogs.py` |
| nested `.gz`/`.tar`/`.zip` | recurse, depth ≤ 3, expansion cap | stdlib |
| macOS-only: `.asl`, `spindump`/`sample-*`, `launchctl-print-*`, `lsappinfo`, `systemextensionsctl`, `kmutil`, `smcDiagnose`, `.pklg`, `.caar` | structured where known, line-indexed where not | new |
| text < 32 MB | timestamp-regex line extraction | `utils/times.py`, `multilinelog.py` |
| opaque binary | bounded `strings` (ASCII + UTF-16LE, 2 MB cap) | stdlib |
| anything else | `status=catalogued`, `reason="<mime>: no handler"` | — |

Nothing is silently dropped — the residue *is* the coverage report, surfaced by `sdq catalog --unconverted`.

**Phase 6 — Logarchive streaming index.** As above. Independent of 4/5; sequential by default (disk contention), `--parallel` to overlap.

**Phase 7 — Index build.** `normalise.py` + `index.py` → events Parquet, `catalog.parquet`, small tables, DuckDB views.

**Phase 8 — Query CLI + reports.** Can be developed against synthetic Parquet from day one.

**Phase 10 — GitHub Pages launcher UI. ✅ BUILT.** `docs/index.html` — a single self-contained page (no build step, no external requests) mapping a sysdiagnose into **15 categories**, each with the files it lives in, the SAF modules that parse it, and **56 ready-to-paste prompts**. A "case path" box at the top rewrites every prompt to point at your folder; plus search, macOS/iOS filter, per-prompt copy button, and light/dark themes.

Per your choice, it carries **no device data at all** — it describes the *structure* of a sysdiagnose, not the contents of any case, so it is safe to publish and works before anything is ingested. `.github/workflows/pages.yml` is **`workflow_dispatch`-only** (no `on: push`), so nothing publishes until you turn Pages on and run it manually; it also fails the build if case-derived artifacts (`*.parquet`, `*.duckdb`, `catalog*.json`) ever appear in `docs/`.

**Phase 9 — Drive write-back (your suggestion).** The container is ephemeral; `cases/` is disposable. After a session, `sdq sync-drive` pushes **distilled artifacts only** into a `sysdiagnose-analysis/<case_id>/` folder: `status.md`, `coverage.md`, `gaps.md`, cached reports, any timeline extract, and a findings note. All written with **`disableConversionToGoogleType: true`** so Drive never mangles them the way it did your earlier upload. Multi-GB Parquet stays local — it's regenerable from the archive, and content passes through the conversation so only small artifacts are viable.

---

## `sdq` CLI contract

Global on every subcommand: `-c/--case-id`, `--limit N` (default **50**, hard max 2000), `--offset`, `--format table|json|jsonl|csv|md`, `--fields`, `--width` (per-cell cap, default 120), `--no-footer`.

Every command ends with a machine-readable footer so Claude knows whether it saw everything:

```
[rows=50 of 4127 truncated=yes elapsed=0.31s next="sdq timeline --offset 50 ..."]
```

| Group | Commands |
|---|---|
| Setup | `doctor`, `bootstrap`, `ingest <archive> [--profile fast\|standard\|deep] [--logarchive full\|window\|skip] [--resume] [--budget-gb N]`, `status` |
| Discovery | `modules [--nonempty]`, `catalog [--unconverted] [--by ext\|mime\|dir]`, `schema`, `report <device\|apps\|network\|wifi\|crashes\|profiles\|accounts\|battery\|persistence\|coverage>` |
| Query | `around <ISO> [--window 5m]`, `timeline [--from/--to] [--module] [--process] [--grep]`, `search "<pat>" [--regex]`, `agg --by module,process`, `histogram --bucket 1h`, `sql "SELECT ..."` (read-only, auto-LIMIT) |
| Artifacts | `artifact ls`, `artifact show <path> [--as auto\|plist\|json\|text\|hex\|strings] [--path a.b.c]`, `artifact tables <db>`, `artifact query <db> "SQL"`, `artifact strings <path>` |
| Escape | `export --sql "..." --out f.csv` → prints **only** `wrote N rows to <path>`; Claude re-queries the file, never `Read`s it |
| Persist | `sync-drive [--folder-id ID]` |

`sdq artifact show` is the "read any file safely" surface — auto-detects bplist→JSON, SQLite→schema+sample, `.asl`→text, unknown binary→hexdump+strings, always bounded.

---

## Index schema

```
cases/<id>/index/
  manifest.json                     # resumable phase state + capabilities + schema version
  case.duckdb                       # views only, <10 MB
  catalog.parquet                   # every file, with disposition
  events/module=<name>/part-*.parquet   # sorted by ts, ZSTD, 100k row groups
  sqlite/<slug>/<table>.parquet
  plists/<slug>.json
  strings/<slug>.txt
  reports/*.json
```

**`events`** — the load-bearing cross-artifact timeline:

`event_id`, `ts` (TIMESTAMP, **UTC**, µs), `day` (DATE, for partition pruning), `ts_desc`, `module`, `source` (`saf|logarchive|residual`), `process`, `pid`, `thread_id`, `subsystem`, `category`, `event_type`, `bundle_id`, `message` (**truncated to 4000 chars**), `message_len` (true length, so truncation is visible), `rel_path`, `data` (JSON; **NULL for `source='logarchive'`**).

**`catalog`** — `rel_path`, `size_bytes`, `mime`, `magic_desc`, `ext`, `sha256` (<64 MB only), `mtime`, `saf_parser` (computed the same way `CoverageAnalyser.get_parser_coverage` does), `handler`, `status` (`indexed|partial|catalogued|skipped|error`), `reason`, `converted_path`, `rows_emitted`, `container_path`. **`status != 'indexed'` is the blind-spot report.**

Plus small tables: `device` (1 row), `modules` (joined with `logs/summary-<module>.json`), `sqlite_tables`, `plists`, `strings_index`.

Everything stored UTC; `--tz local` renders in the device's offset.

---

## Estimates (this 245 MB archive, 4 vCPU)

| Phase | Wall clock | Disk delta |
|---|---|---|
| Bootstrap (cargo is the long pole) | 5–15 min | +0.5 GB |
| Fetch 245 MB | 1–3 min | +0.25 GB |
| Extract | 1–3 min | +2.2 GB |
| SAF parse (46 modules) | 8–25 min | +0.4–1.5 GB |
| Residual sweep | 5–20 min | +0.2–1.0 GB |
| Logarchive → Parquet *(if present)* | 20–90 min | +0.4–3.5 GB |
| Index build | 1–4 min | +50 MB |
| **Total** | **40–160 min** | **peak ~6–11 GB of 30 GB** |

`--profile fast` (skip logarchive + strings) finishes in **15–40 min** and is the right first pass — especially here, where the logarchive may not exist at all.

**On the 400 MB target:** you asked for 400 MB+; this archive is 245 MB. Everything above is sized for the larger case regardless — streaming writes, Parquet, per-phase disk preflight, on-demand log expansion. A 400 MB–1 GB archive (~4–8 GB extracted) needs no changes.

---

## Failure modes

| Failure | Handling |
|---|---|
| **`cargo` 403 on `static.crates.io`** (most likely) | `no_proxy` augmentation built into bootstrap. If it still fails: `--logarchive skip`; every affected report prints `[blind-spot: unified logs not indexed]`. `shutdownlogs` and `logdata_statistics` still work — they read plain text from `logarchive/Extra/`. |
| **No logarchive in the archive** (likely here) | Detected Phase 3, stated plainly. Timeline built from the other ~40 sources + APOLLO. |
| DuckDB unavailable | Tier 2 (pyarrow) → tier 3 (sqlite3 + rg). `sdq sql` disabled in tier 3 with a message pointing at the fixed subcommands. |
| DuckDB `fts` extension unavailable | Degrade to `LIKE` + ripgrep. Never a hard dependency. |
| Disk fills mid-ingest | `--budget-gb` checked before each phase and every 250k-row batch. Abort cleanly, mark `status=aborted_disk`, keep what's written. `ingest --resume` continues. |
| Corrupt archive (`create_case` raises `ValueError`) | Catch it, `tar -xzf` directly into `cases/<id>/data/`, run parsers with an **unregistered case_id** (works — see corrections). Exposed as `ingest --unsafe-extract`. |
| Parser crashes or hangs | Subprocess + timeout; mark `error`/`timeout` in `modules`, continue. |
| Extractor emits garbage | Its stderr `[ERROR]` counter is already tracked (`logarchive.py:52-70`); warn if error rate > 1%. |
| Container loss | `cases/` is gitignored and disposable. Commit `scripts/` + `.claude/` early; Phase 9 pushes distilled results to Drive. |

---

## Verification

**Stage A — no real data (CI-able, <1 min).** `fixtures.py` builds a synthetic archive with the minimum SAF requires plus one of each residual type:
- `sysdiagnose.log` containing `IN_PROGRESS_sysdiagnose_2026.07.13_13-52-59-0600_` (required by `get_sysdiagnose_creation_datetime_from_file`, `base.py:231-244`)
- `remotectl_dumpstate.txt` in tab-based-hierarchy form with a `Local device` block
- `SystemVersion.plist` + `ioreg/IODeviceTree.txt` (the backup metadata path)
- residual probes: a binary plist with an NSKeyedArchiver blob, a `TCC.db` + `-wal` (exercises the APOLLO route), an `.ips`, a `.gz`-in-tar, an opaque binary

`selftest.py` asserts: ingest exits 0; **100%** of walked files have a non-null `catalog.status`; a seeded marker is findable via `sdq search`; a seeded event is returned by `sdq around`; every subcommand honours `--limit` and emits a footer; no command exceeds ~4 KB at default limits.

**Stage B — real public data.** `git submodule update --init --depth 1 tests/testdata` (reachable — verified). Ingest a real iOS archive and assert `sdq modules` counts match `logs/summary-<module>.json` `num_events` for every jsonl module — that's the proof normalisation loses nothing. Also `pytest tests` to confirm no upstream regression.

**Stage C — your real archive.** `sdq ingest --profile standard`, then `sdq status`. Success: device reads `MacBookPro17,1` / `24G720` / 2026-07-13 (cross-checked against `sw_vers` and `remotectl_dumpstate` in the tree); catalog file count matches `tar tzf | wc -l` ±known skips; `sdq artifact show` on `com.apple.windowserver.displays.plist` returns JSON not hex; `sdq artifact tables` on the `.PLSQL` returns table names + row counts; `sdq around` on the capture time returns events from **more than one** module; `sdq catalog --unconverted` accounts for the remainder with reasons; unconverted bytes < 5% of total.

---

## Needs your explicit approval (will not be done silently)

- **`.claude/settings.json` permission allowlist** (`Bash(scripts/sdq:*)` etc.) to cut approval prompts during long sessions. Proposed only — bootstrap will not write it.
- **Installing into the repo:** `pip install` into `.venv/`, `git clone` + `cargo build` into `tools/`. Both gitignored.
- **YARA rules** if you want the tamper playbook to be more than heuristics.

## Out of scope

No web UI, no report generator, no Timesketch/ELK/Splunk export (SAF already ships those under `scripts/`). No changes to `src/sysdiagnose/` — the streaming logarchive hook is the one thing that would otherwise belong there, and calling `LogarchiveHelper`'s static methods directly avoids needing it.
