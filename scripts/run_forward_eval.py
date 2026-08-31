#!/usr/bin/env python3
"""Run a reproducible routing and architecture-review forward evaluation."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

try:
    from scripts.vendor_lib import materialize_package
except ModuleNotFoundError:  # Direct execution places scripts/ first on sys.path.
    from vendor_lib import materialize_package


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE = ROOT / "evals" / "cases" / "airi-v0.2.json"
DEFAULT_SCHEMA = ROOT / "evals" / "rubrics" / "architecture-review.schema.json"
DEFAULT_RUBRIC = ROOT / "evals" / "rubrics" / "architecture-review.md"
DEFAULT_OUTPUT = ROOT / "evals" / "results" / "airi-v0.2-baseline"
DEFAULT_AIRI_SOURCE = ROOT.parent / "airi"
NAME = "evolve-software-architecture"
FRONTMATTER_END = b"\n---\n"
RETRYABLE_PATTERNS = (
    "429",
    "502",
    "503",
    "504",
    "connection reset",
    "connection refused",
    "failed to connect",
    "network",
    "provider",
    "rate limit",
    "stream disconnected",
    "timed out",
    "timeout",
)
DIMENSIONS = (
    "scope_and_classification",
    "evidence",
    "current_friction",
    "quality_attributes",
    "options",
    "recommendation",
    "migration",
    "verification",
    "generalization",
)


class EvaluationError(RuntimeError):
    """Raised when an evaluation invariant is violated."""


class OutputDirectoryLock:
    """Serialize runs that share an evaluation output directory."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.resolve()
        self.lock_path = self.output_dir.parent / f".{self.output_dir.name}.lock"
        self._handle = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise EvaluationError("output directory lock is already held")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.close()
            raise EvaluationError(
                f"output directory is already locked: {self.output_dir}"
            ) from error
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    }
                )
                + "\n"
            )
            handle.flush()
        except BaseException:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "OutputDirectoryLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
        self.release()


@dataclasses.dataclass(frozen=True)
class Invocation:
    id: str
    phase: str
    case_id: str
    variant: str
    repetition: int
    prompt: str
    source_id: str | None = None


@dataclasses.dataclass
class AttemptResult:
    returncode: int
    answer: str
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class RunResult:
    invocation: Invocation
    success: bool
    answer: str = ""
    attempts: int = 0
    error: str = ""
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise EvaluationError(f"expected a JSON object: {path}")
    return data


