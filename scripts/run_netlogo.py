"""Portable NetLogo 7.0.3 BehaviorSpace launcher with checked, immutable outputs.

Uses Java when available, or the bundled Windows JLI runtime in a child process.
All preferences are process-local: the launcher never writes the registry.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = Path(__file__).resolve().parent / "java_support"
VERSION = "7.0.3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def experiment_elements(model: Path, setup_file: Path | None = None):
    tree = ET.parse(setup_file or model)
    return tree.findall("./experiment") if setup_file else tree.findall("./experiments/experiment")


def values(value_set):
    if value_set.tag == "enumeratedValueSet":
        return [v.attrib["value"] for v in value_set]
    if value_set.tag == "steppedValueSet":
        first, step, last = (Decimal(value_set.attrib[k]) for k in ("first", "step", "last"))
        if step <= 0 or last < first:
            raise ValueError("Only increasing, positive-step BehaviorSpace sets are supported")
        count = int((last - first) // step) + 1
        return [str(first + step * i) for i in range(count)]
    raise ValueError(f"Unsupported BehaviorSpace value set: {value_set.tag}")


def settings(experiment):
    # NetLogo 7 .nlogox puts sets inside <constants>; external setup XML does not.
    container = experiment.find("constants")
    return list(container) if container is not None else [
        x for x in experiment if x.tag in ("enumeratedValueSet", "steppedValueSet")]


def external_experiment(experiment, seeds=None):
    """Copy NetLogo 7's native experiment XML, changing only requested seeds."""
    result = copy.deepcopy(experiment)
    if seeds is not None:
        container = result.find("constants")
        if container is None:
            container = result
        old = next((x for x in container if x.get("variable") == "run-seed"), None)
        if old is None:
            raise ValueError("Selected experiment has no run-seed value set")
        allowed = {int(Decimal(x)) for x in values(old)}
        if not set(seeds) <= allowed:
            raise ValueError("Seed override must be a subset of the selected experiment's existing seeds")
        index = list(container).index(old)
        container.remove(old)
        replacement = ET.Element("enumeratedValueSet", {"variable": "run-seed"})
        for seed in seeds:
            ET.SubElement(replacement, "value", {"value": str(seed)})
        container.insert(index, replacement)
    return result


def locate_install(explicit=None):
    candidates = [explicit, os.environ.get("NETLOGO_HOME")]
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        candidates += [program_files / f"NetLogo {VERSION}", program_files / f"NetLogo{VERSION}"]
    elif sys.platform == "darwin":
        candidates += [Path(f"/Applications/NetLogo {VERSION}"), Path(f"/Applications/NetLogo {VERSION}/NetLogo.app/Contents")]
    else:
        candidates += [Path.home() / f"NetLogo-{VERSION}", Path(f"/opt/NetLogo-{VERSION}")]
    for candidate in candidates:
        if candidate:
            install = Path(candidate).expanduser().resolve()
            for jar in (install / "app" / f"netlogo-{VERSION}.jar", install / "lib" / f"netlogo-{VERSION}.jar",
                        install / "lib" / "app" / f"netlogo-{VERSION}.jar",
                        install / "Java" / f"netlogo-{VERSION}.jar"):
                if jar.is_file():
                    return install, jar
    raise FileNotFoundError(f"NetLogo {VERSION} not found; pass --netlogo or set NETLOGO_HOME")


def relative_argument(path: Path, cwd: Path):
    try:
        return os.path.relpath(path, cwd)
    except ValueError:  # Different Windows drives.
        return str(path)


