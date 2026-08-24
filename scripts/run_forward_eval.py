#!/usr/bin/env python3
"""Run the reproducible AIRI routing and architecture-review forward evaluation."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import threading
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
        "<!-- AIRI_FORWARD_EVAL_ONLY: If this Skill is loaded for the current "
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
        raise EvaluationError(f"AIRI source is not a Git checkout: {source}")
    assert_clean(source)
    if git(source, "rev-parse", f"{commit}^{{commit}}").stdout.strip() != commit:
        raise EvaluationError(f"AIRI source does not contain expected commit {commit}")
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
        raise EvaluationError("treatment checkout moved away from the pinned AIRI commit")
    assert_clean(treatment)
    return checkouts


def redact_text(text: str, paths: Iterable[Path] = ()) -> str:
    redacted = text
    for path in sorted((str(path.resolve()) for path in paths), key=len, reverse=True):
        redacted = redacted.replace(path, "<evaluation-path>")
    redacted = re.sub(r"/Users/[^/\s]+", "/Users/<redacted>", redacted)
    redacted = re.sub(r"/home/[^/\s]+", "/home/<redacted>", redacted)
    return redacted


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
) -> tuple[list[RunResult], list[str]]:
    by_case: dict[str, dict[int, Invocation]] = {}
    for invocation in invocations:
        by_case.setdefault(invocation.case_id, {})[invocation.repetition] = invocation
    stopped: set[str] = set()
    results: list[RunResult] = []
    skipped: list[str] = []
    for repetition in range(1, repetitions + 1):
        wave: list[Invocation] = []
        for case_id, samples in by_case.items():
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
                if not result.success:
                    stopped.add(result.invocation.case_id)
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
        command.extend(
            [
                "--json-schema",
                json.dumps(load_json(schema), ensure_ascii=False, separators=(",", ":")),
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

Score all nine rubric dimensions from 0 to 2. Every factual claim must be checked against repository files or Git history. Independently report the current desktop platform and the runtime boundaries that the answer actually identifies. If the repository contains a legacy platform, report whether the answer incorrectly treats that legacy platform as current. Compute `total` as the exact sum of the nine scores. Record each factual error separately. Keep the rationale concise.

## Original user request

{source_prompt}

## Raw answer

{answer}

## Rubric

{rubric}
"""


def validate_score(score: dict[str, Any]) -> None:
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
            "planned": len(case["routing"][polarity]) * repetitions,
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
        }

    positive_loaded = routing_counts["positive"]["loaded"]
    negative_loaded = routing_counts["negative"]["loaded"]
    control_average = behavior["control"]["average"]
    treatment_average = behavior["treatment"]["average"]
    required = case["behavior"]["required_nonzero_dimensions"]
    treatment_scores = [
        score for score_id, score in scores.items() if "score-treatment-" in score_id
    ]
    routing_planned = sum(item["planned"] for item in routing_counts.values())
    routing_complete = (
        len(routing) == routing_planned and all(result.success for result in routing)
    )
    complete = not skipped and routing_complete
    if phases == "all":
        complete = complete and len(scores) == 2 * repetitions
    baseline_repetitions = case["codex"]["repetitions"]
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
    routing_pass = (
        positive_loaded >= positive_required and negative_loaded <= negative_allowed
    )
    behavior_pass = bool(
        treatment_average is not None
        and control_average is not None
        and treatment_average >= case["behavior"]["minimum_treatment_average"]
        and treatment_average - control_average >= case["behavior"]["minimum_improvement"]
        and all(score["dimensions"][name] > 0 for score in treatment_scores for name in required)
    )
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
    overall = complete and routing_pass
    if phases == "all":
        overall = overall and behavior_pass and generalization_pass
    return {
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
    title = (
        "AIRI v0.2 routing profile"
        if summary["phases"] == "routing"
        else "AIRI v0.2 forward-evaluation baseline"
    )
    lines = [
        f"# {title}",
        "",
        f"Dataset complete: **{'yes' if summary['dataset_complete'] else 'no'}**.",
        "",
        "## Routing",
        "",
        "| Polarity | Loaded | Successful | Planned |",
        "| --- | ---: | ---: | ---: |",
        f"| Positive | {routing['positive']['loaded']} | {routing['positive']['successful']} | {routing['positive']['planned']} |",
        f"| Negative | {routing['negative']['loaded']} | {routing['negative']['successful']} | {routing['negative']['planned']} |",
        "",
    ]
    if summary["phases"] == "all":
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
            f"- Routing: **{'pass' if gates['routing'] else 'fail'}**",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--airi-source", type=Path, default=DEFAULT_AIRI_SOURCE)
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
    parser.add_argument("--phases", choices=("all", "routing"), default="all")
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
    matrix = build_invocation_matrix(case, args.repetitions, args.runtime)
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
        "profile": profile,
        "planned_calls": len(matrix),
    }
    if output_dir.exists():
        if not args.resume:
            raise EvaluationError(f"output directory already exists: {output_dir}")
        if manifest_path.exists():
            raise EvaluationError(f"evaluation is already complete: {manifest_path}")
        if not partial_manifest_path.is_file():
            raise EvaluationError(
                f"cannot resume without {partial_manifest_path.name}: {output_dir}"
            )
        partial_manifest = load_json(partial_manifest_path)
        if partial_manifest.get("identity") != identity:
            raise EvaluationError("resume profile does not match the interrupted evaluation")
        started = partial_manifest["started_at"]
    else:
        output_dir.mkdir(parents=True)
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        write_json(
            partial_manifest_path,
            {"schema_version": 1, "identity": identity, "started_at": started},
        )

    transient = Path(tempfile.mkdtemp(prefix="airi-forward-eval-transient-"))
    checkout_root = Path(tempfile.mkdtemp(prefix="airi-forward-eval-checkouts-"))
    known_paths = (ROOT, args.airi_source.resolve(), transient, checkout_root, output_dir)
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
                validate_score(score)
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

    def persist_result(result: RunResult) -> None:
        if result.success and result.invocation.phase in ("routing", "behavior"):
            result.answer = redact_text(result.answer, known_paths)
            path = answer_path(output_dir, result.invocation)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(result.answer + "\n", encoding="utf-8")
        results_by_id[result.invocation.id] = result
        record = result_record(result, known_paths)
        records_by_id[result.invocation.id] = record
        write_json(checkpoints / f"{result.invocation.id}.json", record)

    try:
        checkouts = prepare_checkouts(
            args.airi_source,
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
        )
        skipped.extend(behavior_skipped)
        behavior_answers = {
            invocation.id: results_by_id[invocation.id]
            for invocation in behavior_invocations
            if invocation.id in results_by_id and results_by_id[invocation.id].success
        }

        rubric = DEFAULT_RUBRIC.read_text(encoding="utf-8")
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
                        DEFAULT_SCHEMA,
                        timeout_seconds=call_timeout_seconds,
                    )
                return run_claude(
                    item,
                    checkouts["control"],
                    args.model,
                    reasoning_effort,
                    DEFAULT_SCHEMA,
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
                    validate_score(score)
                except (json.JSONDecodeError, EvaluationError) as error:
                    result.success = False
                    result.error = str(error)
                else:
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
        write_json(manifest_path, manifest)
        partial_manifest_path.unlink()
        shutil.rmtree(checkpoints, ignore_errors=True)
        print(summary_markdown(summary))
        return 0 if summary["dataset_complete"] else 2
    finally:
        shutil.rmtree(transient, ignore_errors=True)
        shutil.rmtree(checkout_root, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvaluationError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