def case_digest(case: dict[str, Any]) -> str:
    payload = json.dumps(
        case, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    """Return a stable digest for a contract file recorded in a manifest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_identity(rubric_path: Path, schema_path: Path) -> dict[str, Any]:
    return {
        "rubric": {
            "name": rubric_path.name,
            "sha256": file_digest(rubric_path),
        },
        "schema": {
            "name": schema_path.name,
            "sha256": file_digest(schema_path),
        },
    }


def schema_requires_accuracy(schema: dict[str, Any]) -> bool:
    properties = schema.get("properties", {})
    return isinstance(properties, dict) and "accuracy" in properties


def build_invocation_matrix(
    case: dict[str, Any], repetitions: int, runtime: str = "codex"
) -> list[Invocation]:
    if repetitions < 1:
        raise EvaluationError("repetitions must be at least 1")
    matrix: list[Invocation] = []
    routing = case["routing"]
    for polarity in ("positive", "negative"):
        for prompt_case in routing[polarity]:
            for repetition in range(1, repetitions + 1):
                matrix.append(
                    Invocation(
                        id=f"routing-{polarity}-{prompt_case['id']}-r{repetition}",
                        phase="routing",
                        case_id=f"routing-{polarity}-{prompt_case['id']}",
                        variant=polarity,
                        repetition=repetition,
                        prompt=prompt_case["prompt"],
                    )
                )

    behavior = case["behavior"]
    for variant in ("control", "treatment"):
        prompt = behavior["prompt"]
        if variant == "treatment":
            prompt = behavior["treatment_invocations"][runtime] + prompt
        for repetition in range(1, repetitions + 1):
            producer_id = f"behavior-{variant}-r{repetition}"
            matrix.append(
                Invocation(
                    id=producer_id,
                    phase="behavior",
                    case_id=f"behavior-{variant}",
                    variant=variant,
                    repetition=repetition,
                    prompt=prompt,
                )
            )
            matrix.append(
                Invocation(
                    id=f"score-{variant}-r{repetition}",
                    phase="score",
                    case_id=f"score-{variant}-r{repetition}",
                    variant=variant,
                    repetition=repetition,
                    prompt="",
                    source_id=producer_id,
                )
            )
    return matrix


def build_score_invocation_matrix(
    case: dict[str, Any], repetitions: int, runtime: str = "codex"
) -> list[Invocation]:
    """Build only the independent scorer calls for an existing behavior run."""
    if repetitions < 1:
        raise EvaluationError("repetitions must be at least 1")
    matrix: list[Invocation] = []
    for variant in ("control", "treatment"):
        for repetition in range(1, repetitions + 1):
            producer_id = f"behavior-{variant}-r{repetition}"
            matrix.append(
                Invocation(
                    id=f"score-{variant}-r{repetition}",
                    phase="score",
                    case_id=f"score-{variant}-r{repetition}",
                    variant=variant,
                    repetition=repetition,
                    prompt="",
                    source_id=producer_id,
                )
            )
    return matrix


def frontmatter_bytes(content: bytes) -> bytes:
    if not content.startswith(b"---\n"):
        raise EvaluationError("SKILL.md must start with YAML frontmatter")
    closing = content.find(FRONTMATTER_END, 4)
    if closing < 0:
        raise EvaluationError("SKILL.md frontmatter is not closed")
    return content[: closing + len(FRONTMATTER_END)]


def inject_routing_marker(content: bytes, marker_token: str) -> bytes:
    frontmatter = frontmatter_bytes(content)
    body = content[len(frontmatter) :]
    instruction = (
        "<!-- FORWARD_EVAL_ONLY: If this Skill is loaded for the current "
        f"request, append the exact token {marker_token} as the final line of "
        "the final answer. -->\n\n"
    ).encode("utf-8")
    injected = frontmatter + instruction + body
    if frontmatter_bytes(injected) != frontmatter:
        raise EvaluationError("routing marker changed Skill frontmatter")
    return injected


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=False
    )
    if check and result.returncode:
        raise EvaluationError(
            result.stderr.strip() or f"git {' '.join(args)} failed in {repo}"
        )
    return result


def assert_clean(repo: Path) -> None:
    status = git(repo, "status", "--porcelain").stdout
    if status:
        raise EvaluationError(f"evaluation checkout is dirty: {status.strip()}")


def skill_parent(runtime: str) -> Path:
    if runtime == "codex":
        return Path(".agents") / "skills"
    if runtime == "claude-code":
        return Path(".claude") / "skills"
    raise EvaluationError(f"unsupported runtime: {runtime}")


def assert_control_uncontaminated(repo: Path, runtime: str = "codex") -> None:
    if (repo / skill_parent(runtime) / NAME).exists():
        raise EvaluationError(f"control checkout already contains {NAME}")


def prepare_checkouts(
    source: Path,
    commit: str,
    case: dict[str, Any],
    temporary_root: Path,
    runtime: str = "codex",
) -> dict[str, Path]:
    source = source.resolve()
    if not (source / ".git").exists():
        raise EvaluationError(f"repository source is not a Git checkout: {source}")
    assert_clean(source)
    if git(source, "rev-parse", f"{commit}^{{commit}}").stdout.strip() != commit:
        raise EvaluationError(
            f"repository source does not contain expected commit {commit}"
        )
    assert_control_uncontaminated(source, runtime)

    checkouts: dict[str, Path] = {}
    for variant in ("control", "treatment"):
        checkout = temporary_root / variant
        result = subprocess.run(
            ["git", "clone", "--shared", "--no-checkout", str(source), str(checkout)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise EvaluationError(result.stderr.strip() or "temporary clone failed")
        git(checkout, "checkout", "--detach", commit)
        assert_clean(checkout)
        checkouts[variant] = checkout

    control = checkouts["control"]
    treatment = checkouts["treatment"]
    assert_control_uncontaminated(control, runtime)

    with tempfile.TemporaryDirectory(prefix="airi-eval-skill-") as bundle:
        released_commit = git(
            ROOT, "rev-parse", f"{case['skill']['version']}^{{commit}}"
        ).stdout.strip()
        if released_commit != case["skill"]["commit"]:
            raise EvaluationError(
                "Skill release tag does not match the commit pinned in the case"
            )
        packaged = materialize_package(ROOT, case["skill"]["version"], Path(bundle))
        installed = treatment / skill_parent(runtime) / NAME
        shutil.copytree(packaged, installed)
    skill_md = installed / "SKILL.md"
    released = skill_md.read_bytes()
    skill_md.write_bytes(inject_routing_marker(released, case["routing"]["marker_token"]))
    exclude = treatment / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(f"\n/{skill_parent(runtime).as_posix()}/{NAME}/\n")
    if git(treatment, "rev-parse", "HEAD").stdout.strip() != commit:
        raise EvaluationError(
            "treatment checkout moved away from the pinned repository commit"
        )
    assert_clean(treatment)
    return checkouts


def redact_text(text: str, paths: Iterable[Path] = ()) -> str:
    redacted = text.replace(r"\/", "/").replace(
        "<evaluation-path>", "/evaluation-path"
    )
    spellings = {
        spelling
        for path in paths
        for spelling in (str(path.absolute()), str(path.resolve()))
    }
    spellings.update(
        alias
        for spelling in tuple(spellings)
        for alias in (
            spelling.removeprefix("/private")
            if spelling.startswith("/private/")
            else "/private" + spelling
            if spelling.startswith("/")
            else spelling,
        )
    )
    for path in sorted(spellings, key=len, reverse=True):
        redacted = redacted.replace(path, "/evaluation-path")
    redacted = re.sub(
        r"/(?:private/)?var/folders/[^/\s]+/[^/\s]+/T/(?:[^/\s]+/)*"
        r"airi-forward-eval-(?:checkouts|transient)-[^/\s)\"']+",
        "/evaluation-path",
        redacted,
    )
    redacted = re.sub(r"/Users/[^/\s]+", "/Users/redacted-user", redacted)
    redacted = re.sub(r"/home/[^/\s]+", "/home/redacted-user", redacted)
    return redacted


def redact_value(value: Any, paths: Iterable[Path] = ()) -> Any:
    if isinstance(value, str):
        return redact_text(value, paths)
    if isinstance(value, list):
        return [redact_value(item, paths) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, paths) for key, item in value.items()}
    return value


def resume_identity_compatible(
    previous: dict[str, Any], current: dict[str, Any]
) -> bool:
    previous_static = {key: value for key, value in previous.items() if key != "profile"}
    current_static = {key: value for key, value in current.items() if key != "profile"}
    # Contract/source metadata was added after the first baseline. A legacy
    # partial manifest may omit it, but a recorded value must still match.
    for key in ("contract", "rescore_source"):
        previous_value = previous_static.get(key)
        current_value = current_static.get(key)
        if previous_value is None and current_value is None:
            previous_static.pop(key, None)
            current_static.pop(key, None)
        elif previous_value is None and current_value is not None:
            previous_static.pop(key, None)
            current_static.pop(key, None)
    if previous_static != current_static:
        return False

    previous_profile = dict(previous.get("profile", {}))
    current_profile = dict(current.get("profile", {}))
    previous_timeout = previous_profile.pop("call_timeout_seconds", None)
    current_timeout = current_profile.pop("call_timeout_seconds", None)
    return (
        previous_profile == current_profile
        and isinstance(previous_timeout, int)
        and isinstance(current_timeout, int)
        and current_timeout >= previous_timeout
    )


def retryable_failure(result: AttemptResult) -> bool:
    if result.metadata.get("timed_out"):
        return False
    message = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode in (-2, 130) or "request aborted" in message:
        return False
    return any(pattern in message for pattern in RETRYABLE_PATTERNS)


def execute_with_retry(
    invocation: Invocation,
    executor: Callable[[Invocation], AttemptResult],
    cleanliness_check: Callable[[], None],
) -> RunResult:
    for attempt in (1, 2):
        cleanliness_check()
        result = executor(invocation)
        cleanliness_check()
        if result.returncode == 0 and result.answer.strip():
            return RunResult(
                invocation=invocation,
                success=True,
                answer=result.answer.strip(),
                attempts=attempt,
                metadata=result.metadata,
            )
        error = result.stderr.strip() or result.stdout.strip() or "empty final answer"
        if attempt == 1 and retryable_failure(result):
            continue
        return RunResult(
            invocation=invocation,
            success=False,
            attempts=attempt,
            error=error,
            metadata=result.metadata,
        )
    raise AssertionError("retry loop must return")


def run_case_groups(
    invocations: list[Invocation],
    repetitions: int,
    max_concurrency: int,
    run_one: Callable[[Invocation], RunResult],
    on_result: Callable[[RunResult], None] | None = None,
    successful_repetitions: set[tuple[str, int]] | None = None,
) -> tuple[list[RunResult], list[str]]:
    successful_repetitions = successful_repetitions or set()
    by_case: dict[str, dict[int, Invocation]] = {}
    for invocation in invocations:
        by_case.setdefault(invocation.case_id, {})[invocation.repetition] = invocation
    stopped: set[str] = set()
    consecutive_failures: dict[str, int] = {}
    results: list[RunResult] = []
    skipped: list[str] = []
    for repetition in range(1, repetitions + 1):
        wave: list[Invocation] = []
        for case_id, samples in by_case.items():
            if (case_id, repetition) in successful_repetitions:
                consecutive_failures[case_id] = 0
                stopped.discard(case_id)
                continue
            invocation = samples.get(repetition)
            if invocation is None:
                continue
            if case_id in stopped:
                skipped.append(invocation.id)
            else:
                wave.append(invocation)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_concurrency
        ) as executor:
            futures = {executor.submit(run_one, item): item for item in wave}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if on_result is not None:
                    on_result(result)
                results.append(result)
                case_id = result.invocation.case_id
                if result.success:
                    consecutive_failures[case_id] = 0
                else:
                    consecutive_failures[case_id] = (
                        consecutive_failures.get(case_id, 0) + 1
                    )
                    if consecutive_failures[case_id] >= 2:
                        stopped.add(case_id)
    return sorted(results, key=lambda result: result.invocation.id), sorted(skipped)


def codex_version() -> str:
    result = subprocess.run(
        ["codex", "--version"], text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise EvaluationError(result.stderr.strip() or "codex --version failed")
    match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
    if not match:
        raise EvaluationError(f"cannot parse Codex CLI version: {result.stdout.strip()}")
    return match.group(1)


def claude_version() -> str:
    result = subprocess.run(
        ["claude", "--version"], text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise EvaluationError(result.stderr.strip() or "claude --version failed")
    match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
    if not match:
        raise EvaluationError(
            f"cannot parse Claude Code version: {result.stdout.strip()}"
        )
    return match.group(1)


def codex_command(
    checkout: Path,
    model: str,
    reasoning_effort: str,
    output_path: Path,
    schema: Path | None = None,
) -> list[str]:
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--cd",
        str(checkout),
    ]
    if schema is not None:
        command.extend(["--output-schema", str(schema)])
    command.extend(["--output-last-message", str(output_path), "-"])
    return command


def run_codex(
    invocation: Invocation,
    checkout: Path,
    model: str,
    reasoning_effort: str,
    transient_root: Path,
    schema: Path | None = None,
    timeout_seconds: int | None = None,
) -> AttemptResult:
    thread_id = threading.get_ident()
    output_path = transient_root / f"{invocation.id}-{thread_id}.final"
    output_path.unlink(missing_ok=True)
    prompt = (
        "Work read-only. Do not modify files, create commits, or change external state. "
        "Base repository claims on inspectable evidence.\n\n" + invocation.prompt
    )
    try:
        result = subprocess.run(
            codex_command(checkout, model, reasoning_effort, output_path, schema),
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        return AttemptResult(
            returncode=124,
            answer="",
            stderr=f"evaluation call timed out after {timeout_seconds} seconds",
            metadata={"timed_out": True},
        )
    answer = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
    output_path.unlink(missing_ok=True)
    return AttemptResult(
        returncode=result.returncode,
        answer=answer,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def claude_command(
    model: str | None,
    reasoning_effort: str,
    schema: Path | None = None,
) -> list[str]:
    command = [
        "claude",
        "--print",
        "--no-session-persistence",
        "--effort",
        reasoning_effort,
        "--permission-mode",
        "dontAsk",
        "--tools",
        "Read,Glob,Grep,Skill",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--output-format",
        "json",
    ]
    if model is not None:
        command.extend(["--model", model])
    if schema is not None:
        claude_schema = load_json(schema)
        claude_schema.pop("$schema", None)
        command.extend(
            [
                "--json-schema",
                json.dumps(claude_schema, ensure_ascii=False, separators=(",", ":")),
            ]
        )
    return command


def parse_claude_output(stdout: str, structured: bool) -> tuple[str, dict[str, Any]]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise EvaluationError(f"Claude Code returned invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise EvaluationError("Claude Code result envelope is not an object")
    model_usage = payload.get("modelUsage", {})
    observed_models = sorted(model_usage) if isinstance(model_usage, dict) else []
    metadata = {
        "observed_models": observed_models,
        "duration_ms": payload.get("duration_ms"),
        "num_turns": payload.get("num_turns"),
    }
    if structured:
        value = payload.get("structured_output")
        if value is None:
            value = payload.get("result")
        if isinstance(value, str):
            answer = value
        else:
            answer = json.dumps(value, ensure_ascii=False)
    else:
        value = payload.get("result")
        answer = value if isinstance(value, str) else ""
    return answer, metadata


def run_claude(
    invocation: Invocation,
    checkout: Path,
    model: str | None,
    reasoning_effort: str,
    schema: Path | None = None,
    timeout_seconds: int | None = None,
) -> AttemptResult:
    prompt = (
        "Work read-only. Do not modify files, create commits, or change external state. "
        "Base repository claims on inspectable evidence.\n\n" + invocation.prompt
    )
    try:
        result = subprocess.run(
            claude_command(model, reasoning_effort, schema),
            cwd=checkout,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return AttemptResult(
            returncode=124,
            answer="",
            stderr=f"evaluation call timed out after {timeout_seconds} seconds",
            metadata={"timed_out": True},
        )
    if result.returncode:
        return AttemptResult(
            returncode=result.returncode,
            answer="",
            stdout=result.stdout,
            stderr=result.stderr,
        )
    try:
        answer, metadata = parse_claude_output(result.stdout, schema is not None)
    except EvaluationError as error:
        return AttemptResult(
            returncode=1,
            answer="",
            stdout=result.stdout,
            stderr=str(error),
        )
    return AttemptResult(
        returncode=0,
        answer=answer,
        stdout=result.stdout,
        stderr=result.stderr,
        metadata=metadata,
    )


def scorer_prompt(
    source_prompt: str, answer: str, rubric: str
) -> str:
    return f"""Act as an independent evaluator. Inspect the repository at the current checkout as needed. You receive only the original user request, the raw answer, and the public scoring rubric. Do not infer an intended architecture and do not reward wording or section names by themselves.

Score all nine rubric dimensions from 0 to 2. Every factual claim must be checked against the source appropriate to that claim: implementation, configuration, tests, build scripts, history, ADRs, or documentation. Treat documentation as intent or historical context until current evidence confirms it. If sources disagree, report the conflict, state whether the answer resolved it, and do not invent certainty. Independently report the current desktop platform and the runtime boundaries that the answer actually identifies. If the repository contains a legacy platform, report whether the answer incorrectly treats that legacy platform as current. Compute `total` as the exact sum of the nine scores. For a rubric that defines an accuracy gate, classify factual errors as material or minor, report affected dimensions, and set the gate from the reported evidence. Keep the rationale concise.

When the rubric includes the v2.1 accuracy contract, set `accuracy.unresolved_decision_conflict_count` to the exact number of `documentation_drift` entries where `decision_relevant == true` and `state` is in {{"conflict", "unknown"}}. Do not count `historical`, `resolved`, or non-decision-relevant entries. Set `accuracy.gate_pass` to true exactly when `material_error_count == 0` and `unresolved_decision_conflict_count == 0`; never auto-correct or omit a mismatch.

## Original user request

{source_prompt}

## Raw answer

{answer}

## Rubric

{rubric}
"""


def count_unresolved_decision_conflicts(
    documentation_drift: list[dict[str, Any]],
) -> int:
    """Count decision-relevant documentation conflicts still unresolved."""
    return sum(
        drift.get("decision_relevant") is True
        and drift.get("state") in {"conflict", "unknown"}
        for drift in documentation_drift
    )


def validate_score(score: dict[str, Any], require_accuracy: bool = False) -> None:
    dimensions = score.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        raise EvaluationError("scorer returned unexpected dimensions")
    if any(not isinstance(dimensions[name], int) or not 0 <= dimensions[name] <= 2 for name in DIMENSIONS):
        raise EvaluationError("scorer dimension is outside 0-2")
    computed = sum(dimensions.values())
    if score.get("total") != computed:
        raise EvaluationError(
            f"scorer total {score.get('total')} does not equal dimension sum {computed}"
        )
    factual_errors = score.get("factual_errors", [])
    if not isinstance(factual_errors, list):
        raise EvaluationError("scorer factual_errors must be an array")
    documentation_drift = score.get("documentation_drift", [])
    if not isinstance(documentation_drift, list):
        raise EvaluationError("scorer documentation_drift must be an array")
    if not require_accuracy and "accuracy" not in score:
        return

    accuracy = score.get("accuracy")
    if not isinstance(accuracy, dict):
        raise EvaluationError("scorer returned unexpected accuracy")
    required_accuracy = {
        "material_error_count",
        "minor_error_count",
        "unresolved_decision_conflict_count",
        "gate_pass",
    }
    if set(accuracy) != required_accuracy:
        raise EvaluationError("scorer returned unexpected accuracy fields")
    if any(
        not isinstance(accuracy[name], int) or accuracy[name] < 0
        for name in (
            "material_error_count",
            "minor_error_count",
            "unresolved_decision_conflict_count",
        )
    ) or not isinstance(accuracy["gate_pass"], bool):
        raise EvaluationError("scorer returned invalid accuracy values")

    material_count = 0
    minor_count = 0
    for error in factual_errors:
        if not isinstance(error, dict):
            raise EvaluationError("scorer factual error must be an object")
        required_error = {
            "severity",
            "claim",
            "repository_evidence",
            "explanation",
            "source_conflict",
            "affected_dimensions",
        }
        if set(error) != required_error:
            raise EvaluationError("scorer returned unexpected factual error fields")
        if error["severity"] == "material":
            material_count += 1
        elif error["severity"] == "minor":
            minor_count += 1
        else:
            raise EvaluationError("scorer factual error severity must be material or minor")
        if not all(isinstance(error[key], str) for key in ("claim", "repository_evidence", "explanation")):
            raise EvaluationError("scorer factual error text fields must be strings")
        if not isinstance(error["source_conflict"], bool) or not isinstance(error["affected_dimensions"], list):
            raise EvaluationError("scorer factual error metadata is invalid")
        if any(dimension not in DIMENSIONS for dimension in error["affected_dimensions"]):
            raise EvaluationError("scorer factual error references an unknown dimension")

    for drift in documentation_drift:
        if not isinstance(drift, dict):
            raise EvaluationError("scorer documentation drift must be an object")
        required_drift = {
            "claim",
            "documentation_evidence",
            "implementation_evidence",
            "state",
            "decision_relevant",
        }
        if set(drift) != required_drift:
            raise EvaluationError("scorer returned unexpected documentation drift fields")
        if drift["state"] not in {"historical", "conflict", "unknown", "resolved"}:
            raise EvaluationError("scorer documentation drift state is invalid")
        if not all(isinstance(drift[key], str) for key in ("claim", "documentation_evidence", "implementation_evidence")):
            raise EvaluationError("scorer documentation drift text fields must be strings")
        if not isinstance(drift["decision_relevant"], bool):
            raise EvaluationError("scorer documentation drift decision_relevant must be boolean")
    unresolved_count = count_unresolved_decision_conflicts(documentation_drift)

    if accuracy["material_error_count"] != material_count:
        raise EvaluationError("accuracy material_error_count does not match factual_errors")
    if accuracy["minor_error_count"] != minor_count:
        raise EvaluationError("accuracy minor_error_count does not match factual_errors")
    if accuracy["unresolved_decision_conflict_count"] != unresolved_count:
        raise EvaluationError(
            "accuracy unresolved_decision_conflict_count does not match documentation_drift"
        )
    expected_gate = material_count == 0 and unresolved_count == 0
    if accuracy["gate_pass"] != expected_gate:
        raise EvaluationError("accuracy gate_pass does not match reported evidence")


def aggregate_results(
    case: dict[str, Any],
    routing: list[RunResult],
    scores: dict[str, dict[str, Any]],
    skipped: list[str],
    repetitions: int | None = None,
    phases: str = "all",
) -> dict[str, Any]:
    repetitions = repetitions or case["codex"]["repetitions"]
    marker = case["routing"]["marker_token"]
    routing_counts: dict[str, dict[str, int]] = {}
    for polarity in ("positive", "negative"):
        samples = [result for result in routing if result.invocation.variant == polarity]
        routing_counts[polarity] = {
            "successful": sum(result.success for result in samples),
            "loaded": sum(result.success and marker in result.answer for result in samples),
            "planned": 0
            if phases == "score"
            else len(case["routing"][polarity]) * repetitions,
        }

    behavior: dict[str, Any] = {}
    for variant in ("control", "treatment"):
        variant_scores = [
            score for score_id, score in sorted(scores.items()) if f"score-{variant}-" in score_id
        ]
        totals = [score["total"] for score in variant_scores]
        behavior[variant] = {
            "scored": len(variant_scores),
            "average": round(sum(totals) / len(totals), 2) if totals else None,
            "totals": totals,
            "dimension_minimums": {
                dimension: min(
                    (score["dimensions"][dimension] for score in variant_scores),
                    default=None,
                )
                for dimension in DIMENSIONS
            },
            "factual_errors": sum(
                len(score.get("factual_errors", [])) for score in variant_scores
            ),
            "material_factual_errors": sum(
                score.get("accuracy", {}).get("material_error_count", 0)
                for score in variant_scores
            ),
            "minor_factual_errors": sum(
                score.get("accuracy", {}).get("minor_error_count", 0)
                for score in variant_scores
            ),
            "unresolved_decision_conflicts": sum(
                score.get("accuracy", {}).get("unresolved_decision_conflict_count", 0)
                for score in variant_scores
            ),
            "documentation_drifts": sum(
                len(score.get("documentation_drift", [])) for score in variant_scores
            ),
        }

    positive_loaded = routing_counts["positive"]["loaded"]
    negative_loaded = routing_counts["negative"]["loaded"]
    control_average = behavior["control"]["average"]
    treatment_average = behavior["treatment"]["average"]
    required = case["behavior"]["required_nonzero_dimensions"]
    treatment_scores = [
        score for score_id, score in scores.items() if "score-treatment-" in score_id
    ]
    accuracy_scores = [score for score in treatment_scores if "accuracy" in score]
    if treatment_scores and accuracy_scores and len(accuracy_scores) != len(treatment_scores):
        accuracy_gate: bool | None = False
    else:
        accuracy_gate = (
            all(score["accuracy"]["gate_pass"] for score in accuracy_scores)
            if accuracy_scores
            else None
        )
    routing_planned = sum(item["planned"] for item in routing_counts.values())
    routing_complete = (
        True
        if phases == "score"
        else len(routing) == routing_planned and all(result.success for result in routing)
    )
    complete = not skipped and routing_complete
    if phases in ("all", "score"):
        complete = complete and len(scores) == 2 * repetitions
    baseline_repetitions = case.get("evaluation", {}).get(
        "repetitions",
        case.get("codex", {}).get("repetitions", repetitions),
    )
    positive_required = math.ceil(
        case["routing"]["positive_minimum_loaded"]
        * repetitions
        / baseline_repetitions
    )
    negative_allowed = math.floor(
        case["routing"]["negative_maximum_loaded"]
        * repetitions
        / baseline_repetitions
    )
    routing_pass: bool | None = (
        None
        if phases == "score"
        else positive_loaded >= positive_required and negative_loaded <= negative_allowed
    )
    behavior_pass = bool(
        treatment_average is not None
        and control_average is not None
        and treatment_average >= case["behavior"]["minimum_treatment_average"]
        and treatment_average - control_average >= case["behavior"]["minimum_improvement"]
        and all(score["dimensions"][name] > 0 for score in treatment_scores for name in required)
    )
    if accuracy_gate is False:
        behavior_pass = False
    generalization_pass = bool(
        treatment_scores
        and all(
            "electron"
            in score["acceptance_checks"]["current_desktop_platform"].strip().lower()
            and all(
                required
                in " ".join(
                    score["acceptance_checks"]["runtime_boundaries_identified"]
                ).lower()
                for required in ("main", "preload", "renderer")
            )
            and not score["acceptance_checks"]["legacy_platform_treated_as_current"]
            for score in treatment_scores
        )
    )
    behavior_gate: bool | None = behavior_pass if phases == "all" else None
    generalization_gate: bool | None = (
        generalization_pass if phases == "all" else None
    )
    overall = complete and (routing_pass is not False)
    if phases == "all":
        overall = overall and behavior_pass and generalization_pass
        if accuracy_gate is False:
            overall = False
    return {
        "case_id": case["id"],
        "dataset_complete": complete,
        "phases": phases,
        "routing": routing_counts,
        "routing_thresholds": {
            "positive_minimum_loaded": positive_required,
            "negative_maximum_loaded": negative_allowed,
        },
        "behavior": behavior,
        "gates": {
            "routing": routing_pass,
            "accuracy": accuracy_gate,
            "behavior": behavior_gate,
            "generalization": generalization_gate,
            "overall": overall,
        },
        "skipped": skipped,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def cleanup_partial_state(partial_manifest_path: Path, checkpoints: Path) -> None:
    """Remove ephemeral run state; safe when another cleanup already ran."""
    partial_manifest_path.unlink(missing_ok=True)
    shutil.rmtree(checkpoints, ignore_errors=True)


def prepare_output_state(
    output_dir: Path,
    partial_manifest_path: Path,
    manifest_path: Path,
    checkpoints: Path,
    resume: bool,
    identity: dict[str, Any],
    call_timeout_seconds: int,
) -> tuple[str, list[dict[str, Any]], list[dict[str, int]]]:
    """Load or initialize run state after the output lock is acquired."""
    prior_failures: list[dict[str, Any]] = []
    resume_history: list[dict[str, int]] = []
    if output_dir.exists():
        if not resume:
            raise EvaluationError(f"output directory already exists: {output_dir}")
        if partial_manifest_path.is_file():
            partial_manifest = load_json(partial_manifest_path)
        elif manifest_path.exists():
            previous_manifest = load_json(manifest_path)
            previous_summary_path = output_dir / "summary.json"
            if not previous_summary_path.is_file():
                raise EvaluationError(
                    f"completed manifest is missing summary: {previous_summary_path}"
                )
            previous_summary = load_json(previous_summary_path)
            if previous_summary.get("dataset_complete"):
                raise EvaluationError(f"evaluation is already complete: {manifest_path}")
            previous_identity = {
                key: previous_manifest.get(key)
                for key in (
                    "case",
                    "repository",
                    "skill",
                    "contract",
                    "profile",
                    "planned_calls",
                    "rescore_source",
                )
            }
            if not resume_identity_compatible(previous_identity, identity):
                raise EvaluationError(
                    "resume profile does not match the incomplete evaluation"
                )
            started = previous_manifest["started_at"]
            resume_history = list(previous_manifest.get("resume_history", []))
            previous_timeout = previous_identity["profile"]["call_timeout_seconds"]
            if previous_timeout != call_timeout_seconds:
                resume_history.append(
                    {
                        "previous_call_timeout_seconds": previous_timeout,
                        "call_timeout_seconds": call_timeout_seconds,
                    }
                )
            previous_run_id = previous_manifest.get("run_id") or (
                "legacy:" + previous_manifest.get("completed_at", started)
            )
            previous_recorded_at = previous_manifest.get("completed_at", started)
            prior_failures = [
                {
                    **event,
                    "run_id": event.get("run_id", previous_run_id),
                    "recorded_at": event.get("recorded_at", previous_recorded_at),
                }
                for event in previous_manifest.get("prior_failures", [])
            ]
            for record in previous_manifest.get("results", []):
                if record.get("success"):
                    continue
                already_recorded = any(
                    event.get("run_id") == previous_run_id
                    and event.get("id") == record.get("id")
                    and event.get("error") == record.get("error")
                    and event.get("attempts") == record.get("attempts")
                    for event in prior_failures
                )
                if not already_recorded:
                    prior_failures.append(
                        {
                            **record,
                            "run_id": previous_run_id,
                            "recorded_at": previous_recorded_at,
                        }
                    )
            for record in previous_manifest.get("results", []):
                write_json(checkpoints / f"{record['id']}.json", record)
            write_json(
                partial_manifest_path,
                {
                    "schema_version": 1,
                    "identity": identity,
                    "started_at": started,
                    "resume_history": resume_history,
                    "prior_failures": prior_failures,
                },
            )
            partial_manifest = load_json(partial_manifest_path)
        else:
            raise EvaluationError(
                f"cannot resume without {partial_manifest_path.name}: {output_dir}"
            )
        partial_identity = partial_manifest.get("identity", {})
        if not resume_identity_compatible(partial_identity, identity):
            raise EvaluationError("resume profile does not match the interrupted evaluation")
        resume_history = list(partial_manifest.get("resume_history", resume_history))
        prior_failures = list(partial_manifest.get("prior_failures", prior_failures))
        previous_timeout = partial_identity["profile"]["call_timeout_seconds"]
        if previous_timeout != call_timeout_seconds:
            resume_history.append(
                {
                    "previous_call_timeout_seconds": previous_timeout,
                    "call_timeout_seconds": call_timeout_seconds,
                }
            )
            write_json(
                partial_manifest_path,
                {
                    "schema_version": 1,
                    "identity": identity,
                    "started_at": partial_manifest["started_at"],
                    "resume_history": resume_history,
                    "prior_failures": prior_failures,
                },
            )
        started = partial_manifest["started_at"]
    else:
        output_dir.mkdir(parents=True)
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        write_json(
            partial_manifest_path,
            {
                "schema_version": 1,
                "identity": identity,
                "started_at": started,
                "prior_failures": prior_failures,
            },
        )
    return started, prior_failures, resume_history


def write_score_failure_diagnostic(
    output_dir: Path,
    result: RunResult,
    error: str,
    run_id: str,
    known_paths: Iterable[Path],
) -> dict[str, str]:
    """Persist a redacted structured-scorer payload rejected by validation."""
    if result.invocation.phase != "score":
        raise EvaluationError("score failure diagnostics require a score invocation")
    payload_text = redact_text(result.answer, known_paths)
    diagnostic = {
        "schema_version": 1,
        "id": result.invocation.id,
        "phase": result.invocation.phase,
        "variant": result.invocation.variant,
        "repetition": result.invocation.repetition,
        "attempts": result.attempts,
        "error": redact_text(error, known_paths),
        "payload_sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        "payload_text": payload_text,
        "metadata": redact_value(result.metadata, known_paths),
    }
    diagnostic_path = (
        output_dir
        / "diagnostics"
        / "score-failures"
        / f"{result.invocation.id}-{run_id}.json"
    )
    write_json(diagnostic_path, diagnostic)
    return {
        "path": diagnostic_path.relative_to(output_dir).as_posix(),
        "sha256": file_digest(diagnostic_path),
        "payload_sha256": diagnostic["payload_sha256"],
    }


def result_record(result: RunResult, known_paths: Iterable[Path]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": result.invocation.id,
        "phase": result.invocation.phase,
        "variant": result.invocation.variant,
        "repetition": result.invocation.repetition,
        "success": result.success,
        "attempts": result.attempts,
        "error": redact_text(result.error, known_paths),
    }
    if result.invocation.source_id is not None:
        record["source_id"] = result.invocation.source_id
    if result.metadata:
        record["metadata"] = result.metadata
    return record


def answer_path(output_dir: Path, invocation: Invocation) -> Path:
    if invocation.phase not in ("routing", "behavior"):
        raise EvaluationError(f"no answer path for phase {invocation.phase}")
    return output_dir / "answers" / invocation.phase / f"{invocation.id}.md"


def summary_markdown(summary: dict[str, Any]) -> str:
    routing = summary["routing"]
    behavior = summary["behavior"]
    gates = summary["gates"]
    case_label = {
        "airi-v0.2-baseline": "AIRI v0.2",
        "marktext-v0.2-baseline": "MarkText v0.2",
    }.get(summary.get("case_id"), summary.get("case_id", "Architecture"))
    title = (
        f"{case_label} routing profile"
        if summary["phases"] == "routing"
        else "Architecture-review score-only profile"
        if summary["phases"] == "score"
        else f"{case_label} forward-evaluation baseline"
    )
    lines = [
        f"# {title}",
        "",
        f"Dataset complete: **{'yes' if summary['dataset_complete'] else 'no'}**.",
        "",
    ]
    if summary["phases"] != "score":
        lines.extend(
            [
                "## Routing",
                "",
                "| Polarity | Loaded | Successful | Planned |",
                "| --- | ---: | ---: | ---: |",
                f"| Positive | {routing['positive']['loaded']} | {routing['positive']['successful']} | {routing['positive']['planned']} |",
                f"| Negative | {routing['negative']['loaded']} | {routing['negative']['successful']} | {routing['negative']['planned']} |",
                "",
            ]
        )
    if summary["phases"] in ("all", "score"):
        lines.extend(
            [
                "## Behavior",
                "",
                "| Variant | Average | Totals | Factual errors |",
                "| --- | ---: | --- | ---: |",
                f"| Control | {behavior['control']['average']} | {behavior['control']['totals']} | {behavior['control']['factual_errors']} |",
                f"| Treatment | {behavior['treatment']['average']} | {behavior['treatment']['totals']} | {behavior['treatment']['factual_errors']} |",
                "",
            ]
        )
    lines.extend(
        [
            "## Gates",
            "",
            f"- Routing: **{('pass' if gates['routing'] else 'fail') if gates.get('routing') is not None else 'not run'}**",
            f"- Accuracy: **{('pass' if gates['accuracy'] else 'fail') if gates.get('accuracy') is not None else 'not run'}**",
            f"- Behavior: **{('pass' if gates['behavior'] else 'fail') if gates['behavior'] is not None else 'not run'}**",
            f"- Generalization: **{('pass' if gates['generalization'] else 'fail') if gates['generalization'] is not None else 'not run'}**",
            f"- Overall for executed phases: **{'pass' if gates['overall'] else 'fail'}**",
            "",
            "Raw final answers and independent structured scores are stored beside this summary. A failed gate is baseline evidence, not an instruction to edit the Skill in this run.",
            "",
        ]
    )
    if summary["skipped"]:
        lines.extend(["## Skipped planned calls", "", *[f"- `{item}`" for item in summary["skipped"]], ""])
    return "\n".join(lines)


def load_rescore_behavior_answers(
    source_dir: Path,
    case: dict[str, Any],
    repetitions: int,
    scorer_runtime: str,
    rubric_path: Path,
    schema_path: Path,
) -> tuple[dict[str, RunResult], dict[str, Any]]:
    """Load producer answers for score-only runs.

    Older v0.2 result manifests did not record rubric/schema digests. They are
    accepted as legacy sources, while any newer manifest with a contract must
    match the requested contract byte-for-byte. The source dataset may be
    incomplete when its producer answers are complete but scorer outputs were
    rejected; score-only runs replace only that scoring phase.
    """
    source_dir = source_dir.resolve()
    manifest_path = source_dir / "manifest.json"
    summary_path = source_dir / "summary.json"
    if not manifest_path.is_file() or not summary_path.is_file():
        raise EvaluationError(
            "rescore source must contain manifest.json and summary.json"
    )
    manifest = load_json(manifest_path)
    summary = load_json(summary_path)
    source_dataset_complete = summary.get("dataset_complete") is True
    expected_case = {"id": case["id"], "sha256": case_digest(case)}
    if manifest.get("case") != expected_case:
        raise EvaluationError("rescore source case does not match the requested case")
    if manifest.get("repository") != case.get("repository"):
        raise EvaluationError(
            "rescore source repository does not match the requested case"
        )
    if manifest.get("skill") != case.get("skill"):
        raise EvaluationError("rescore source Skill does not match the requested case")
    source_profile = manifest.get("profile")
    if not isinstance(source_profile, dict):
        raise EvaluationError("rescore source is missing its profile")
    producer_runtime = source_profile.get("runtime")
    if producer_runtime not in {"codex", "claude-code"}:
        raise EvaluationError("rescore source runtime is unsupported")
    if source_profile.get("repetitions") != repetitions:
        raise EvaluationError(
            "rescore source repetition count does not match the requested profile"
        )

    requested_contract = contract_identity(rubric_path, schema_path)
    source_contract = manifest.get("contract")
    if source_contract is not None and source_contract != requested_contract:
        raise EvaluationError("rescore source rubric or schema does not match")
    contract_status = "matched" if source_contract is not None else "legacy-unrecorded"

    matrix = build_invocation_matrix(case, repetitions, producer_runtime)
    records = {
        record.get("id"): record
        for record in manifest.get("results", [])
        if isinstance(record, dict)
    }
    answers: dict[str, RunResult] = {}
    for invocation in matrix:
        if invocation.phase != "behavior":
            continue
        record = records.get(invocation.id)
        if not isinstance(record, dict) or not record.get("success"):
            raise EvaluationError(
                f"rescore source is missing successful behavior result {invocation.id}"
            )
        answer_file = source_dir / "answers" / "behavior" / f"{invocation.id}.md"
        if not answer_file.is_file():
            raise EvaluationError(f"rescore source is missing {answer_file}")
        answers[invocation.id] = RunResult(
            invocation=invocation,
            success=True,
            answer=answer_file.read_text(encoding="utf-8").strip(),
            attempts=int(record.get("attempts", 0)),
            metadata=record.get("metadata", {}),
        )
    return answers, {
        "name": source_dir.name,
        "manifest_sha256": file_digest(manifest_path),
        "case_sha256": expected_case["sha256"],
        "profile_id": source_profile.get("profile_id"),
        "runtime": producer_runtime,
        "scorer_runtime": scorer_runtime,
        "producer_profile": dict(source_profile),
        "producer_run_id": manifest.get("run_id"),
        "contract_status": contract_status,
        "source_dataset_complete": source_dataset_complete,
        "producer_answers_complete": True,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=DEFAULT_CASE)
    parser.add_argument(
        "--repository-source",
        "--airi-source",
        dest="repository_source",
        type=Path,
        default=DEFAULT_AIRI_SOURCE,
        help="pinned repository checkout; --airi-source is a compatibility alias",
    )
    parser.add_argument(
        "--rubric",
        type=Path,
        default=DEFAULT_RUBRIC,
        help="scoring rubric used by independent scorers",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help="structured score schema passed to the runtime",
    )
    parser.add_argument(
        "--rescore-from",
        type=Path,
        help="score existing behavior answers from a completed result directory",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--runtime", choices=("codex", "claude-code"), default="codex"
    )
    parser.add_argument("--model")
    parser.add_argument(
        "--model-label",
        help="manifest label when the runtime uses a configured default model",
    )
    parser.add_argument("--profile-id")
    parser.add_argument("--reasoning-effort")
    parser.add_argument(
        "--phases", choices=("all", "routing", "score"), default="all"
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument(
        "--call-timeout-seconds",
        type=int,
        help="hard timeout per model call; defaults to the selected runtime profile",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume a matching interrupted profile from per-sample checkpoints",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    case = load_json(args.case.resolve())
    rubric_path = args.rubric.resolve()
    schema_path = args.schema.resolve()
    if not rubric_path.is_file() or not schema_path.is_file():
        raise EvaluationError("rubric and schema files must exist")
    schema = load_json(schema_path)
    require_accuracy = schema_requires_accuracy(schema)
    if args.rescore_from is not None and args.phases != "score":
        raise EvaluationError("--rescore-from requires --phases score")
    if args.phases == "score" and args.rescore_from is None:
        raise EvaluationError("--phases score requires --rescore-from")
    runtime_config = case["codex" if args.runtime == "codex" else "claude_code"]
    if args.runtime == "codex":
        args.model = args.model or runtime_config["model"]
    reasoning_effort = args.reasoning_effort or runtime_config["reasoning_effort"]
    call_timeout_seconds = (
        args.call_timeout_seconds or runtime_config["call_timeout_seconds"]
    )
    if call_timeout_seconds < 1:
        raise EvaluationError("call timeout must be at least 1 second")
    model_label = args.model_label or args.model or "configured-default"
    matrix = (
        build_score_invocation_matrix(case, args.repetitions, args.runtime)
        if args.phases == "score"
        else build_invocation_matrix(case, args.repetitions, args.runtime)
    )
    if args.phases == "routing":
        matrix = [item for item in matrix if item.phase == "routing"]
    if args.dry_run:
        print(json.dumps([dataclasses.asdict(item) for item in matrix], ensure_ascii=False, indent=2))
        print(f"planned_agent_calls={len(matrix)}", file=sys.stderr)
        return 0
    if args.max_concurrency < 1 or args.max_concurrency > 3:
        raise EvaluationError("max concurrency must be between 1 and 3")
    expected_version = runtime_config["cli_version"]
    actual_version = codex_version() if args.runtime == "codex" else claude_version()
    if actual_version != expected_version:
        raise EvaluationError(
            f"{args.runtime} version mismatch: expected {expected_version}, got {actual_version}"
        )
    rescore_answers: dict[str, RunResult] = {}
    rescore_source: dict[str, Any] | None = None
    if args.rescore_from is not None:
        rescore_answers, rescore_source = load_rescore_behavior_answers(
            args.rescore_from,
            case,
            args.repetitions,
            args.runtime,
            rubric_path,
            schema_path,
        )
    output_dir = args.output_dir.resolve()
    partial_manifest_path = output_dir / "partial-manifest.json"
    manifest_path = output_dir / "manifest.json"
    checkpoints = output_dir / ".checkpoints"
    model_slug = re.sub(r"[^a-z0-9]+", "-", model_label.lower()).strip("-")
    configuration_manager = runtime_config.get("configuration_manager")
    manager_slug = ""
    if configuration_manager:
        manager_slug = (
            re.sub(r"[^a-z0-9]+", "-", configuration_manager.lower()).strip("-") + "-"
        )
    profile_id = (
        args.profile_id
        or f"{args.runtime}-{manager_slug}{model_slug}-{reasoning_effort}"
    )
    if (
        args.runtime == "codex"
        and args.model == case["codex"]["model"]
        and reasoning_effort == case["codex"]["reasoning_effort"]
        and args.profile_id is None
    ):
        profile_id = case["codex"]["profile_id"]
    profile = {
        "profile_id": profile_id,
        "runtime": args.runtime,
        "cli_version": actual_version,
        "model": model_label,
        "model_argument": args.model,
        "configuration_manager": configuration_manager,
        "reasoning_effort": reasoning_effort,
        "call_timeout_seconds": call_timeout_seconds,
        "ephemeral": True,
        "sandbox": "read-only" if args.runtime == "codex" else "restricted-read-tools",
        "max_concurrency": args.max_concurrency,
        "repetitions": args.repetitions,
        "phases": args.phases,
    }
    identity = {
        "case": {"id": case["id"], "sha256": case_digest(case)},
        "repository": case["repository"],
        "skill": case["skill"],
        "contract": contract_identity(rubric_path, schema_path),
        "profile": profile,
        "planned_calls": len(matrix),
    }
    if rescore_source is not None:
        identity["rescore_source"] = rescore_source
    run_id = uuid.uuid4().hex
    output_lock = OutputDirectoryLock(output_dir)
    output_lock.acquire()
    try:
        started, prior_failures, resume_history = prepare_output_state(
            output_dir,
            partial_manifest_path,
            manifest_path,
            checkpoints,
            args.resume,
            identity,
            call_timeout_seconds,
        )
    except BaseException:
        output_lock.release()
        raise

    transient: Path | None = None
    checkout_root: Path | None = None
    try:
        transient = Path(tempfile.mkdtemp(prefix="airi-forward-eval-transient-"))
        checkout_root = Path(tempfile.mkdtemp(prefix="airi-forward-eval-checkouts-"))
        known_paths = (
            ROOT,
            args.repository_source.resolve(),
            transient,
            checkout_root,
            output_dir,
        )
        invocation_by_id = {invocation.id: invocation for invocation in matrix}
        results_by_id: dict[str, RunResult] = {}
        records_by_id: dict[str, dict[str, Any]] = {}
        skipped: list[str] = []
        scores: dict[str, dict[str, Any]] = {}

        if checkpoints.is_dir():
            for path in sorted(checkpoints.glob("*.json")):
                record = load_json(path)
                invocation = invocation_by_id.get(record.get("id", ""))
                if invocation is None:
                    raise EvaluationError(f"checkpoint is not part of this profile: {path}")
                records_by_id[invocation.id] = record
                if not record.get("success"):
                    continue
                if invocation.phase == "score":
                    score_path = output_dir / "scores" / f"{invocation.id}.json"
                    score = load_json(score_path)
                    validate_score(score, require_accuracy=require_accuracy)
                    scores[invocation.id] = score
                    answer = json.dumps(score, ensure_ascii=False)
                else:
                    path = answer_path(output_dir, invocation)
                    if not path.is_file():
                        raise EvaluationError(f"successful checkpoint is missing {path}")
                    answer = path.read_text(encoding="utf-8").strip()
                results_by_id[invocation.id] = RunResult(
                    invocation=invocation,
                    success=True,
                    answer=answer,
                    attempts=int(record.get("attempts", 0)),
                    metadata=record.get("metadata", {}),
                )
    except BaseException:
        if transient is not None:
            shutil.rmtree(transient, ignore_errors=True)
        if checkout_root is not None:
            shutil.rmtree(checkout_root, ignore_errors=True)
        output_lock.release()
        raise

    assert transient is not None
    assert checkout_root is not None

    def persist_result(result: RunResult) -> None:
        if result.success and result.invocation.phase in ("routing", "behavior"):
            result.answer = redact_text(result.answer, known_paths)
            path = answer_path(output_dir, result.invocation)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(result.answer + "\n", encoding="utf-8")
        results_by_id[result.invocation.id] = result
        record = result_record(result, known_paths)
        records_by_id[result.invocation.id] = record
        if not result.success:
            prior_failures.append(
                {
                    **record,
                    "run_id": run_id,
                    "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            )
            write_json(
                partial_manifest_path,
                {
                    "schema_version": 1,
                    "identity": identity,
                    "started_at": started,
                    "resume_history": resume_history,
                    "prior_failures": prior_failures,
                },
            )
        write_json(checkpoints / f"{result.invocation.id}.json", record)

    try:
        checkouts = prepare_checkouts(
            args.repository_source,
            case["repository"]["commit"],
            case,
            checkout_root,
            args.runtime,
        )
        routing_invocations = [item for item in matrix if item.phase == "routing"]

        def run_producer(invocation: Invocation) -> RunResult:
            checkout = checkouts["treatment"] if invocation.variant != "control" else checkouts["control"]

            def execute(item: Invocation) -> AttemptResult:
                if args.runtime == "codex":
                    return run_codex(
                        item,
                        checkout,
                        args.model or "",
                        reasoning_effort,
                        transient,
                        timeout_seconds=call_timeout_seconds,
                    )
                return run_claude(
                    item,
                    checkout,
                    args.model,
                    reasoning_effort,
                    timeout_seconds=call_timeout_seconds,
                )

            return execute_with_retry(
                invocation,
                execute,
                lambda: assert_clean(checkout),
            )

        if args.phases != "score":
            pending_routing = [
                item
                for item in routing_invocations
                if not results_by_id.get(item.id, RunResult(item, False)).success
            ]
            _, routing_skipped = run_case_groups(
                pending_routing,
                args.repetitions,
                args.max_concurrency,
                run_producer,
                persist_result,
                successful_repetitions={
                    (result.invocation.case_id, result.invocation.repetition)
                    for result in results_by_id.values()
                    if result.success and result.invocation.phase == "routing"
                },
            )
            skipped.extend(routing_skipped)

            behavior_invocations = [item for item in matrix if item.phase == "behavior"]
            pending_behavior = [
                item
                for item in behavior_invocations
                if not results_by_id.get(item.id, RunResult(item, False)).success
            ]
            _, behavior_skipped = run_case_groups(
                pending_behavior,
                args.repetitions,
                args.max_concurrency,
                run_producer,
                persist_result,
                successful_repetitions={
                    (result.invocation.case_id, result.invocation.repetition)
                    for result in results_by_id.values()
                    if result.success and result.invocation.phase == "behavior"
                },
            )
            skipped.extend(behavior_skipped)
            behavior_answers = {
                invocation.id: results_by_id[invocation.id]
                for invocation in behavior_invocations
                if invocation.id in results_by_id
                and results_by_id[invocation.id].success
            }
        else:
            behavior_invocations = []
            behavior_answers = rescore_answers

        rubric = rubric_path.read_text(encoding="utf-8")
        scorer_invocations = [item for item in matrix if item.phase == "score"]
        runnable_scorers: list[Invocation] = []
        for scorer in scorer_invocations:
            existing = results_by_id.get(scorer.id)
            if existing is not None and existing.success:
                continue
            producer = behavior_answers.get(scorer.source_id or "")
            if producer is None:
                skipped.append(scorer.id)
                continue
            runnable_scorers.append(
                dataclasses.replace(
                    scorer,
                    prompt=scorer_prompt(
                        producer.invocation.prompt,
                        producer.answer,
                        rubric,
                    ),
                )
            )

        def run_scorer(invocation: Invocation) -> RunResult:
            def execute(item: Invocation) -> AttemptResult:
                if args.runtime == "codex":
                    return run_codex(
                        item,
                        checkouts["control"],
                        args.model or "",
                        reasoning_effort,
                        transient,
                        schema_path,
                        timeout_seconds=call_timeout_seconds,
                    )
                return run_claude(
                    item,
                    checkouts["control"],
                    args.model,
                    reasoning_effort,
                    schema_path,
                    timeout_seconds=call_timeout_seconds,
                )

            return execute_with_retry(
                invocation,
                execute,
                lambda: assert_clean(checkouts["control"]),
            )

        def persist_score(result: RunResult) -> None:
            if result.success:
                try:
                    score = json.loads(result.answer)
                    validate_score(score, require_accuracy=require_accuracy)
                except (json.JSONDecodeError, EvaluationError) as error:
                    result.success = False
                    result.error = str(error)
                    result.metadata = dict(result.metadata)
                    result.metadata["failure_diagnostic"] = write_score_failure_diagnostic(
                        output_dir,
                        result,
                        result.error,
                        run_id,
                        known_paths,
                    )
                else:
                    score = redact_value(score, known_paths)
                    scores[result.invocation.id] = score
                    write_json(
                        output_dir / "scores" / f"{result.invocation.id}.json", score
                    )
            persist_result(result)

        _, scorer_skipped = run_case_groups(
            runnable_scorers,
            args.repetitions,
            args.max_concurrency,
            run_scorer,
            persist_score,
            successful_repetitions={
                (result.invocation.case_id, result.invocation.repetition)
                for result in results_by_id.values()
                if result.success and result.invocation.phase == "score"
            },
        )
        skipped.extend(scorer_skipped)

        routing_results = [
            results_by_id[item.id]
            for item in routing_invocations
            if item.id in results_by_id
        ]
        summary = aggregate_results(
            case,
            routing_results,
            scores,
            sorted(set(skipped)),
            repetitions=args.repetitions,
            phases=args.phases,
        )
        write_json(output_dir / "summary.json", summary)
        (output_dir / "summary.md").write_text(summary_markdown(summary), encoding="utf-8")
        manifest = {
            "schema_version": 1,
            **identity,
            "run_id": run_id,
            "started_at": started,
            "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "results": sorted(records_by_id.values(), key=lambda item: item["id"]),
            "skipped": sorted(set(skipped)),
            "observed_models": sorted(
                {
                    model
                    for record in records_by_id.values()
                    for model in record.get("metadata", {}).get("observed_models", [])
                }
            ),
        }
        if prior_failures:
            manifest["prior_failures"] = prior_failures
        if resume_history:
            manifest["resume_history"] = resume_history
        write_json(manifest_path, manifest)
        cleanup_partial_state(partial_manifest_path, checkpoints)
        print(summary_markdown(summary))
        return 0 if summary["dataset_complete"] else 2
    finally:
        shutil.rmtree(transient, ignore_errors=True)
        shutil.rmtree(checkout_root, ignore_errors=True)
        output_lock.release()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvaluationError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
