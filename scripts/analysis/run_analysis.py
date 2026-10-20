"""Run recovered baseline R analyses; never substitute chart aggregates for raw paths."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
LEGACY = {
    0: "experiment_0_bandit_base_report",
    1: "experiment_1_evidence_bandit_report",
    2: "experiment_2_opaque_credence_report",
}


def safe_r_path(value: str | Path) -> str:
    """Avoid legacy Rscript command-line decoding of non-ASCII Windows paths."""
    value = str(value)
    if os.name == "nt" and Path(value).exists():
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        count = ctypes.windll.kernel32.GetShortPathNameW(value, buffer, len(buffer))
        if count and buffer.value.isascii():
            return buffer.value
    return value


def r_environment() -> dict[str, str]:
    env = os.environ.copy()
    if os.name == "nt":
        # A Unix C.UTF-8 inherited from the host is not a Windows R locale.
        # Let current Windows R select its native UTF-8 locale instead.
        for key in list(env):
            if key.startswith("LC_") or key in ("LANG", "LANGUAGE"):
                env.pop(key)
    return env


def compare_csv(actual: Path, published: Path, ignored: tuple[str, ...] = ()) -> dict:
    def read(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as h:
            return list(csv.DictReader(h))
    aa, bb = read(actual), read(published)
    if len(aa) != len(bb) or not aa or set(aa[0]) != set(bb[0]):
        raise ValueError(f"Published comparison schema/count mismatch: {actual.name}")
    maximum = 0.0
    for index, (a, b) in enumerate(zip(aa, bb), 1):
        for column in a:
            if column in ignored:
                continue
            try:
                x, y = float(a[column]), float(b[column])
            except ValueError:
                if a[column] != b[column]:
                    raise ValueError(f"Published text mismatch: {actual.name}:{index}:{column}")
            else:
                if x != x and y != y:
                    continue
                difference = abs(x - y)
                maximum = max(maximum, difference)
                if difference > 1e-10 * max(1.0, abs(y)):
                    raise ValueError(f"Published numeric mismatch: {actual.name}:{index}:{column}: {x} vs {y}")
    return {"file": actual.name, "rows": len(aa), "maximum_absolute_error": maximum,
            "ignored_metadata_columns": list(ignored)}


def find_rscript(explicit: str | None) -> str:
    if explicit:
        resolved = shutil.which(explicit) or explicit
        if Path(resolved).is_file():
            return str(Path(resolved).resolve())
        raise FileNotFoundError(f"Rscript does not exist: {explicit}")
    discovered = shutil.which("Rscript")
    if discovered:
        return discovered
    candidates = sorted(Path("C:/Program Files/R").glob("R-*/bin/Rscript.exe"))
    if candidates:
        return str(candidates[-1])
    raise FileNotFoundError("Rscript was not found; supply --rscript. Baseline analyses used R 4.5.3.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment", choices=["0", "1", "2", "calibration", "all"], required=True)
    p.add_argument("--raw-root", type=Path, required=True, help="Directory containing experiment_0/1/2 raw exports")
    p.add_argument("--output-root", type=Path, default=PROJECT / "results" / "analysis")
    p.add_argument("--rscript")
    args = p.parse_args()
    raw_root, output_root = args.raw_root.resolve(), args.output_root.resolve()
    if output_root == PROJECT / "data" or (PROJECT / "data") in output_root.parents:
        p.error("Analysis output must be separate from published data/.")
    if output_root.exists() and any(output_root.iterdir()):
        p.error("Output root is not empty; choose a fresh directory to preserve earlier results.")
    rscript = find_rscript(args.rscript)
    requested = ["calibration", "0", "1", "2"] if args.experiment == "all" else [args.experiment]
    commands = []
    input_paths: set[Path] = set()

    def raw(exp: int, name: str) -> Path:
        aliases = [name]
        if name == "raw_exact_trajectories.csv":
            aliases.append("raw_exact_regression_trajectories.csv")
        candidates = [raw_root / f"experiment_{exp}" / n for n in aliases]
        candidates += [raw_root / LEGACY[exp] / n for n in aliases]
        if name in ("raw_main_final.csv", "raw_peer_check.csv"):
            candidates.append(PROJECT / "data" / f"experiment_{exp}" / name)
        for path in candidates:
            if path.is_file():
                if output_root == path.parent or output_root in path.parents:
                    raise ValueError("Output directory contains an analysis input.")
                input_paths.add(path)
                return path
        raise FileNotFoundError(
            f"Missing raw export: {candidates[0]}. Full per-run trajectories must be regenerated "
            "with the model's BehaviorSpace trajectory experiment; published trajectory summaries "
            "cannot reconstruct individual recovery delays."
        )

    # Resolve every required input before invoking an R script or writing a result.
    for exp in requested:
        out = output_root / ("calibration" if exp == "calibration" else f"experiment_{exp}")
        if exp == "calibration":
            inputs = [raw(2, f"calibration_{phase}_{world}_raw.csv")
                      for phase in ("estimate", "heldout") for world in ("good", "bad")]
            script = "calibrate_opaque_credence.R"
        elif exp == "0":
            inputs = [raw(0, "raw_main_final.csv"), raw(0, "raw_trajectories.csv"), raw(0, "raw_peer_check.csv")]
            script = "analyze_experiment_0_bandit.R"
        elif exp == "1":
            inputs = [raw(1, "raw_main_final.csv"), raw(1, "raw_trajectories.csv"),
                      raw(0, "raw_main_final.csv"), raw(0, "raw_trajectories.csv")]
            script = "analyze_experiment_1_evidence.R"
        else:
            frozen = PROJECT / "data/experiment_2/frozen_credence_message_table.csv"
            heldout = PROJECT / "data/experiment_2/heldout_calibration_audit.csv"
            input_paths.update((frozen, heldout))
            inputs = [raw(2, "raw_main_final.csv"), raw(2, "raw_trajectories.csv"),
                      raw(2, "raw_exact_trajectories.csv"), raw(1, "raw_trajectories.csv"), frozen, heldout]
            script = "analyze_experiment_2_opaque_credence.R"
        commands.append((exp, out, [rscript, str(HERE / script), *map(str, inputs), str(out)]))

    output_root.mkdir(parents=True, exist_ok=True)
    receipt = {"status": "running", "scientific_parameters_changed": False,
               "input_sha256": {str(x): hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(input_paths)},
               "steps": [], "scope": "Existing raw-data analysis only; no simulation is launched."}
    receipt["rscript_version"] = subprocess.run([rscript, "--version"], env=r_environment(),
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    receipt["recovered_script_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(HERE.glob("*.R"))}
    receipt["analysis_driver_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt["published_csv_comparisons"] = []
    receipt_path = output_root / "analysis_receipt.json"
    try:
        for exp, out, command in commands:
            out.mkdir(parents=True, exist_ok=True)
            command = [safe_r_path(x) for x in command]
            result = subprocess.run(command, cwd=out, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", env=r_environment())
            (out / "analysis.log").write_text(result.stdout, encoding="utf-8")
            receipt["steps"].append({"experiment": exp, "command": command,
                                     "returncode": result.returncode, "log": str(out / "analysis.log")})
            if result.returncode:
                raise RuntimeError(f"R analysis {exp} failed; inspect {out / 'analysis.log'}")
            if exp == "1":
                # The original plot script reads relative inputs. Supply its exact
                # filtered table and execute it from the new analysis directory.
                with (out / "paired_contrasts.csv").open(encoding="utf-8-sig", newline="") as h:
                    rows = list(csv.DictReader(h))
                with (out / "report_source_regret_contrasts.csv").open("w", encoding="utf-8", newline="") as h:
                    writer = csv.DictWriter(h, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(r for r in rows if r["metric"] == "post_regret")
                plot_command = [safe_r_path(x) for x in [rscript, str(HERE / "make_static_figures.R"), str(out)]]
                result = subprocess.run(plot_command, cwd=out, text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", env=r_environment())
                (out / "figures.log").write_text(result.stdout, encoding="utf-8")
                receipt["steps"].append({"experiment": "1-figures", "command": plot_command,
                                         "returncode": result.returncode})
                if result.returncode:
                    raise RuntimeError(f"Experiment 1 figure generation failed; inspect {out / 'figures.log'}")
            if exp == "calibration":
                receipt["calibration_note"] = (
                    "The recovered script labels its newly computed table prehash-v1. "
                    "This output is for comparison; the published frozen table and model are never patched."
                )
            published_dir = PROJECT / "data" / ("experiment_2" if exp == "calibration" else f"experiment_{exp}")
            check_file = out / ("calibration_validation_checks.csv" if exp == "calibration" else "validation_checks.csv")
            with check_file.open(encoding="utf-8-sig", newline="") as h:
                check_rows = list(csv.DictReader(h))
            pass_column = "passed" if "passed" in check_rows[0] else "pass"
            if not all(row[pass_column].lower() == "true" for row in check_rows):
                raise ValueError(f"Recovered analysis {exp} produced failed original checks: {check_file}")
            receipt["steps"][-1]["original_validation_checks_passed"] = len(check_rows)
            for actual in sorted(out.glob("*.csv")):
                published = published_dir / actual.name
                if published.exists():
                    ignored = ("table_version",) if actual.name == "frozen_credence_message_table.csv" else ()
                    receipt["published_csv_comparisons"].append(compare_csv(actual, published, ignored))
        receipt["status"] = "passed"
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["error"] = str(exc)
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "receipt": str(receipt_path)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(str(exc).encode("ascii", "backslashreplace").decode("ascii"), file=sys.stderr)
        raise SystemExit(1)