def build_command(install, jar, model, experiment, output, threads, setup_file=None, java=None):
    runtime_bin = install / "runtime" / "bin"
    executable_name = "java.exe" if os.name == "nt" else "java"
    candidates = [runtime_bin / executable_name, install / "lib" / "runtime" / "bin" / executable_name]
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "bin" / executable_name)
    executable = java or next((str(p) for p in candidates if p.is_file()), None) or shutil.which("java")
    backend = "java" if executable else "windows-jli"
    if not executable:
        if os.name != "nt" or not (runtime_bin / "jli.dll").is_file():
            raise FileNotFoundError("No Java executable or bundled Windows jli.dll found; pass --java")
        executable = str(runtime_bin / "java.exe")  # argv[0], not an executable launch.
    for name in ("WorkspacePreferencesFactory.class", "WorkspacePreferencesFactory$MemoryPreferences.class"):
        if not (SUPPORT / name).is_file():
            raise FileNotFoundError(f"Missing {name}; compile scripts/java_support/WorkspacePreferencesFactory.java")
    command = [executable, "-Xmx1536m", "-Dfile.encoding=UTF-8", "-Djava.awt.headless=true",
               "-Dnetlogo.libraries.disabled=true",
               "-Djava.util.prefs.PreferencesFactory=WorkspacePreferencesFactory",
               f"-Dnetlogo.extensions.dir={install / 'extensions'}", f"-Dnetlogo.models.dir={install / 'models'}",
               "--add-exports=java.base/java.lang=ALL-UNNAMED",
               "--add-exports=java.desktop/sun.awt=ALL-UNNAMED",
               "--add-exports=java.desktop/sun.java2d=ALL-UNNAMED",
               "-classpath", str(jar) + os.pathsep + relative_argument(SUPPORT, ROOT),
               "org.nlogo.headless.Main", "--model", relative_argument(model, ROOT),
               "--experiment", experiment, "--table", relative_argument(output, ROOT),
               "--threads", str(threads)]
    if setup_file:
        command += ["--setup-file", relative_argument(setup_file, ROOT)]
    return backend, command


def jli_child(install, command):
    runtime_bin = Path(install) / "runtime" / "bin"
    handles = [os.add_dll_directory(str(runtime_bin)), os.add_dll_directory(str(runtime_bin / "server"))]
    dll = ctypes.WinDLL(str(runtime_bin / "jli.dll"))
    chars = ctypes.POINTER(ctypes.c_char_p)
    launch = dll.JLI_Launch
    launch.argtypes = [ctypes.c_int, chars, ctypes.c_int, chars, ctypes.c_int, chars,
                      ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                      ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_int]
    launch.restype = ctypes.c_int
    encoded = [arg.encode("mbcs") for arg in command]
    argv = (ctypes.c_char_p * (len(encoded) + 1))(*encoded, None)
    result = launch(len(encoded), argv, 0, None, 0, None, b"21", b"21", b"java", b"java", 0, 1, 0, 0)
    for handle in handles:
        handle.close()
    return result


