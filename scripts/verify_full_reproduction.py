"""Read-only postflight for a completed, full classroom-model reproduction.

Never launches NetLogo or R and never changes scientific sources. Large native
tables are streamed; cross-model trajectories use a disposable SQLite index.
Exit 0 = passed, 1 = failed, 2 = incomplete (missing/running upstream outputs).
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TOLERANCE = 1e-10
JOBS = (
    (2, "experiment-2-calibration-estimate-good", "calibration_estimate_good_raw.csv"),
    (2, "experiment-2-calibration-estimate-bad", "calibration_estimate_bad_raw.csv"),
    (2, "experiment-2-calibration-heldout-good", "calibration_heldout_good_raw.csv"),
    (2, "experiment-2-calibration-heldout-bad", "calibration_heldout_bad_raw.csv"),
    (0, "experiment-0-bandit-main-final", "raw_main_final.csv"),
    (0, "experiment-0-bandit-peer-check", "raw_peer_check.csv"),
    (0, "experiment-0-bandit-trajectories", "raw_trajectories.csv"),
    (1, "experiment-1-evidence-main-final", "raw_main_final.csv"),
    (1, "experiment-1-evidence-trajectories", "raw_trajectories.csv"),
    (2, "experiment-2-opaque-main-final", "raw_main_final.csv"),
    (2, "experiment-2-opaque-trajectories", "raw_trajectories.csv"),
    (2, "experiment-2-exact-regression-trajectories", "raw_exact_trajectories.csv"),
)
ANALYSIS_FILES = (
    ("calibration", 2, "calibration_validation_checks.csv", 13),
    ("calibration", 2, "frozen_credence_message_table.csv", 10),
    ("calibration", 2, "heldout_calibration_audit.csv", 10),
    ("experiment_0", 0, "trajectory_summary.csv", 1002),
    ("experiment_0", 0, "validation_checks.csv", 36),
    ("experiment_1", 1, "endpoint_summary.csv", 6),
    ("experiment_1", 1, "paired_contrasts.csv", 42),
    ("experiment_1", 1, "trajectory_chart_data.csv", 612),
    ("experiment_1", 1, "validation_checks.csv", 33),
    ("experiment_2", 2, "endpoint_summary.csv", 30),
    ("experiment_2", 2, "paired_policy_effects.csv", 30),
    ("experiment_2", 2, "trajectory_chart_data.csv", 612),
    ("experiment_2", 2, "validation_checks.csv", 21),
)
EXACT_ALIASES = {"Exact-C-Preemption": "E-Preemption", "Exact-C-Total Evidence": "E-Total Evidence"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class FileAudit:
    """Chunked digests plus a final check that audited inputs have not moved."""
    def __init__(self):
        self.files = {}

    def hash(self, path):
        path = Path(path).resolve()
        key = str(path)
        if key in self.files:
            return self.files[key]["sha256"]
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
        require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
                f"Input changed while hashing: {path}")
        self.files[key] = {"sha256": digest.hexdigest(), "bytes": after.st_size, "mtime_ns": after.st_mtime_ns}
        return digest.hexdigest()

    def unchanged(self):
        for filename, item in self.files.items():
            stat = Path(filename).stat()
            require((stat.st_size, stat.st_mtime_ns) == (item["bytes"], item["mtime_ns"]),
                    f"Input changed during postflight: {filename}")


def git_blob_sha(path):
    path = Path(path)
    digest = hashlib.sha1(f"blob {path.stat().st_size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def native_table(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        prefix = []
        for header in reader:
            if header and header[0] == "[run number]":
                break
            prefix.extend(header)
        else:
            raise ValueError(f"Missing BehaviorSpace header: {path}")
        require(any("NetLogo 7.0.3" in value for value in prefix), f"Unexpected native version: {path}")
        require(len(header) == len(set(header)), f"Duplicate CSV columns: {path}")
        yield header, csv.DictReader(stream, fieldnames=header)


def case_key(row, policy_column=None, aliases=None):
    policy = row[policy_column] if policy_column else ""
    if aliases:
        policy = aliases[policy]
    return (int(Decimal(row["run-seed"])), row["world-mode"], row["peer-sharing?"].lower(), policy)


def model_path(index):
    candidates = list((ROOT / "models" / f"experiment_{index}").glob("*.nlogox"))
    require(len(candidates) == 1, f"Ambiguous model for experiment {index}")
    return candidates[0]


def value_set_values(element):
    if element.tag == "enumeratedValueSet":
        return [x.get("value").strip('"') for x in element]
    require(element.tag == "steppedValueSet", f"Unsupported value set {element.tag}")
    first, step, last = (Decimal(element.get(name)) for name in ("first", "step", "last"))
    require(step > 0 and last >= first, "Invalid stepped seed grid")
    return [str(first + step * i) for i in range(int((last - first) // step) + 1)]


def experiment_spec(index, name, seeds=None):
    experiment = next((x for x in ET.parse(model_path(index)).findall("./experiments/experiment")
                       if x.get("name") == name), None)
    require(experiment is not None, f"Experiment missing from model: {name}")
    values = {x.get("variable"): value_set_values(x) for x in experiment.find("constants")}
    if seeds is not None:  # Used only by bounded fixture checks; CLI always requests the complete original grid.
        allowed = {int(Decimal(value)) for value in values["run-seed"]}
        require(set(seeds) <= allowed, "Subset fixture requested an out-of-protocol seed")
        values["run-seed"] = list(map(str, seeds))
    policy = "evidence-policy" if index == 1 else "credence-policy" if index == 2 else None
    keys = set()
    for combination in itertools.product(*values.values()):
        row = dict(zip(values, combination))
        keys.add(case_key(row, policy))
    repetitions = int(experiment.get("repetitions", "1"))
    require(repetitions == 1, "This audit expects the baseline's one repetition per grid cell")
    trajectory = experiment.get("runMetricsEveryStep") == "true"
    ticks = 25 if "calibration" in name else 500
    return {"name": name, "index": index, "policy": policy, "values": values, "grid": keys,
            "runs": len(keys), "rows": len(keys) * (ticks + 1 if trajectory else 1),
            "trajectory": trajectory, "ticks": ticks,
            "metrics": [x.text for x in experiment.findall("./metrics/metric")]}


def audit_native_table(path, spec):
    """Independently check a complete native table using O(number of runs) state."""
    states, observed, endpoints = {}, set(), {}
    row_count, maximum_identity_error = 0, 0.0
    with native_table(path) as (columns, rows):
        required = set(spec["values"]) | set(spec["metrics"]) | {"[run number]", "[step]"}
        require(required <= set(columns), f"Missing native columns in {path}: {sorted(required - set(columns))}")
        error_fields = [x for x in columns if x.startswith("maximum-") and x.endswith("-error")]
        valid_fields = [x for x in columns if x.endswith("valid?")]
        for row in rows:
            row_count += 1
            require(None not in row and all(value is not None and value != "" for value in row.values()),
                    f"Truncated/malformed row {row_count}: {path}")
            key = case_key(row, spec["policy"])
            require(key in spec["grid"], f"Unexpected native setting {key}: {path}")
            run_id = int(Decimal(row["[run number]"]))
            step = int(Decimal(row["[step]"]))
            require(Decimal(row["[step]"]) == step, f"Fractional BehaviorSpace step: {path}")
            if run_id not in states:
                require(key not in observed, f"Duplicate native grid cell {key}: {path}")
                observed.add(key)
                states[run_id] = [key, 0]
            state = states[run_id]
            require(state[0] == key, f"Native settings changed inside run {run_id}: {path}")
            expected_step = state[1] if spec["trajectory"] else spec["ticks"]
            require(step == expected_step, f"Missing/duplicate/out-of-order step in {path}, {key}: {step} vs {expected_step}")
            state[1] += 1
            for column, value in row.items():
                try:
                    numeric = float(value)
                except ValueError:
                    continue
                require(math.isfinite(numeric), f"Nonfinite native metric {column}: {path}")
            for column in error_fields:
                error = abs(float(row[column]))
                maximum_identity_error = max(maximum_identity_error, error)
                require(error < TOLERANCE, f"Native identity failed {column}={error}: {path}")
            require(all(row[column] == "true" for column in valid_fields), f"False native validity reporter: {path}, {key}, {step}")
            require(int(Decimal(row["ticks"])) == step, f"Native tick/step mismatch: {path}")
            require(int(Decimal(row["actual-seed"])) == key[0], f"Native actual seed mismatch: {path}")
            require(row["hidden-world"] == key[1], f"Native actual world mismatch: {path}")
            if "expert-total-pulls" in row:
                require(float(row["expert-total-pulls"]) == 5 * min(step, 25), f"Expert pull count mismatch: {path}")
            if "total-lay-pulls" in row:
                require(float(row["total-lay-pulls"]) == 10 * step, f"Lay pull count mismatch: {path}")
            if step == spec["ticks"] and "calibration" not in spec["name"]:
                endpoints[key] = row
    expected_steps = spec["ticks"] + 1 if spec["trajectory"] else 1
    require(observed == spec["grid"], f"Incomplete native grid: {path}; {len(observed)}/{len(spec['grid'])}")
    require(all(state[1] == expected_steps for state in states.values()), f"Incomplete native step sequence: {path}")
    require(row_count == spec["rows"] and len(states) == spec["runs"], f"Native totals mismatch: {path}")
    return {"runs": len(states), "rows": row_count, "final_tick": spec["ticks"],
            "trajectory": spec["trajectory"], "maximum_identity_error": maximum_identity_error,
            "columns": columns}, endpoints


def compare_fields(actual, expected, columns, context, tolerance=TOLERANCE, ignored=()):
    maximum, compared = 0.0, 0
    for column in columns:
        if column in ignored:
            continue
        a, b = actual[column], expected[column]
        try:
            na, nb = float(a), float(b)
        except ValueError:
            require(a == b, f"Text mismatch {context}, {column}: {a!r} vs {b!r}")
        else:
            if math.isnan(na) and math.isnan(nb):
                continue
            require(math.isfinite(na) and math.isfinite(nb), f"Nonfinite comparison {context}, {column}")
            difference = abs(na - nb)
            maximum = max(maximum, difference)
            require(difference <= tolerance, f"Numeric mismatch {context}, {column}: {a} vs {b} (difference {difference})")
        compared += 1
    return compared, maximum


def endpoint_index(path, policy=None, aliases=None):
    result = {}
    with native_table(path) as (_, rows):
        for row in rows:
            if int(Decimal(row["[step]"])) != 500:
                continue
            key = case_key(row, policy, aliases)
            require(key not in result, f"Duplicate endpoint key {key}: {path}")
            result[key] = row
    require(bool(result), f"No endpoints: {path}")
    return result


def compare_endpoints(actual, reference, label, complete=False, exact_schema=False):
    require(set(actual) <= set(reference), f"Unmatched endpoints: {label}")
    if complete:
        require(set(actual) == set(reference), f"Missing endpoints: {label}")
    checked, maximum, columns_seen = 0, 0.0, set()
    for key in sorted(actual):
        a, b = actual[key], reference[key]
        if exact_schema:
            require(set(a) == set(b), f"Endpoint schema changed: {label}")
        columns = (set(a) & set(b)) - {"[run number]", "evidence-policy", "credence-policy"}
        require(len(columns) > 10, f"Insufficient common endpoint fields: {label}")
        count, difference = compare_fields(a, b, sorted(columns), f"{label}/{key}")
        checked += count
        maximum = max(maximum, difference)
        columns_seen.update(columns)
    return {"comparison": label, "endpoints": len(actual), "field_comparisons": checked,
            "columns": sorted(columns_seen), "maximum_absolute_error": maximum,
            "ignored_columns": ["[run number]", "evidence-policy", "credence-policy"],
            "policy_keys_checked_separately": True}


def trajectory_regression(left_path, right_path, directory, label, left_policy=None, right_policy=None,
                          left_allowed=None, right_allowed=None, left_aliases=None, right_aliases=None,
                          expected_rows=None):
    """Compare by seed/world/sharing/policy/tick without keeping trajectories in RAM."""
    with native_table(left_path) as (left_columns, _), native_table(right_path) as (right_columns, _):
        columns = sorted((set(left_columns) & set(right_columns)) -
                         {"[run number]", "evidence-policy", "credence-policy"})
    require(len(columns) > 10, f"Insufficient shared trajectory fields: {label}")
    temporary = tempfile.NamedTemporaryFile(prefix="regression_", suffix=".sqlite3", dir=directory, delete=False)
    database = Path(temporary.name)
    temporary.close()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA cache_size=-65536")
    connection.execute("CREATE TABLE paired (k TEXT PRIMARY KEY, payload TEXT NOT NULL, visited INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID")
    inserted = compared = fields = 0
    maximum = 0.0
    def index_key(row, policy, aliases):
        return json.dumps((*case_key(row, policy, aliases), int(Decimal(row["[step]"]))), separators=(",", ":"))
    try:
        batch = []
        with native_table(left_path) as (_, rows):
            for row in rows:
                if left_allowed is not None and row[left_policy] not in left_allowed:
                    continue
                batch.append((index_key(row, left_policy, left_aliases), json.dumps({c: row[c] for c in columns}, separators=(",", ":"))))
                inserted += 1
                if len(batch) >= 2000:
                    connection.executemany("INSERT INTO paired (k,payload) VALUES (?,?)", batch)
                    batch.clear()
            if batch:
                connection.executemany("INSERT INTO paired (k,payload) VALUES (?,?)", batch)
        connection.commit()
        with native_table(right_path) as (_, rows):
            for row in rows:
                if right_allowed is not None and row[right_policy] not in right_allowed:
                    continue
                key = index_key(row, right_policy, right_aliases)
                reference = connection.execute("SELECT payload,visited FROM paired WHERE k=?", (key,)).fetchone()
                require(reference is not None and reference[1] == 0, f"Unmatched/duplicate trajectory row {label}: {key}")
                count, difference = compare_fields(row, json.loads(reference[0]), columns, f"{label}/{key}")
                fields += count
                maximum = max(maximum, difference)
                connection.execute("UPDATE paired SET visited=1 WHERE k=?", (key,))
                compared += 1
        missing = connection.execute("SELECT count(*) FROM paired WHERE visited=0").fetchone()[0]
        require(inserted == compared and missing == 0, f"Incomplete trajectory regression: {label}")
        if expected_rows is not None:
            require(compared == expected_rows, f"Wrong full-grid regression count: {label}: {compared}/{expected_rows}")
        return {"comparison": label, "paired_rows": compared, "field_comparisons": fields,
                "columns": columns, "maximum_absolute_error": maximum,
                "alignment": "seed, world, sharing, mapped policy, tick; independent of native run order",
                "sqlite_cache_limit_mib": 64}
    finally:
        connection.close()
        database.unlink(missing_ok=True)


def analysis_command_paths(run_root):
    raw = run_root / "raw"
    scripts = ROOT / "scripts" / "analysis"
    published = ROOT / "data" / "experiment_2"
    analysis = run_root / "analysis"
    return {
        "calibration": [scripts / "calibrate_opaque_credence.R",
                        *(raw / "experiment_2" / f"calibration_{phase}_{world}_raw.csv"
                          for phase in ("estimate", "heldout") for world in ("good", "bad")), analysis / "calibration"],
        "0": [scripts / "analyze_experiment_0_bandit.R", raw / "experiment_0/raw_main_final.csv",
              raw / "experiment_0/raw_trajectories.csv", raw / "experiment_0/raw_peer_check.csv", analysis / "experiment_0"],
        "1": [scripts / "analyze_experiment_1_evidence.R", raw / "experiment_1/raw_main_final.csv",
              raw / "experiment_1/raw_trajectories.csv", raw / "experiment_0/raw_main_final.csv",
              raw / "experiment_0/raw_trajectories.csv", analysis / "experiment_1"],
        "1-figures": [scripts / "make_static_figures.R", analysis / "experiment_1"],
        "2": [scripts / "analyze_experiment_2_opaque_credence.R", raw / "experiment_2/raw_main_final.csv",
              raw / "experiment_2/raw_trajectories.csv", raw / "experiment_2/raw_exact_trajectories.csv",
              raw / "experiment_1/raw_trajectories.csv", published / "frozen_credence_message_table.csv",
              published / "heldout_calibration_audit.csv", analysis / "experiment_2"],
    }


def verify_analysis_commands(receipt, run_root, file_audit):
    expected = analysis_command_paths(run_root)
    require([s.get("experiment") for s in receipt["steps"]] == list(expected), "Analysis stage order differs")
    executable = None
    checked = []
    for step in receipt["steps"]:
        name, command = step["experiment"], step.get("command", [])
        require(len(command) == len(expected[name]) + 1, f"Analysis command arity differs: {name}")
        # Path.resolve on Windows expands existing 8.3 short paths used by the
        # frozen R wrapper, so this compares actual targets rather than spelling.
        actual = [Path(value).resolve() for value in command]
        require(actual[0].is_file() and actual[0].name.lower() in ("rscript.exe", "rscript"),
                f"Unexpected Rscript executable: {name}")
        if executable is None:
            executable = actual[0]
        require(actual[0] == executable, f"Rscript executable changed between stages: {name}")
        require(actual[1:] == [path.resolve() for path in expected[name]],
                f"Analysis stage used unexpected script/input/output paths: {name}")
        file_audit.hash(actual[0])
        checked.append({"stage": name, "rscript": str(actual[0]), "script": str(actual[1]),
                        "input_paths": [str(path) for path in actual[2:-1]], "output_path": str(actual[-1])})
    return checked


def audit_analysis(run_root, file_audit, raw_hashes):
    receipt_path = run_root / "analysis" / "analysis_receipt.json"
    receipt = load_json(receipt_path)
    file_audit.hash(receipt_path)
    require(receipt.get("status") == "passed" and receipt.get("scientific_parameters_changed") is False,
            "R analysis receipt did not pass the unchanged protocol")
    expected_steps = ["calibration", "0", "1", "1-figures", "2"]
    require([s.get("experiment") for s in receipt["steps"]] == expected_steps and
            all(s.get("returncode") == 0 for s in receipt["steps"]), "Analysis command/exit sequence differs")
    checked_commands = verify_analysis_commands(receipt, run_root, file_audit)
    validation_counts = {s["experiment"]: s.get("original_validation_checks_passed") for s in receipt["steps"]}
    require({k: validation_counts[k] for k in ("calibration", "0", "1-figures", "2")} ==
            {"calibration": 13, "0": 36, "1-figures": 33, "2": 21}, "Original R check counts differ")
    expected_inputs = dict(raw_hashes)
    for name in ("frozen_credence_message_table.csv", "heldout_calibration_audit.csv"):
        path = ROOT / "data" / "experiment_2" / name
        expected_inputs[str(path.resolve())] = file_audit.hash(path)
    actual_inputs = {str(Path(path).resolve()): digest for path, digest in receipt["input_sha256"].items()}
    require(actual_inputs == expected_inputs, "Analysis inputs are not exactly the 12 newly generated native files plus two frozen published calibration files")
    require(receipt.get("analysis_driver_sha256") == file_audit.hash(ROOT / "scripts/analysis/run_analysis.py"),
            "Analysis driver hash mismatch")
    for name, digest in receipt["recovered_script_sha256"].items():
        require(file_audit.hash(ROOT / "scripts" / "analysis" / name) == digest, f"Recovered R source changed: {name}")
    records = []
    for folder, exp, name, expected_rows in ANALYSIS_FILES:
        actual = run_root / "analysis" / folder / name
        published = ROOT / "data" / f"experiment_{exp}" / name
        file_audit.hash(actual)
        file_audit.hash(published)
        with actual.open(encoding="utf-8-sig", newline="") as aa, published.open(encoding="utf-8-sig", newline="") as bb:
            ar, br = csv.DictReader(aa), csv.DictReader(bb)
            require(ar.fieldnames is not None and set(ar.fieldnames) == set(br.fieldnames), f"Analysis schema mismatch: {folder}/{name}")
            ignored = ("table_version",) if name == "frozen_credence_message_table.csv" else ()
            count = fields = 0
            maximum = 0.0
            for count, pair in enumerate(itertools.zip_longest(ar, br), 1):
                a, b = pair
                require(a is not None and b is not None, f"Analysis row-count mismatch: {folder}/{name}")
                compared, difference = compare_fields(a, b, ar.fieldnames, f"{folder}/{name}/{count}", tolerance=0.0, ignored=ignored)
                fields += compared
                maximum = max(maximum, difference)
            require(count == expected_rows, f"Analysis expected rows differ: {folder}/{name}")
        records.append({"folder": folder, "file": name, "rows": count, "field_comparisons": fields,
                        "maximum_absolute_error": maximum, "ignored_metadata_columns": list(ignored)})
    expected_receipt = Counter((x["file"], x["rows"], x["maximum_absolute_error"], tuple(x["ignored_metadata_columns"])) for x in records)
    actual_receipt = Counter((x["file"], x["rows"], x["maximum_absolute_error"], tuple(x["ignored_metadata_columns"]))
                             for x in receipt.get("published_csv_comparisons", []))
    require(len(records) == 13 and actual_receipt == expected_receipt, "Analysis receipt does not certify exactly the 13 independently compared CSVs with zero numerical difference")
    return {"status": "passed", "published_csv_comparisons": records, "new_raw_inputs": 12,
            "deliberate_published_inputs": 2, "original_checks": validation_counts,
            "checked_stage_commands": checked_commands,
            "rscript_version": receipt.get("rscript_version"),
            "metadata_exception": "Only frozen table_version may differ (prehash-v1 versus published hash label)."}


def credence_bin(q):
    if q <= 0:
        return 0
    if q >= 1:
        return 9
    return min(9, math.floor(10 * q))


def calibration_bin_counts(path):
    counts, seeds = [0] * 10, set()
    lowest, highest = 1.0, 0.0
    with native_table(path) as (columns, rows):
        required = {"actual-seed", "ticks", "expert-total-pulls", "calibration-expert-q", "calibration-message-bin"}
        require(required <= set(columns), f"Missing independent calibration columns: {path}")
        for row in rows:
            q = float(row["calibration-expert-q"])
            require(math.isfinite(q) and 0 < q < 1, f"Invalid calibration credence: {path}")
            recorded_bin = int(Decimal(row["calibration-message-bin"]))
            require(Decimal(row["calibration-message-bin"]) == recorded_bin == credence_bin(q),
                    f"Fresh calibration q/bin mismatch: {path}, q={q}, bin={row['calibration-message-bin']}")
            require(float(row["ticks"]) == 25 and float(row["expert-total-pulls"]) == 125,
                    f"Fresh calibration budget mismatch: {path}")
            seed = int(Decimal(row["actual-seed"]))
            require(seed not in seeds, f"Duplicate independent calibration seed: {path}")
            seeds.add(seed)
            counts[recorded_bin] += 1
            lowest, highest = min(lowest, q), max(highest, q)
    require(bool(seeds), f"Empty calibration file: {path}")
    return {"rows": sum(counts), "counts_by_bin": counts, "q_minimum": lowest, "q_maximum": highest,
            "seed_minimum": min(seeds), "seed_maximum": max(seeds), "all_q_bins_independently_checked": True}, seeds


def calibration_tables(counts):
    """Independently derive Jeffreys-smoothed testimony and unsmoothed heldout audit."""
    eg, eb, hg, hb = (counts[name] for name in ("estimate_good", "estimate_bad", "heldout_good", "heldout_bad"))
    ng, nb, nhg, nhb = map(sum, (eg, eb, hg, hb))
    require(all(n > 0 for n in (ng, nb, nhg, nhb)), "Empty calibration count vector")
    frozen, heldout = [], []
    z = 1.95996398454005
    for k in range(10):
        pg, pb = (eg[k] + .5) / (ng + 5), (eb[k] + .5) / (nb + 5)
        lam = math.log(pg / pb)
        implied = pg / (pg + pb)
        se = math.sqrt((1 - pg) / ((ng + 5) * pg) + (1 - pb) / ((nb + 5) * pb))
        frozen.append({"message_bin": k, "lower": k / 10, "upper": (k + 1) / 10, "midpoint": k / 10 + .05,
                       "estimate_count_good": eg[k], "estimate_count_bad": eb[k], "estimate_n_good": ng, "estimate_n_bad": nb,
                       "p_message_given_good": pg, "p_message_given_bad": pb, "message_lambda": lam,
                       "lambda_mc_se": se, "implied_p_good_given_message": implied})
        n = hg[k] + hb[k]
        require(n > 0, f"Empty heldout message category {k}")
        empirical = hg[k] / n
        denominator = 1 + z * z / n
        center = (empirical + z * z / (2 * n)) / denominator
        half = z * math.sqrt(empirical * (1 - empirical) / n + z * z / (4 * n * n)) / denominator
        heldout.append({"message_bin": k, "midpoint": k / 10 + .05,
                        "heldout_count_good": hg[k], "heldout_count_bad": hb[k],
                        "heldout_p_message_given_good": hg[k] / nhg, "heldout_p_message_given_bad": hb[k] / nhb,
                        "frozen_implied_p_good": implied, "heldout_empirical_p_good": empirical,
                        "wilson_low": max(0, center - half), "wilson_high": min(1, center + half),
                        "absolute_calibration_gap": abs(empirical - implied)})
    return frozen, heldout


def compare_calibration_tables(derived, reference, label):
    require(len(derived) == len(reference) == 10, f"Calibration category count differs: {label}")
    reference = {int(row["message_bin"]): row for row in reference}
    require(set(reference) == set(range(10)), f"Calibration category IDs differ: {label}")
    count = 0
    maximum = 0.0
    for row in derived:
        expected = reference[row["message_bin"]]
        for field in row:
            if "count_" in field or field.startswith("estimate_n_") or field == "message_bin":
                require(Decimal(str(row[field])) == Decimal(expected[field]), f"Fresh integer calibration count differs: {label}/{field}")
        checked, difference = compare_fields({key: str(value) for key, value in row.items()}, expected,
                                              sorted(row), f"independent {label}/bin{row['message_bin']}", tolerance=1e-12)
        count += checked
        maximum = max(maximum, difference)
    return {"table": label, "categories": 10, "field_comparisons": count,
            "maximum_absolute_error": maximum, "integer_counts_exact": True, "floating_tolerance": 1e-12}


def audit_calibration(run_root, file_audit):
    summaries, counts, all_seeds = {}, {}, set()
    for phase in ("estimate", "heldout"):
        for world in ("good", "bad"):
            label = f"{phase}_{world}"
            path = run_root / "raw" / "experiment_2" / f"calibration_{label}_raw.csv"
            file_audit.hash(path)
            summary, seeds = calibration_bin_counts(path)
            require(summary["rows"] == (50000 if phase == "estimate" else 10000), f"Fresh calibration row count differs: {label}")
            require(not (all_seeds & seeds), f"Fresh calibration seed namespaces overlap: {label}")
            all_seeds.update(seeds)
            summaries[label], counts[label] = summary, summary["counts_by_bin"]
    frozen, heldout = calibration_tables(counts)
    comparisons = []
    for name, derived in (("frozen_credence_message_table.csv", frozen), ("heldout_calibration_audit.csv", heldout)):
        path = ROOT / "data" / "experiment_2" / name
        file_audit.hash(path)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            comparisons.append(compare_calibration_tables(derived, list(csv.DictReader(stream)), name))
    tv_good = .5 * sum(abs(h["heldout_p_message_given_good"] - f["p_message_given_good"]) for f, h in zip(frozen, heldout))
    tv_bad = .5 * sum(abs(h["heldout_p_message_given_bad"] - f["p_message_given_bad"]) for f, h in zip(frozen, heldout))
    maximum_bin_probability_gap = max(abs(h[hp] - f[fp]) for f, h in zip(frozen, heldout)
                                      for hp, fp in (("heldout_p_message_given_good", "p_message_given_good"),
                                                     ("heldout_p_message_given_bad", "p_message_given_bad")))
    weighted_gap = sum((h["heldout_count_good"] + h["heldout_count_bad"]) * h["absolute_calibration_gap"] for h in heldout) / 20000
    checks = {"estimate_rows_per_world_50000": all(summaries[f"estimate_{w}"]["rows"] == 50000 for w in ("good", "bad")),
              "heldout_rows_per_world_10000": all(summaries[f"heldout_{w}"]["rows"] == 10000 for w in ("good", "bad")),
              "all_expert_runs_have_125_pulls": True, "calibration_seed_namespaces_disjoint": len(all_seeds) == 120000,
              "minimum_estimate_cell_count_at_least_200": min(counts["estimate_good"] + counts["estimate_bad"]) >= 200,
              "smoothed_good_probabilities_sum_to_one": abs(sum(f["p_message_given_good"] for f in frozen) - 1) < 1e-12,
              "smoothed_bad_probabilities_sum_to_one": abs(sum(f["p_message_given_bad"] for f in frozen) - 1) < 1e-12,
              "all_message_lambdas_finite": all(math.isfinite(f["message_lambda"]) for f in frozen),
              "message_lambda_monotone_in_bin": all(a["message_lambda"] <= b["message_lambda"] for a, b in zip(frozen, frozen[1:])),
              "heldout_total_variation_good_at_most_003": tv_good <= .03,
              "heldout_total_variation_bad_at_most_003": tv_bad <= .03,
              "heldout_max_bin_probability_gap_at_most_002": maximum_bin_probability_gap <= .02,
              "heldout_weighted_calibration_gap_at_most_003": weighted_gap <= .03}
    require(len(checks) == 13 and all(checks.values()), "Independent fresh-raw calibration failed original thresholds")
    return {"status": "passed", "raw_runs_recounted": 120000, "source_counts": summaries,
            "derived_table_comparisons": comparisons, "independent_original_checks": checks,
            "heldout_total_variation_good": tv_good, "heldout_total_variation_bad": tv_bad,
            "heldout_maximum_bin_probability_gap": maximum_bin_probability_gap,
            "heldout_weighted_calibration_gap": weighted_gap,
            "method": "q -> floor(10q) category, exact counts, Jeffreys .5 probabilities, independent log ratio/SE/posterior and Wilson interval"}


def preflight_paths(run_root):
    paths = [run_root / "pipeline.json", run_root / "analysis/analysis_receipt.json"]
    for index, _, name in JOBS:
        raw = run_root / "raw" / f"experiment_{index}" / name
        paths.extend((raw, Path(str(raw) + ".provenance.json"), Path(str(raw) + ".log")))
    paths.extend(run_root / "analysis" / folder / name for folder, _, name, _ in ANALYSIS_FILES)
    missing = [str(path) for path in paths if not path.is_file()]
    pending = []
    for path in paths:
        if path.is_file() and (path.name == "pipeline.json" or path.name.endswith(".provenance.json") or path.name == "analysis_receipt.json"):
            try:
                item = load_json(path)
            except (ValueError, OSError):
                pending.append({"path": str(path), "status": "unreadable/incomplete JSON"})
                continue
            if item.get("status") != "passed":
                pending.append({"path": str(path), "status": item.get("status"), "error": item.get("error")})
    return missing, pending


def verify(run_root, output):
    file_audit = FileAudit()
    report = {"schema_version": 1, "status": "running", "run_root": str(run_root),
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Independent postflight of newly regenerated full native grids, run-key endpoints, every-tick regressions and 13 R outputs",
              "runs_launched": 0, "scientific_sources_modified": False,
              "numeric_tolerance_raw": TOLERANCE, "numeric_tolerance_analysis": 0.0,
              "batches": [], "endpoint_comparisons": [], "trajectory_regressions": []}
    target = output / "full_reproduction_verification.json"
    exit_code = 1
    try:
        missing, pending = preflight_paths(run_root)
        if missing or pending:
            failed_upstream = any(item.get("status") == "failed" for item in pending)
            report.update(status="failed" if failed_upstream else "incomplete", missing_files=missing, incomplete_receipts=pending)
            exit_code = 1 if failed_upstream else 2
            return exit_code
        pipeline = load_json(run_root / "pipeline.json")
        file_audit.hash(run_root / "pipeline.json")
        require(pipeline.get("command") == "reproduce" and pipeline.get("scientific_parameters_changed") is False,
                "Pipeline is not a full unchanged-protocol reproduction")
        expected_steps = ["model", "verifier_mutations", "statistics", "native", "native_baseline"] + [job[1] for job in JOBS] + ["analysis"]
        require([s["name"] for s in pipeline["steps"]] == expected_steps and
                all(s.get("returncode") == 0 for s in pipeline["steps"]), "Pipeline step list or exit codes do not certify every full batch")
        for step in pipeline["steps"]:
            file_audit.hash(run_root / step["log"])
        for name, digest in pipeline["sources"].items():
            require(file_audit.hash(ROOT / name) == digest, f"Pipeline source changed: {name}")
        manifest_path = ROOT / "source_manifest.json"
        file_audit.hash(manifest_path)
        manifest = load_json(manifest_path)
        require(pipeline.get("upstream") == manifest["ref"], "Pipeline pinned upstream ref changed")
        pinned = []
        for entry in manifest["files"]:
            if entry["path"].startswith(("models/", "data/")):
                path = ROOT / entry["path"]
                file_audit.hash(path)
                require(path.stat().st_size == entry["bytes"] and git_blob_sha(path) == entry["git_blob_sha"],
                        f"Pinned scientific source/data differs: {entry['path']}")
                pinned.append(entry["path"])
        require(len(pinned) == 23, f"Pinned scientific-file inventory differs: {len(pinned)}")
        report["source_integrity"] = {"upstream": manifest["ref"], "pipeline_snapshot_files": len(pipeline["sources"]),
                                      "pinned_model_and_data_files": len(pinned), "all_hashes_unchanged": True}
        raw_hashes, indexes = {}, {}
        for index, name, filename in JOBS:
            path = run_root / "raw" / f"experiment_{index}" / filename
            spec = experiment_spec(index, name)
            digest = file_audit.hash(path)
            raw_hashes[str(path.resolve())] = digest
            provenance_path = Path(str(path) + ".provenance.json")
            provenance = load_json(provenance_path)
            file_audit.hash(provenance_path)
            file_audit.hash(Path(str(path) + ".log"))
            require(provenance.get("status") == "passed" and provenance.get("exit_code") == 0 and
                    provenance.get("seed_subset_only") is False and provenance.get("experiment") == name,
                    f"Batch receipt is not a complete successful original grid: {name}")
            require(provenance.get("table_sha256") == digest, f"Native output hash changed: {name}")
            require(provenance.get("postflight", {}).get("passed") is True and
                    provenance["postflight"].get("native_version") == "NetLogo 7.0.3", f"Native postflight/version missing: {name}")
            require(sorted(provenance.get("seeds", [])) == sorted(int(Decimal(x)) for x in spec["values"]["run-seed"]),
                    f"Receipt seed range differs: {name}")
            for filename_source, item in provenance["sources"].items():
                require(file_audit.hash(Path(filename_source)) == item["sha256"], f"Native source changed: {filename_source}")
            model = model_path(index).resolve()
            require(str(model) in provenance["sources"], f"Native model provenance missing: {name}")
            command = provenance.get("command", [])
            require("--setup-file" not in command and command[command.index("--experiment") + 1] == name,
                    f"Full batch used a changed external setup: {name}")
            working_directory = Path(provenance["working_directory"])
            require((working_directory / command[command.index("--model") + 1]).resolve() == model and
                    (working_directory / command[command.index("--table") + 1]).resolve() == path.resolve() and
                    Path(provenance["output"]).resolve() == path.resolve(), f"Native command paths differ: {name}")
            require(file_audit.hash(Path(provenance["engine_jar"]["path"])) == provenance["engine_jar"]["sha256"],
                    f"NetLogo engine JAR changed: {name}")
            actual, endpoints = audit_native_table(path, spec)
            for field in ("runs", "rows", "trajectory"):
                require(provenance["postflight"].get(field) == actual[field], f"Native receipt {field} mismatch: {name}")
            require(provenance["postflight"].get("expected_ticks") == spec["ticks"], f"Native endpoint receipt mismatch: {name}")
            report["batches"].append({"experiment": name, "file": str(path), "sha256": digest,
                                      "status": "passed", **actual})
            if endpoints:
                indexes[(index, filename)] = endpoints
            print(f"Checked {name}: {actual['runs']:,} runs / {actual['rows']:,} rows", flush=True)
        totals = {"batches": len(report["batches"]), "runs": sum(b["runs"] for b in report["batches"]),
                  "rows": sum(b["rows"] for b in report["batches"]),
                  "trajectory_runs": sum(b["runs"] for b in report["batches"] if b["trajectory"]),
                  "trajectory_rows": sum(b["rows"] for b in report["batches"] if b["trajectory"])}
        require(totals == {"batches": 12, "runs": 132600, "rows": 1932600, "trajectory_runs": 3600, "trajectory_rows": 1803600},
                f"Complete reproduction totals differ: {totals}")
        report["totals"] = totals
        for index, filename in ((0, "raw_main_final.csv"), (0, "raw_peer_check.csv"),
                                (1, "raw_main_final.csv"), (2, "raw_main_final.csv")):
            baseline = ROOT / "data" / f"experiment_{index}" / filename
            file_audit.hash(baseline)
            policy = "evidence-policy" if index == 1 else "credence-policy" if index == 2 else None
            result = compare_endpoints(indexes[(index, filename)], endpoint_index(baseline, policy),
                                       f"E{index}/{filename} versus pinned published runs", complete=True, exact_schema=True)
            report["endpoint_comparisons"].append(result)
        require(sum(c["endpoints"] for c in report["endpoint_comparisons"]) == 9000, "Published endpoint comparison is incomplete")
        for index in range(3):
            report["endpoint_comparisons"].append(compare_endpoints(indexes[(index, "raw_trajectories.csv")],
                indexes[(index, "raw_main_final.csv")], f"E{index} trajectory tick 500 versus newly generated main endpoints"))
        exact_endpoints = {(seed, world, sharing, EXACT_ALIASES[policy]): row
                           for (seed, world, sharing, policy), row in indexes[(2, "raw_exact_trajectories.csv")].items()}
        report["endpoint_comparisons"].append(compare_endpoints(exact_endpoints, indexes[(1, "raw_main_final.csv")],
                                                               "E2 exact trajectory tick 500 versus newly generated E1 main endpoints"))
        raw = run_root / "raw"
        report["trajectory_regressions"].append(trajectory_regression(
            raw / "experiment_0/raw_trajectories.csv", raw / "experiment_1/raw_trajectories.csv", output,
            "E0 baseline versus E1 No Deference, all 200 seeds/world",
            right_policy="evidence-policy", right_allowed={"No Deference"}, right_aliases={"No Deference": ""}, expected_rows=200400))
        report["trajectory_regressions"].append(trajectory_regression(
            raw / "experiment_1/raw_trajectories.csv", raw / "experiment_2/raw_exact_trajectories.csv", output,
            "E1 raw evidence versus E2 exact regression, all 200 seeds/world/policy",
            left_policy="evidence-policy", right_policy="credence-policy",
            left_allowed={"E-Preemption", "E-Total Evidence"}, right_aliases=EXACT_ALIASES, expected_rows=400800))
        report["independent_calibration"] = audit_calibration(run_root, file_audit)
        report["analysis"] = audit_analysis(run_root, file_audit, raw_hashes)
        report["verifier"] = {"path": str(Path(__file__).resolve()), "sha256": file_audit.hash(Path(__file__)),
                              "separate_postflight_source": True, "not_in_upstream_pipeline_snapshot": str(Path(__file__).relative_to(ROOT)).replace("\\", "/") not in pipeline["sources"]}
        file_audit.unchanged()
        report["status"] = "passed"
        exit_code = 0
        return exit_code
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(report["error"], file=sys.stderr, flush=True)
        return 1
    finally:
        report["input_files"] = file_audit.files
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Full reproduction postflight {report['status']}: {target}", flush=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_root, output = args.run_root.resolve(), args.output_dir.resolve()
    if output.exists():
        parser.error("Refusing to overwrite an existing postflight directory")
    for protected in (ROOT / "data", ROOT / "models", ROOT / "scripts"):
        if output == protected or protected in output.parents:
            parser.error("Postflight outputs must be separate from scientific sources and scripts")
    if output == run_root:
        parser.error("Use a separate postflight directory")
    output.mkdir(parents=True)
    return verify(run_root, output)


if __name__ == "__main__":
    raise SystemExit(main())
