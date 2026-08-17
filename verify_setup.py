from __future__ import annotations

import argparse
import json
import sys

from openai import OpenAI

from config import AppConfig


def verify_groq(config: AppConfig) -> bool:
    if not config.groq_api_key:
        print("[FAIL] GROQ_API_KEY가 설정되지 않았습니다.")
        return False
    try:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=config.groq_api_key,
            timeout=20,
        )
        response = client.chat.completions.create(
            model=config.groq_model,
            temperature=0,
            max_tokens=200,
            reasoning_effort="low",
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "connection_check",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"connected": {"type": "boolean"}},
                        "required": ["connected"],
                        "additionalProperties": False,
                    },
                },
            },
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": 'Return exactly {"connected": true}.'},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        if payload.get("connected") is True:
            print(f"[OK] Groq 연결 성공 · model={config.groq_model}")
            return True
        print("[FAIL] Groq가 예상한 연결 확인 JSON을 반환하지 않았습니다.")
        return False
    except Exception as exc:
        print(f"[FAIL] Groq 연결 실패 · {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="API 연결 상태 검사")
    parser.add_argument("--groq", action="store_true", help="Groq 연결을 1회 검사")
    args = parser.parse_args()
    if not args.groq:
        parser.print_help()
        return 2
    return 0 if verify_groq(AppConfig()) else 1


if __name__ == "__main__":
    sys.exit(main())
