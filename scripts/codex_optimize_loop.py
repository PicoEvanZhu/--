#!/usr/bin/env python3

import argparse
import json
import shlex
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ShellResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_sec: float


@dataclass
class PlannerOutput:
    question: str
    candidates: List[Dict[str, str]]
    chosen_id: str
    raw_message: str


def run_process(command: List[str], cwd: Path, timeout: Optional[int] = None) -> ShellResult:
    start = time.time()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return ShellResult(
        command=" ".join(shlex.quote(item) for item in command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_sec=time.time() - start,
    )


def run_shell(command: str, cwd: Path, timeout: Optional[int] = None) -> ShellResult:
    start = time.time()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        shell=True,
        timeout=timeout,
    )
    return ShellResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_sec=time.time() - start,
    )


def ensure_git_repo(repo: Path) -> None:
    result = run_process(["git", "rev-parse", "--is-inside-work-tree"], repo)
    if result.returncode != 0 or result.stdout.strip() != "true":
        print("[error] 当前目录不是 Git 仓库，无法执行循环优化", file=sys.stderr)
        sys.exit(2)


def get_changed_files(repo: Path) -> List[str]:
    tracked = run_process(["git", "diff", "--name-only"], repo)
    untracked = run_process(["git", "ls-files", "--others", "--exclude-standard"], repo)

    items: List[str] = []
    if tracked.returncode == 0:
        items.extend(line.strip() for line in tracked.stdout.splitlines() if line.strip())
    if untracked.returncode == 0:
        items.extend(line.strip() for line in untracked.stdout.splitlines() if line.strip())

    return sorted(set(items))


def get_diff_stat(repo: Path) -> str:
    result = run_process(["git", "diff", "--stat"], repo)
    return result.stdout.strip() if result.returncode == 0 else ""


def truncate_text(text: str, size: int) -> str:
    if len(text) <= size:
        return text
    return text[:size] + "\n...(truncated)..."


def summarize_checks(checks: List[ShellResult]) -> str:
    if not checks:
        return "本轮没有配置检查命令"

    parts: List[str] = []
    for index, item in enumerate(checks, start=1):
        status = "PASS" if item.returncode == 0 else "FAIL"
        parts.append(f"[{index}] {status} | {item.command}")
        content = (item.stdout + "\n" + item.stderr).strip()
        if content:
            parts.append(truncate_text(content, 1200))
    return "\n".join(parts)


def extract_json(text: str) -> Optional[Dict]:
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        snippet = text[start : end + 1]
        try:
            payload = json.loads(snippet)
            if isinstance(payload, dict):
                return payload
        except Exception:
            return None

    return None


def parse_planner_output(raw_message: str) -> PlannerOutput:
    payload = extract_json(raw_message)

    if not payload:
        return PlannerOutput(
            question="当前可优化项较多，你希望优先稳定性、性能，还是新功能？",
            candidates=[
                {
                    "id": "fallback-1",
                    "title": "优先修复检查失败或高风险问题",
                    "impact": "high",
                    "effort": "m",
                    "reason": "先保障系统稳定运行",
                    "acceptance": "检查命令全部通过",
                }
            ],
            chosen_id="fallback-1",
            raw_message=raw_message,
        )

    question = str(payload.get("question") or "当前有哪些优化内容你希望优先？")
    chosen_id = str(payload.get("chosen_id") or "")

    raw_candidates = payload.get("candidates")
    candidates: List[Dict[str, str]] = []
    if isinstance(raw_candidates, list):
        for idx, item in enumerate(raw_candidates, start=1):
            if not isinstance(item, dict):
                continue
            candidates.append(
                {
                    "id": str(item.get("id") or f"opt-{idx}"),
                    "title": str(item.get("title") or "未命名优化项"),
                    "impact": str(item.get("impact") or "unknown"),
                    "effort": str(item.get("effort") or "unknown"),
                    "reason": str(item.get("reason") or ""),
                    "acceptance": str(item.get("acceptance") or ""),
                }
            )

    if not candidates:
        candidates = [
            {
                "id": "fallback-1",
                "title": "优先修复检查失败或高风险问题",
                "impact": "high",
                "effort": "m",
                "reason": "先保障系统稳定运行",
                "acceptance": "检查命令全部通过",
            }
        ]

    if not chosen_id:
        chosen_id = candidates[0]["id"]

    return PlannerOutput(
        question=question,
        candidates=candidates,
        chosen_id=chosen_id,
        raw_message=raw_message,
    )


def choose_candidate(plan: PlannerOutput) -> Dict[str, str]:
    for item in plan.candidates:
        if item.get("id") == plan.chosen_id:
            return item
    return plan.candidates[0]


def is_concurrency_blocked(result: ShellResult) -> bool:
    haystack = (result.stderr + "\n" + result.stdout).upper()
    return "CONCURRENCY_LIMIT_EXCEEDED" in haystack or "429 TOO MANY REQUESTS" in haystack


