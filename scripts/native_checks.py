"""Small native NetLogo acceptance suite; does not run the publication grids."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MODELS = {i: next((ROOT / "models" / f"experiment_{i}").glob("*.nlogox")) for i in range(3)}


def read_table(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        lines = stream.readlines()
    header = next((i for i, line in enumerate(lines) if line.startswith('"[run number]"')), None)
    if header is None:
        raise ValueError("Native table has no BehaviorSpace run header")
    if not any("NetLogo 7.0.3" in line for line in lines[:header]):
        raise ValueError("Native output does not identify NetLogo 7.0.3")
    reader = csv.DictReader(lines[header:])
    rows = list(reader)
    if not rows or any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError("Empty, truncated or malformed native table")
    return rows


def canonical(value):
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    try:
        return str(Decimal(value).normalize())
    except Exception:
        return value


def check_table(path, experiment, expected_ticks=None):
    from run_netlogo import settings, values
    rows = read_table(path)
    sets = settings(experiment)
    variables = [s.get("variable") for s in sets]
    expected_grid = set(itertools.product(*[[canonical(v) for v in values(s)] for s in sets]))
    repetitions = int(experiment.get("repetitions", "1"))
    trajectories = experiment.get("runMetricsEveryStep", "false") == "true"
    if expected_ticks is None:
        condition = experiment.findtext("exitCondition", "").strip()
        match = re.fullmatch(r"ticks\s*>=\s*(\d+)", condition)
        expected_ticks = int(match.group(1)) if match else {
            "ticks >= total-ticks-fixed": 500,
            "ticks >= expert-active-ticks-fixed": 25,
        }.get(condition)
    if expected_ticks is None:
        raise ValueError("Unknown termination; provide --expected-ticks")
    metrics_container = experiment.find("metrics")
    metrics = [m.text for m in (metrics_container if metrics_container is not None else experiment)
               if m.tag == "metric"]
    required = set(variables + metrics + ["[run number]", "[step]"])
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    groups = {}
    for row in rows:
        run_id = row["[run number]"]
        grid = tuple(canonical(row[v]) for v in variables)
        groups.setdefault(run_id, []).append(row)
        if grid not in expected_grid:
            raise ValueError(f"Unexpected run-grid setting: {grid}")
        for key, value in row.items():
            if value.lower() in ("nan", "infinity", "-infinity", "inf", "-inf"):
                raise ValueError(f"Nonfinite value in {key}")
            if key.startswith("maximum-") and key.endswith("-error") and abs(float(value)) >= 1e-10:
                raise ValueError(f"Failed numeric identity {key}: {value}")
            if key.endswith("valid?") and value != "true":
                raise ValueError(f"Failed validity reporter {key}: {value}")
        if "ticks" in row and float(row["ticks"]) != float(row["[step]"]):
            raise ValueError("ticks and BehaviorSpace step differ")
        step = int(float(row["[step]"]))
        if "expert-total-pulls" in row and float(row["expert-total-pulls"]) != 5 * min(step, 25):
            raise ValueError("Expert pull accounting failed")
        if "total-lay-pulls" in row and "calibration" not in experiment.get("name", "") and float(row["total-lay-pulls"]) != 10 * step:
            raise ValueError("Lay pull accounting failed")
    observed_grid = {}
    for run_id, run_rows in groups.items():
        grid = tuple(canonical(run_rows[0][v]) for v in variables)
        if any(tuple(canonical(row[v]) for v in variables) != grid for row in run_rows):
            raise ValueError(f"Settings changed within run {run_id}")
        observed_grid[grid] = observed_grid.get(grid, 0) + 1
        steps = [int(float(row["[step]"])) for row in run_rows]
        wanted = list(range(expected_ticks + 1)) if trajectories else [expected_ticks]
        if steps != wanted:
            raise ValueError(f"Incomplete/duplicate native rows in run {run_id}: expected {len(wanted)} steps, got {len(steps)}")
        final = run_rows[-1]
        if "actual-seed" in final and canonical(final["actual-seed"]) != canonical(final["run-seed"]):
            raise ValueError("Requested and actual seed differ")
        if "hidden-world" in final and "world-mode" in final and final["world-mode"] in ("B-good", "B-bad") and final["hidden-world"] != final["world-mode"]:
            raise ValueError("Requested and actual world differ")
        for field, wanted_value in (("duplicate-message-count", 0), ("expert-packet-size-at-intervention", 125),
                                    ("expert-local-overlap-count", 0), ("broadcast-count", 1),
                                    ("credence-message-count", 1), ("expert-raw-items-transmitted", 0)):
            if field in final and float(final[field]) != wanted_value:
                raise ValueError(f"Final {field} differs from {wanted_value}")
        for field in ("expert-packet-unique?", "inbox-empty-at-intervention?"):
            if field in final and final[field] != "true":
                raise ValueError(f"Final {field} failed")
        sharing = final.get("peer-sharing?", "true") == "true"
        if "mean-lay-archive-size-at-25" in final and float(final["mean-lay-archive-size-at-25"]) != (75 if sharing else 25):
            raise ValueError("Pre-intervention local evidence count failed")
        if "mean-peer-messages-received" in final and float(final["mean-peer-messages-received"]) != (998 if sharing else 0):
            raise ValueError("Final peer-message count failed")
    if set(observed_grid) != expected_grid or any(n != repetitions for n in observed_grid.values()):
        raise ValueError("Missing or duplicate native run grid")
    return {"passed": True, "runs": len(groups), "rows": len(rows), "expected_ticks": expected_ticks,
            "trajectory": trajectories, "native_version": "NetLogo 7.0.3",
            "checks": ["exact run grid", "complete step sequence", "required columns", "finite metrics",
                       "reported validity and numeric identities", "pull and available message accounting"]}


def run_engine(model, experiment, output, args, seed_count=None, setup_file=None):
    command = [sys.executable, str(Path(__file__).with_name("run_netlogo.py")), "--model", str(model),
               "--experiment", experiment, "--output", str(output), "--threads", str(args.threads),
               "--timeout", str(args.timeout)]
    if args.netlogo:
        command += ["--netlogo", args.netlogo]
    if args.java:
        command += ["--java", args.java]
    if seed_count is not None:
        command += ["--seed-count", str(seed_count)]
    if setup_file:
        command += ["--setup-file", str(setup_file)]
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode:
        raise RuntimeError(f"Native check failed: {experiment}; inspect {output}.log")
    return {"experiment": experiment, "output": str(output), "command": command,
            "provenance": json.loads(Path(str(output) + ".provenance.json").read_text(encoding="utf-8"))}


def exact_regression(evidence_path, exact_path):
    e1, e2 = read_table(evidence_path), read_table(exact_path)
    aliases = {"No Deference": "No Deference", "Exact-C-Preemption": "E-Preemption",
               "Exact-C-Total Evidence": "E-Total Evidence"}
    def key(row, policy):
        return (row["run-seed"], row["world-mode"], row["peer-sharing?"], policy, row["[step]"])
    left = {key(row, row["evidence-policy"]): row for row in e1 if row["evidence-policy"] != "No Deference"}
    right = {key(row, aliases[row["credence-policy"]]): row for row in e2}
    if set(left) != set(right):
        raise ValueError("E1/E2 exact regression has different seed/world/policy/tick grids")
    metrics = ["ticks", "current-lay-correct-choice-rate", "current-lay-b-share", "mean-lay-q",
               "mean-lay-posterior-truth-mass", "mean-lay-cumulative-regret",
               "mean-lay-post-intervention-regret", "expert-posterior-truth-mass", "expert-total-pulls"]
    worst = 0.0
    for case, row in left.items():
        for metric in metrics:
            difference = abs(float(row[metric]) - float(right[case][metric]))
            worst = max(worst, difference)
            if difference > 1e-10:
                raise ValueError(f"E1/E2 exact regression differs at {case}, {metric}: {row[metric]} versus {right[case][metric]}")
    return {"passed": True, "paired_rows": len(left), "metrics": metrics, "maximum_absolute_error": worst,
            "scope": "paired seed/world/policy trajectories at every tick 0 through 500"}


def diagnostic_fixture(model, index, directory):
    """Append assertions to a result-only copy; never edit the scientific model."""
    from run_netlogo import external_experiment
    tree = ET.parse(model)
    update = "update-belief-from-result" if index == 0 else "observe-new-evidence"
    common = r'''
to native-assert [condition label-text]
  if not condition [error (word "Native diagnostic failed: " label-text)]
end

to native-common-tests
  setup
  ask layperson 1 [
    UPDATE true 1
    native-assert (abs (belief-llr - llr-unit) < 1.0e-12) "B success LLR"
    UPDATE true 0
    native-assert (abs belief-llr < 1.0e-12) "B failure LLR"
    UPDATE false 1
    UPDATE false 0
    native-assert (abs belief-llr < 1.0e-12) "A rewards carry no world information"
  ]

  setup
  let duplicate-record (list (list 2 0 0) true 1)
  ask layperson 1 [set next-inbox (list duplicate-record duplicate-record)]
  deliver-peer-messages
  native-assert (duplicate-message-count = 1) "duplicate peer ID detected"
  native-assert ([peer-messages-received] of layperson 1 = 1) "duplicate peer counted once"
  native-assert ([length seen-evidence-ids] of layperson 1 = 1) "duplicate peer archive once"
  native-assert (abs ([belief-llr] of layperson 1 - llr-unit) < 1.0e-12) "duplicate peer LLR once"

  setup
  ask layperson 1 [layperson-pull]
  let own-before [belief-llr] of layperson 1
  ask layperson 1 [
    set next-inbox (list (list (list who ticks 0) chose-b? current-reward))
  ]
  deliver-peer-messages
  native-assert (duplicate-message-count = 1) "self-origin peer duplicate detected"
  native-assert ([length seen-evidence-ids] of layperson 1 = 1) "self-origin archive once"
  native-assert ([belief-llr] of layperson 1 = own-before) "self-origin LLR once"
  let duplicate-own-rejected? false
  carefully [ask layperson 1 [layperson-pull]] [
    set duplicate-own-rejected?
      (error-message = "A layperson generated a duplicate first-hand evidence ID")
  ]
  native-assert duplicate-own-rejected? "duplicate first-hand ID rejected"

  setup
  ask layperson 1 [set next-inbox (list (list (list 999 0 0) true 1))]
  deliver-peer-messages
  queue-first-hand-messages
  native-assert (all? laypeople [length next-inbox = 2]) "exactly one first-hand message per neighbor"
  foreach (sort laypeople) [learner ->
    ask learner [
      let allowed [who] of cycle-link-neighbors
      foreach next-inbox [record ->
        native-assert (member? (item 0 (item 0 record)) allowed) "received records never forwarded"
        native-assert (item 1 (item 0 record) = ticks) "only current-round records queued"
      ]
    ]
  ]

  setup
  ask layperson 1 [UPDATE true 1]
  set hidden-world ifelse-value (hidden-world = "B-good") ["B-bad"] ["B-good"]
  ask layperson 2 [UPDATE true 1]
  native-assert ([belief-llr] of layperson 1 = [belief-llr] of layperson 2)
    "identical evidence updates independent of hidden-world scoring label"
end
'''.replace("UPDATE", update)
    specific = ""
    if index in (1, 2):
        intervention = "apply-evidence-intervention" if index == 1 else "apply-credence-intervention"
        specific += r'''
  setup
  repeat 25 [go]
  native-assert (ticks = 25 and expertise-snapshot-recorded?) "snapshot after round 25"
  native-assert (not deference-intervention-complete?) "no intervention before round 26"
  native-assert (all? laypeople [length seen-evidence-ids = 75 and empty? next-inbox])
    "round-25 peers delivered before intervention"
  native-assert (all? laypeople [total-pulls = 25]) "no round-26 action before intervention"
  INTERVENE
  native-assert (all? laypeople [total-pulls = 25 and empty? next-inbox])
    "intervention precedes round-26 actions"
  let archived-before [length seen-evidence-ids] of layperson 1
  let llr-before [belief-llr] of layperson 1
  ask layperson 1 [observe-new-evidence true 1]
  native-assert (abs ([belief-llr] of layperson 1 - llr-before - llr-unit) < 1.0e-12)
    "P and TE continue updating after intervention"
  native-assert ([length seen-evidence-ids] of layperson 1 = archived-before)
    "pre-intervention archive retained"
  native-assert ([post-intervention-local-item-count] of layperson 1 = 1)
    "post-intervention new evidence counted"
  setup
  repeat 26 [go]
  native-assert (ticks = 26 and deference-intervention-complete?) "intervention completed at round 26"
  native-assert (all? laypeople [total-pulls = 26 and length seen-evidence-ids = 78 and peer-messages-received = 52])
    "round-26 action and subsequent peer delivery counted"
'''.replace("INTERVENE", intervention)
    if index == 1:
        specific += r'''
  setup
  repeat 25 [go]
  ask expert 0 [set evidence-archive replace-item 1 evidence-archive (item 0 evidence-archive)]
  let duplicate-packet-rejected? false
  carefully [apply-evidence-intervention] [
    set duplicate-packet-rejected?
      (error-message = "Expert raw-evidence packet contains duplicate IDs")
  ]
  native-assert duplicate-packet-rejected? "duplicate expert packet rejected"
  setup
  repeat 25 [go]
  let overlapping-id item 0 (item 0 [evidence-archive] of expert 0)
  ask layperson 1 [set seen-evidence-ids lput overlapping-id seen-evidence-ids]
  let overlap-rejected? false
  carefully [apply-evidence-intervention] [
    set overlap-rejected?
      (error-message = "Expert evidence overlaps a layperson local archive")
  ]
  native-assert overlap-rejected? "expert-local overlap rejected"
'''
    if index == 2:
        specific += r'''
  native-assert credence-bin-boundaries-valid? "coarse category boundaries"
  let saved-bin -1
  let saved-payload 0
  let saved-student-beliefs []
  foreach [0.61 0.69] [private-q ->
    setup
    repeat 25 [go]
    ask expert 0 [set belief-llr probability-to-llr private-q]
    apply-credence-intervention
    let learner-beliefs map [learner -> [belief-llr] of learner] (sort laypeople)
    ifelse saved-bin = -1 [
      set saved-bin broadcast-message-bin
      set saved-payload broadcast-message-llr
      set saved-student-beliefs learner-beliefs
    ] [
      native-assert (broadcast-message-bin = saved-bin) "same-bin test fixture"
      native-assert (broadcast-message-llr = saved-payload) "same-bin payload independent of private q"
      native-assert (learner-beliefs = saved-student-beliefs) "same transcript and bin imply same student adoption"
    ]
  ]
'''
    code = tree.getroot().find("code")
    code.text += "\n" + common + "\nto native-diagnostic-setup\n  native-common-tests\n" + specific + "\n  setup\nend\n"
    model_copy = directory / f"diagnostic_{index}.nlogox"
    with model_copy.open("xb") as stream:
        tree.write(stream, encoding="utf-8", xml_declaration=True)
    original = next(e for e in tree.findall("./experiments/experiment") if "smoke" in e.get("name", ""))
    experiment = external_experiment(original)
    experiment.set("name", f"native-diagnostic-{index}")
    experiment.set("timeLimit", "1")
    experiment.find("setup").text = "native-diagnostic-setup"
    experiment.find("go").text = "tick"
    experiment.find("exitCondition").text = "ticks >= 1"
    metrics = experiment.find("metrics")
    metrics[:] = []
    for metric in ("actual-seed", "ticks"):
        ET.SubElement(metrics, "metric").text = metric
    root = ET.Element("experiments")
    root.append(experiment)
    setup_file = directory / f"diagnostic_{index}.xml"
    with setup_file.open("xb") as stream:
        ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=True)
    return model_copy, setup_file


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--netlogo")
    parser.add_argument("--java")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--seed-count", type=int, default=1, help="Existing trajectory/peer-check seeds per world/policy")
    args = parser.parse_args()
    if args.seed_count < 1 or args.threads < 1 or args.timeout <= 0:
        parser.error("seed-count, threads and timeout must be positive")
    directory = args.output_dir.resolve()
    if directory.exists():
        parser.error(f"Refusing to overwrite existing acceptance directory: {directory}")
    directory.mkdir(parents=True)
    report = {"schema_version": 1, "status": "running", "purpose": "native engineering acceptance, not a theory experiment",
              "runs": [], "coverage": [], "not_tested": ["full publication seed grids", "GUI operation", "new scientific mechanisms"]}
    try:
        for i, label in ((0, "bandit"), (1, "evidence"), (2, "opaque")):
            report["runs"].append(run_engine(MODELS[i], f"experiment-{i}-{label}-smoke", directory / f"smoke_{i}.csv", args))
        report["runs"].append(run_engine(MODELS[0], "experiment-0-bandit-peer-check", directory / "peer_check.csv", args, args.seed_count))
        report["runs"].append(run_engine(MODELS[1], "experiment-1-evidence-trajectories", directory / "evidence_trajectories.csv", args, args.seed_count))
        report["runs"].append(run_engine(MODELS[2], "experiment-2-exact-regression-trajectories", directory / "exact_trajectories.csv", args, args.seed_count))
        report["exact_regression"] = exact_regression(directory / "evidence_trajectories.csv", directory / "exact_trajectories.csv")
        for i in range(3):
            diagnostic_model, fixture = diagnostic_fixture(MODELS[i], i, directory)
            result = run_engine(diagnostic_model, f"native-diagnostic-{i}", directory / f"diagnostic_{i}.csv", args, setup_file=fixture)
            result["unaltered_source"] = {"path": str(MODELS[i]), "sha256": hashlib.sha256(MODELS[i].read_bytes()).hexdigest()}
            report["runs"].append(result)
        report["coverage"] += ["all three unchanged models compile and finish native smoke grids",
                               "peer on/off accounting over full 500-round runs",
                               "P/TE keep learning through round 500 with reported archive/decomposition invariants",
                               "E1/E2 exact policies agree at every tick on nine shared metrics",
                               "isolated assertions: B/A update, duplicate peer/self evidence, duplicate generated ID rejection",
                               "isolated assertions: queued messages are first-hand only and hidden scoring label does not enter conditional evidence update",
                               "isolated assertions: round 25 delivery / round 26 intervention ordering and later P/TE updates",
                               "isolated assertions: E1 duplicate expert packet and expert-local overlap rejected",
                               "isolated assertions: E2 identical local transcript plus same bin adopts identical beliefs for private q=.61 versus .69"]
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        (directory / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Native acceptance passed: {directory / 'acceptance.json'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
