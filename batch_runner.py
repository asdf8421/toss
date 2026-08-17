from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date

from config import AppConfig
from pipeline import FundManagerPipeline


def main() -> int:
    parser = argparse.ArgumentParser(
        description="유동성 적격 KRX 전체를 캐시·재개 가능한 방식으로 분석합니다."
    )
    parser.add_argument("--strategy", choices=["balanced", "rebound", "breakout"], default="balanced")
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--require-groq", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--deep-limit", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()

    config = replace(AppConfig(), max_workers=max(1, args.workers))
    if args.require_groq and not config.groq_api_key:
        print("[FAIL] Groq 연결이 필요합니다. 먼저 powershell -ExecutionPolicy Bypass -File .\\setup_groq.ps1")
        return 2

    as_of = date.fromisoformat(args.as_of)
    if as_of != date.today():
        print("[FAIL] 현재 공급원은 과거 시점 시장·재무 스냅샷을 보장하지 않으므로 오늘 날짜만 허용합니다.")
        return 2
    pipeline = FundManagerPipeline(config)
    scope = "full" if args.limit <= 0 else f"sample{args.limit}"
    job_id = f"{scope}-{as_of:%Y%m%d}-{args.strategy}"
    pipeline.storage.start_batch_job(job_id, as_of.isoformat(), args.strategy)
    last_reported: dict[str, int] = {}

    def progress(stage: str, current: int, total: int, message: str) -> None:
        pipeline.storage.update_batch_job(
            job_id,
            status="running",
            stage=stage,
            current=current,
            total=total,
            message=message,
        )
        if current == total or current - last_reported.get(stage, -25) >= 25:
            print(f"[{stage}] {current:,}/{total:,} · {message}", flush=True)
            last_reported[stage] = current

    print(f"[START] {job_id} · 캐시된 오늘 데이터는 재사용합니다.", flush=True)
    try:
        result = pipeline.run(
            strategy=args.strategy,
            as_of=as_of,
            universe_limit=args.limit,
            deep_analysis_limit=args.deep_limit,
            max_positions=max(1, args.max_positions),
            require_ai=args.require_groq,
            progress=progress,
        )
        pipeline.storage.update_batch_job(
            job_id,
            status="complete",
            stage="complete",
            current=result["deep_analysis_count"],
            total=result["deep_analysis_count"],
            message=f"완료 · 오류 {len(result['errors'])}건",
            result_run_id=result["run_id"],
        )
        print(
            f"[OK] run_id={result['run_id']} · 전체={result['universe_count']:,} · "
            f"유동성적격={result['liquid_universe_count']:,} · "
            f"전체팩터={result['deep_analysis_count']:,} · 포지션={len(result['portfolio']['positions'])}",
            flush=True,
        )
        if result["errors"]:
            print("[WARN] 일부 오류:\n" + "\n".join(result["errors"][:20]))
        return 0
    except KeyboardInterrupt:
        pipeline.storage.update_batch_job(
            job_id,
            status="failed",
            stage="interrupted",
            current=0,
            total=0,
            message="사용자 중단 · 다음 실행에서 일일 캐시 재사용",
        )
        print("[STOP] 중단되었습니다. 같은 명령을 다시 실행하면 오늘 캐시부터 재사용합니다.")
        return 130
    except Exception as exc:
        pipeline.storage.update_batch_job(
            job_id,
            status="failed",
            stage="error",
            current=0,
            total=0,
            message=f"{type(exc).__name__}: {exc}",
        )
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