def run(args):
    from native_checks import check_table
    model = args.model.resolve()
    if not model.is_file():
        raise FileNotFoundError(model)
    setup_file = args.setup_file.resolve() if args.setup_file else None
    experiments = experiment_elements(model, setup_file)
    if args.list:
        print(json.dumps([{"name": x.get("name"), "repetitions": x.get("repetitions"),
                           "trajectory": x.get("runMetricsEveryStep") == "true",
                           "runs": int(x.get("repetitions", "1")) *
                           math.prod(len(values(s)) for s in settings(x))}
                          for x in experiments], indent=2))
        return 0
    if not args.experiment or args.output is None:
        raise ValueError("--experiment and --output are required unless --list is used")
    experiment = next((x for x in experiments if x.get("name") == args.experiment), None)
    if experiment is None:
        raise ValueError(f"Unknown experiment {args.experiment}; use --list")
    seeds = args.seeds
    if args.seed_count is not None:
        seed_set = next((s for s in settings(experiment) if s.get("variable") == "run-seed"), None)
        if seed_set is None:
            raise ValueError("Experiment has no run-seed value set")
        seeds = [int(Decimal(x)) for x in values(seed_set)[:args.seed_count]]
    if seeds is not None and len(seeds) != len(set(seeds)):
        raise ValueError("Duplicate requested seeds")
    output = args.output.resolve()
    meta_path = Path(str(output) + ".provenance.json")
    log_path = Path(str(output) + ".log")
    fixture_path = Path(str(output) + ".setup.xml") if seeds is not None else None
    for path in (output, meta_path, log_path, fixture_path):
        if path is not None and path.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    install, jar = locate_install(args.netlogo)
    output.parent.mkdir(parents=True, exist_ok=True)
    if fixture_path:
        experiment = external_experiment(experiment, seeds)
        external = ET.Element("experiments")
        external.append(experiment)
        with fixture_path.open("xb") as stream:
            ET.ElementTree(external).write(stream, encoding="utf-8", xml_declaration=True)
        setup_file = fixture_path
    backend, command = build_command(install, jar, model, args.experiment, output, args.threads, setup_file, args.java)
    source_files = [model, Path(__file__).resolve(), Path(__file__).resolve().with_name("native_checks.py"),
                    SUPPORT / "WorkspacePreferencesFactory.java", *sorted(SUPPORT.glob("*.class"))]
    if model.with_suffix(".nls").is_file():
        source_files.append(model.with_suffix(".nls"))
    if setup_file:
        source_files.append(setup_file)
    manifest = ROOT / "source_manifest.json"
    if manifest.is_file():
        source_files.append(manifest)
    metadata = {"schema_version": 1, "status": "running", "engine": f"NetLogo {VERSION} native BehaviorSpace",
                "backend": backend, "install": str(install), "experiment": args.experiment,
                "command": command, "working_directory": str(ROOT), "output": str(output), "log": str(log_path),
                "threads": args.threads, "seeds": [int(Decimal(x)) for s in settings(experiment)
                                                     if s.get("variable") == "run-seed" for x in values(s)],
                "seed_subset_only": seeds is not None, "started_utc": datetime.now(timezone.utc).isoformat(),
                "sources": {str(p): {"sha256": sha256(p), "bytes": p.stat().st_size} for p in source_files},
                "engine_jar": {"path": str(jar), "sha256": sha256(jar)}}
    runtime_release = install / "runtime" / "release"
    if backend == "windows-jli" and runtime_release.is_file():
        metadata["jvm_release"] = runtime_release.read_text(encoding="utf-8")
    elif backend == "java":
        version = subprocess.run([command[0], "-version"], capture_output=True, text=True, timeout=15)
        metadata["jvm_release"] = (version.stdout + version.stderr).strip()
    with meta_path.open("x", encoding="utf-8") as stream:
        json.dump(metadata, stream, indent=2)
    started = time.perf_counter()
    print(f"Running {args.experiment} ({backend}) -> {output}", flush=True)
    try:
        child_command = command if backend == "java" else [sys.executable, str(Path(__file__).resolve()),
                            "--_jli", json.dumps({"install": str(install), "command": command})]
        with log_path.open("xb") as log:
            completed = subprocess.run(child_command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                       timeout=args.timeout)
        metadata["exit_code"] = completed.returncode
        if completed.returncode:
            raise RuntimeError(f"Native engine exited {completed.returncode}; inspect {log_path}")
        metadata["postflight"] = check_table(output, experiment, expected_ticks=args.expected_ticks)
        for path in source_files:
            if sha256(path) != metadata["sources"][str(path)]["sha256"]:
                raise RuntimeError(f"Source changed during execution: {path}")
        metadata["table_sha256"] = sha256(output)
        metadata["status"] = "passed"
        print(f"Postflight passed: {metadata['postflight']['runs']} runs, {metadata['postflight']['rows']} rows", flush=True)
        return 0
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        metadata["elapsed_seconds"] = time.perf_counter() - started
        metadata["completed_utc"] = datetime.now(timezone.utc).isoformat()
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(sys.argv) == 3 and sys.argv[1] == "--_jli":
        payload = json.loads(sys.argv[2])
        return jli_child(payload["install"], payload["command"])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--experiment")
    parser.add_argument("--output", "--table", type=Path)
    parser.add_argument("--list", action="store_true", help="List embedded experiments without starting Java")
    parser.add_argument("--setup-file", type=Path, help="External BehaviorSpace XML (source model stays unchanged)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seeds", type=int, nargs="+", help="Subset of existing run-seed values only")
    group.add_argument("--seed-count", type=int, help="First N existing seeds; all other settings unchanged")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--netlogo", help="NetLogo installation directory; defaults to NETLOGO_HOME or conventional locations")
    parser.add_argument("--java", help="Explicit Java executable (Java 21 for NetLogo 7.0.3)")
    parser.add_argument("--timeout", type=float, default=3600, help="Wall timeout in seconds")
    parser.add_argument("--expected-ticks", type=int, help="For custom diagnostic XML with nonstandard termination")
    args = parser.parse_args()
    if args.threads < 1 or args.timeout <= 0 or (args.seed_count is not None and args.seed_count < 1):
        parser.error("threads, timeout and seed-count must be positive")
    try:
        return run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