def build_planner_prompt(
    goal: str,
    round_index: int,
    changed_files: List[str],
    diff_stat: str,
    previous_exec_summary: str,
    check_summary: str,
) -> str:
    changed_preview = "\n".join(changed_files[:80]) if changed_files else "(无)"
    previous_exec_summary = truncate_text(previous_exec_summary.strip(), 1800) or "(无)"

    prompt = f"""
你是“优化规划师”。本步骤只做分析和提问，不要改任何文件。

项目终极目标：
{goal}

当前轮次：{round_index}

现有变更文件：
{changed_preview}

diff 统计：
{diff_stat or '(无)'}

上一轮执行摘要：
{previous_exec_summary}

上一轮检查结果：
{check_summary}

请完成两件事：
1) 提出 3-6 个可执行且可验证的优化项
2) 提一个问题：“有哪些优化内容你希望优先？”

输出严格 JSON（不要输出其他文本）：
{{
  "question": "...",
  "candidates": [
    {{
      "id": "opt-1",
      "title": "...",
      "impact": "high|medium|low",
      "effort": "s|m|l",
      "reason": "...",
      "acceptance": "..."
    }}
  ],
  "chosen_id": "opt-1"
}}

规则：
- chosen_id 是你建议本轮优先执行的项
- 本步骤严禁写文件
"""
    return textwrap.dedent(prompt).strip()


def build_executor_prompt(
    goal: str,
    round_index: int,
    plan: PlannerOutput,
    chosen: Dict[str, str],
    auto_answer: str,
    checks: List[str],
) -> str:
    checks_text = "\n".join(f"- {cmd}" for cmd in checks) if checks else "- (无)"
    options_text = "\n".join(
        f"- [{item['id']}] {item['title']} | impact={item['impact']} effort={item['effort']}"
        for item in plan.candidates
    )

    prompt = f"""
你是“优化执行器”，请在当前仓库进行真实改动。

终极目标：
{goal}

当前轮次：{round_index}

规划阶段问题：
{plan.question}

系统自动回答：
{auto_answer}

候选优化项：
{options_text}

本轮执行项：
[{chosen['id']}] {chosen['title']}
- reason: {chosen['reason']}
- acceptance: {chosen['acceptance']}

执行要求：
1) 做高价值、可验证的小步改动，避免无意义重构。
2) 改完后运行必要验证，并尽量覆盖下列命令范围：
{checks_text}
3) 输出简洁总结：改了什么、验证结果、下一轮建议。
"""
    return textwrap.dedent(prompt).strip()


def run_codex_exec(
    repo: Path,
    codex_bin: str,
    prompt: str,
    output_file: Path,
    timeout_sec: int,
    model: Optional[str],
    profile: Optional[str],
    full_auto: bool,
    sandbox: Optional[str],
    dangerous: bool,
) -> ShellResult:
    command: List[str] = [codex_bin]

    if sandbox:
        command.extend(["--sandbox", sandbox])

    command.append("exec")
    command.extend(["--cd", str(repo), "--output-last-message", str(output_file)])

    if model:
        command.extend(["--model", model])
    if profile:
        command.extend(["--profile", profile])
    if full_auto:
        command.append("--full-auto")
    if dangerous:
        command.append("--dangerously-bypass-approvals-and-sandbox")

    command.append(prompt)
    return run_process(command, repo, timeout=timeout_sec)


