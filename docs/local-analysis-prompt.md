# Local sysdiagnose analysis — copy-paste prompt

Run this on the Mac itself. It's faster there than in a container: `log` and
`plutil` are native, there's no Rust build, and the disk isn't ephemeral.

**Setup:** install [Claude Code](https://claude.com/claude-code), clone this repo,
`cd` into it, put your `sysdiagnose_*.tar.gz` somewhere you can point at, run
`claude`, then paste everything in the box below.

---

## The prompt

````text
You are analysing an Apple sysdiagnose archive. Your job in this session is to get
it fully extracted, converted and indexed — NOT to answer investigative questions
yet. I'll ask those once you report ready.

ARCHIVE: <<<PUT THE FULL PATH TO YOUR .tar.gz HERE>>>

Work through the phases below in order. After each phase print a short status line.
If a phase partially fails, record what failed and why, then continue — a missing
capability should cost one artifact type, not the whole run.

=== HARD RULES — these protect your context window, do not break them ===

1. NEVER use Read, cat, head or grep directly on anything inside the extracted
   case, on any .jsonl the parsers produce, or on unified log output. A single
   one of those files can be gigabytes. Always go through a script that
   aggregates or caps output.
2. Any command you run must bound its own output. Default to 50 rows. When you
   want "everything", COUNT it or GROUP BY it — never print it.
3. Never write the full unified log to disk as JSON or JSONL. See phase 4.
4. Before reporting any number, check whether you actually measured it or
   estimated it. Say which.

=== PHASE 0 — environment ===

Confirm: python3 >= 3.11, and that /usr/bin/log and /usr/bin/plutil exist (they
should, on macOS). Create a venv and install this repo plus query deps:

  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev]"
  .venv/bin/pip install duckdb pyarrow
  mkdir -p yara

Install `.[dev]`, not bare `.` — it pins ruff to the range CI uses. An unpinned
`pip install ruff` grabs a newer minor whose formatter disagrees, and you'll
write code that passes locally and fails CI.

`mkdir yara` is not optional: YaraScanAnalyser raises FileNotFoundError rather
than skipping when that directory is missing.

Report free disk. Rule of thumb: you want ~12x the compressed archive size.

=== PHASE 1 — extract ===

  export SYSDIAGNOSE_CASES_PATH="$PWD/cases"
  .venv/bin/python -m scripts.claude_analyst.ingest <ARCHIVE> --case-id local1

If create_case rejects the archive, that's expected for some macOS captures —
SAF's metadata detection is written for iOS. The script already falls back to a
plain extract under an unregistered case id, which still works because
Sysdiagnose.parse() defaults to {"case_id": case_id} when the case isn't
registered.

Then report, from the survey it prints:
  - device model, OS build, capture time, serial
  - total files and bytes
  - whether system_logs.logarchive exists and how many .tracev3 files it has
  - whether oslog_archive_error.log exists

On that last one: READ IT before drawing conclusions. It is usually a handful of
missing uuidtext symbol files, which costs symbolication on a few messages and
nothing else. It does NOT mean the log capture failed.

=== PHASE 2 — convert every binary artifact ===