def write_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="两阶段循环优化：先提优化问题，再执行优化")
    parser.add_argument("--goal", required=True, help="全局优化目标")
    parser.add_argument("--repo", default=".", help="仓库目录")
    parser.add_argument("--max-rounds", type=int, default=5, help="非 infinite 模式最大轮次")
    parser.add_argument("--infinite", action="store_true", help="无限循环（直到 STOP 文件或手动停止）")
    parser.add_argument("--sleep-seconds", type=int, default=8, help="每轮间隔秒数")
    parser.add_argument("--retry-on-busy", type=int, default=30, help="并发占用时重试间隔秒数")
    parser.add_argument("--planner-timeout", type=int, default=900, help="规划步骤超时")
    parser.add_argument("--executor-timeout", type=int, default=1800, help="执行步骤超时")
    parser.add_argument("--auto-answer", default="默认优先执行对散户价值最高且风险可控的优化项", help="自动回答规划问题")
    parser.add_argument("--check", action="append", default=[], help="每轮后检查命令，可重复")
    parser.add_argument("--codex-bin", default="codex", help="codex 命令路径")
    parser.add_argument("--model", default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--dangerous", action="store_true", help="允许无沙箱执行")
    parser.add_argument("--no-full-auto", action="store_true", help="关闭执行步骤 full-auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    ensure_git_repo(repo)

    loop_root = repo / ".codex-loop"
    loop_root.mkdir(parents=True, exist_ok=True)
    run_dir = loop_root / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    stop_file = loop_root / "STOP"
    status_file = run_dir / "status.json"

    print("[info] repo:", repo, flush=True)
    print("[info] run dir:", run_dir, flush=True)
    print("[info] stop file:", stop_file, flush=True)

    previous_exec_message = ""
    previous_checks: List[ShellResult] = []

    round_index = 0
    while True:
        round_index += 1

        if not args.infinite and round_index > args.max_rounds:
            print("[done] reached max rounds", flush=True)
            break

        if stop_file.exists():
            print("[done] STOP file detected", flush=True)
            break

        print(f"\n===== ROUND {round_index} =====", flush=True)

        changed_before = get_changed_files(repo)
        diff_before = get_diff_stat(repo)
        check_summary = summarize_checks(previous_checks)

        round_dir = run_dir / f"round-{round_index:04d}"
        round_dir.mkdir(parents=True, exist_ok=True)

        planner_prompt = build_planner_prompt(
            goal=args.goal,
            round_index=round_index,
            changed_files=changed_before,
            diff_stat=diff_before,
            previous_exec_summary=previous_exec_message,
            check_summary=check_summary,
        )

        planner_message_file = round_dir / "planner_last_message.txt"
        planner_result = run_codex_exec(
            repo=repo,
            codex_bin=args.codex_bin,
            prompt=planner_prompt,
            output_file=planner_message_file,
            timeout_sec=args.planner_timeout,
            model=args.model,
            profile=args.profile,
            full_auto=False,
            sandbox="read-only",
            dangerous=args.dangerous,
        )

        if planner_result.returncode != 0 and is_concurrency_blocked(planner_result):
            print("[busy] planner blocked by concurrency limit, retry later", flush=True)
            write_json(
                status_file,
                {
                    "round": round_index,
                    "state": "busy_planner",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "retry_in": args.retry_on_busy,
                },
            )
            time.sleep(args.retry_on_busy)
            round_index -= 1
            continue

        planner_raw = planner_message_file.read_text(encoding="utf-8", errors="ignore") if planner_message_file.exists() else ""
        plan = parse_planner_output(planner_raw)
        chosen = choose_candidate(plan)

        print("[planner-question]", plan.question, flush=True)
        print("[planner-auto-answer]", args.auto_answer, flush=True)
        print("[planner-chosen] {0} | {1}".format(chosen.get("id"), chosen.get("title")), flush=True)

        executor_prompt = build_executor_prompt(
            goal=args.goal,
            round_index=round_index,
            plan=plan,
            chosen=chosen,
            auto_answer=args.auto_answer,
            checks=args.check,
        )

        executor_message_file = round_dir / "executor_last_message.txt"
        executor_result = run_codex_exec(
            repo=repo,
            codex_bin=args.codex_bin,
            prompt=executor_prompt,
            output_file=executor_message_file,
            timeout_sec=args.executor_timeout,
            model=args.model,
            profile=args.profile,
            full_auto=not args.no_full_auto,
            sandbox=None,
            dangerous=args.dangerous,
        )

        if executor_result.returncode != 0 and is_concurrency_blocked(executor_result):
            print("[busy] executor blocked by concurrency limit, retry later", flush=True)
            write_json(
                status_file,
                {
                    "round": round_index,
                    "state": "busy_executor",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "retry_in": args.retry_on_busy,
                },
            )
            time.sleep(args.retry_on_busy)
            round_index -= 1
            continue

        previous_exec_message = executor_message_file.read_text(encoding="utf-8", errors="ignore") if executor_message_file.exists() else ""

        check_results: List[ShellResult] = []
        for cmd in args.check:
            print("[check]", cmd, flush=True)
            check_result = run_shell(cmd, repo)
            check_results.append(check_result)
            status = "PASS" if check_result.returncode == 0 else "FAIL"
            print(f"[check] {status} ({check_result.duration_sec:.1f}s)", flush=True)

        previous_checks = check_results

        changed_after = get_changed_files(repo)
        diff_after = get_diff_stat(repo)

        report = {
            "round": round_index,
            "planner": {
                "command": planner_result.command,
                "returncode": planner_result.returncode,
                "duration_sec": planner_result.duration_sec,
                "stdout": planner_result.stdout,
                "stderr": planner_result.stderr,
                "question": plan.question,
                "candidates": plan.candidates,
                "chosen": chosen,
            },
            "executor": {
                "command": executor_result.command,
                "returncode": executor_result.returncode,
                "duration_sec": executor_result.duration_sec,
                "stdout": executor_result.stdout,
                "stderr": executor_result.stderr,
                "summary": previous_exec_message,
            },
            "checks": [
                {
                    "command": item.command,
                    "returncode": item.returncode,
                    "duration_sec": item.duration_sec,
                    "stdout": item.stdout,
                    "stderr": item.stderr,
                }
                for item in check_results
            ],
            "changed_files_before": changed_before,
            "changed_files_after": changed_after,
            "diff_stat_before": diff_before,
            "diff_stat_after": diff_after,
        }

        write_json(round_dir / "report.json", report)

        write_json(
            status_file,
            {
                "round": round_index,
                "state": "ok",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "planner_question": plan.question,
                "chosen": chosen,
                "diff_stat_after": diff_after,
                "check_status": [{"command": item.command, "returncode": item.returncode} for item in check_results],
            },
        )

        print("[info] changed files after round:", len(changed_after), flush=True)
        if diff_after:
            print(diff_after, flush=True)

        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    print("\n[finish] loop ended, reports:", run_dir, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