Write a script that walks the extracted tree and converts everything, writing
output under cases/local1/converted/. For each file record: path, size, magic
type, which handler ran, whether it succeeded, and rows/keys emitted.

  - .plist (binary or XML) -> JSON. Use plistlib; for NSKeyedArchiver payloads
    use nska_deserialize (already a SAF dependency). Reuse
    src/sysdiagnose/utils/misc.py:load_plist_file_as_json.
  - SQLite (.db/.sqlite*/.PLSQL/.EPSQL) -> one JSONL per table. Copy the DB plus
    any -wal/-shm siblings to a temp dir first and open read-only, or you lose
    uncommitted rows. Reuse src/sysdiagnose/utils/sqlite2json.py.
  - APOLLO routing — do this, it is the single biggest win on a macOS capture,
    because many SAF parsers are iOS-only and will find nothing. Construct it as:

        from sysdiagnose.utils.apollo import Apollo
        from sysdiagnose.utils.logger import logger
        apollo = Apollo(logger=logger, saf_module="residual", os_version="yolo")
        # apollo.supported_database_names is populated on the INSTANCE, not the
        # class — you must construct it before you can check membership.
        if os.path.basename(f) in apollo.supported_database_names:
            events = apollo.parse_db(db_fname=f, db_type=os.path.basename(f))

    It ships 247 module definitions covering 32 databases. The ones that matter
    most on macOS:
        TCC.db ......................... camera/mic/screen/disk permissions
        knowledgeC.db .................. app usage, focus, device pattern-of-life
        CurrentPowerlog.PLSQL .......... per-process energy
        com.apple.LaunchServices.QuarantineEventsV2 ... what was downloaded, from
                                         where, and by which app
        ExecPolicy / KextPolicy ........ what was allowed to execute / load
        netusage.sqlite, DataUsage.sqlite ... per-process network volume
        History.db ..................... Safari history
        chat.db / sms.db ............... Messages
        CallHistory.storedata .......... calls
        coreduetd.db, interactionC.db .. contact and app interaction graph

    Some of those hold personal message and browsing content. Convert them, but
    tell me they're there rather than dumping contents unprompted.
  - .ips / .panic -> use CrashLogsParser.parse_ips_file (it's a staticmethod).
  - nested .gz/.tar/.zip -> recurse, max depth 3.
  - macOS-only text artifacts with no SAF parser (.asl, spindump, sample-*,
    launchctl-print-*, lsappinfo, systemextensionsctl, kmutil, smcDiagnose,
    .pklg, .caar) -> extract what structure you can, otherwise index the lines.
  - anything else -> record it as unconverted WITH A REASON.

IMPORTANT: skip AppleDouble files. Anything whose basename starts with "._" is a
resource-fork stub, not real content. They will silently double your counts —
e.g. 12 .ips files in a directory is often 6 real crashes plus 6 stubs.

Print a summary table only: counts by handler and by status. Not the file list.

=== PHASE 3 — run the SAF parsers ===

  .venv/bin/python -m sysdiagnose -c local1 parse all -x logarchive,apps

Exclude those two deliberately:
  - logarchive: handled in phase 4. SAF's writer produces uncompressed JSONL
    where `message` is duplicated inside `data`, around 1.2 KB per event. At
    millions of events that's tens of GB.
  - apps: it calls LogarchiveParser.get_result(), which triggers exactly that
    write.

Then run the analysers, excluding the ones that will fail, are redundant, or
ALSO call LogarchiveParser under the hood:

  .venv/bin/python -m sysdiagnose -c local1 analyse all -x apps,ps_everywhere,coverage,yarascan

grep the analysers directory yourself before trusting this list — `grep -l
LogarchiveParser src/sysdiagnose/analysers/*.py` is the ground truth, and it
currently returns exactly `apps.py` and `ps_everywhere.py`. Missing either one
is not cosmetic: it materialises the full uncompressed logarchive.jsonl (~1.2
KB/event) as a side effect, which is multiple GB even on a modest capture.
Verified the hard way — running only `-x apps,coverage,yarascan` (no
ps_everywhere) let a background run write 3.9 GB / 2.4M lines of
logarchive.jsonl before it was caught and killed partway through.

Read per-module results from cases/local1/logs/summary-<module>.json — note that
path. It is NOT parsed_data/<module>.summary.json.

Expect a LOT of parsers to report zero events on a macOS capture. That's the
expected shape, not a bug. Also note SAF stores the macOS version in a field
named `ios_version` and gates parsers on it via PEP 440, so a few parsers get
skipped by version comparison even where they might have worked.

Report: how many modules produced events, how many were empty, how many errored.

=== PHASE 4 — index the unified log WITHOUT materialising it ===

On macOS use the native decoder and stream it:

  /usr/bin/log show <case>/system_logs.logarchive --style ndjson --info --debug --signpost

Pipe that straight into Parquet in batches of ~250k rows. Keep typed columns
(time, process, pid, subsystem, category, event_type, message, thread_id,
activity_id) and DROP the redundant nested payload — it's ~90% duplicated by the
typed columns and it's the difference between a few GB and tens of GB.

First, just COUNT the events and report the number and how long the decode took.
Then build the Parquet index.

=== PHASE 5 — build the query layer ===

Create cases/local1/index/case.duckdb with DuckDB views over the Parquet and
JSONL. Build one normalised timeline table across every source:

  ts (TIMESTAMP, UTC), day (DATE), source, module, process, pid, subsystem,
  category, event_type, bundle_id, message (truncate to 4000 chars),
  message_len, rel_path

Note when normalising SAF output: Event.to_dict() emits exactly five keys —
datetime, message, timestamp_desc, module, data. There is NO top-level
`timestamp` float in the written JSONL, so parse `datetime`. Also, PlistParser
does not write a single plists.json; it writes one JSON per plist into
parsed_data/plists/, so special-case it.

Store everything UTC. Record the device's local offset separately.

=== PHASE 6 — report readiness, then STOP ===

Print:
  - device identity and capture window
  - total events in the timeline, and the date range it actually covers
  - modules with events, ranked
  - what could NOT be converted, with reasons, as a percentage of total bytes
  - disk used
  - anything you had to skip and what it costs me

Then stop and wait. Do not start investigating.

Once you report ready, I'll ask questions like "what crashed and why", "list
launch agents not signed by Apple", "show DNS lookups ranked by frequency",
"what happened in the 5 minutes before capture". Answer those by querying the
index — never by reading raw files.
````

---

## Why these specific warnings are in there

Every one of them cost time in a real run of this pipeline:

| Warning | What actually happened |
|---|---|
| `mkdir yara` | `YaraScanAnalyser` raises `FileNotFoundError`, it doesn't skip |
| Summary path | Summaries are at `cases/<id>/logs/summary-<module>.json`, not next to the parsed data |
| `Event.to_dict()` | Five keys, and no top-level `timestamp` float — consumers must parse `datetime` |
| Exclude `apps` | It calls `LogarchiveParser.get_result()` and materialises the whole log |
| Skip `._` files | 12 `.ips` files in one capture turned out to be 6 crashes plus 6 AppleDouble stubs |
| Read the error log | `oslog_archive_error.log` was one missing uuidtext file, not a failed capture |
| Install `.[dev]` | An unpinned ruff was a minor version ahead of CI's and formatted differently |
| `ios_version` gating | SAF stores the macOS version there and skips parsers on a PEP 440 comparison |
| `Apollo(...)` args | `logger` and `saf_module` are required positional args, and `supported_database_names` only exists after construction |

## Measured on a real archive

257 MB compressed → 692 MB extracted, 2,305 files, macOS 15.7.7 on an M1 MacBook Pro:

- extract: **12 s**
- unified log: **5,249,905 events**, decoded in **52 s** on Linux (~101k events/sec; native `log show` on macOS is comparable or faster)
- decode errors: 153, or **0.003%**
- that log as JSONL would be **~6.5 GB** — hence phase 4

Scale roughly linearly for a larger archive.
