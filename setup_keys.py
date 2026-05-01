"""
KW_AutoTrading — API 키 초기 설정 마법사 (v2)
=============================================
신규 사용자는 이 스크립트를 실행하여 모든 API 키를 한 번에 등록합니다.
키는 소스코드가 아닌 .env 파일에 안전하게 저장됩니다.

필요한 키 목록:
  [1] AT_Sig   실거래/모의 키 (자동매매 엔진용)
  [2] Analyzer 실거래 키 (선도주 분석 엔진용) ← 반드시 별도 계좌 (서버 부하 분리) | 모의 모드 미사용
  [3] 텔레그램 Bot Token + Chat ID                  ← 알림 필수

사용법:
    python setup_keys.py
"""

import os
import sys


SEPARATOR = "=" * 62


def header():
    print()
    print(SEPARATOR)
    print("  🔑  KW AutoTrading  —  API 키 설정 마법사 v2")
    print(SEPARATOR)
    print()


def section(title: str):
    print(f"\n[ {title} ]")


def prompt(label: str, hint: str = "", required: bool = True, secret: bool = False) -> str:
    """값을 입력받습니다. required=False이면 빈 값 허용(Enter로 건너뜀)."""
    while True:
        if hint:
            print(f"  💡 {hint}")
        suffix = "" if required else " (Enter로 건너뜀)"
        value = input(f"  {label}{suffix}: ").strip()
        if value:
            return value
        if not required:
            return ""
        print("  ⚠️  필수 항목입니다. 반드시 입력해 주세요.\n")



def write_env(env_path: str, data: dict):
    """딕셔너리를 .env 파일로 저장합니다."""
    groups = [
        ("# ── AT_Sig (자동매매) ─────────────────────────────", [
            "AT_REAL_APP_KEY", "AT_REAL_APP_SECRET",
            "AT_PAPER_APP_KEY", "AT_PAPER_APP_SECRET",
        ]),
        ("# ── Analyzer_Sig (선도주 분석) ────────────────────", [
            "ANAL_REAL_APP_KEY", "ANAL_REAL_APP_SECRET",
            "ANAL_PAPER_APP_KEY", "ANAL_PAPER_APP_SECRET",
        ]),
        ("# ── Telegram 알림 ─────────────────────────────────", [
            "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID",
        ]),
        ("# ── 공용 (shared/api.py) ──────────────────────────", [
            "KW_REAL_APP_KEY", "KW_REAL_APP_SECRET",
        ]),
    ]

    lines = [
        "# KW_AutoTrading API 키 설정",
        "# ⚠️  이 파일은 절대 외부에 공유하거나 Git에 커밋하지 마세요!\n",
    ]

    for comment, keys in groups:
        lines.append(comment)
        for k in keys:
            v = data.get(k, "")
            if v:
                lines.append(f"{k}={v}")
        lines.append("")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(project_root, ".env")

    header()

    # 기존 .env 덮어쓰기 확인
    if os.path.exists(env_path):
        print("⚠️  이미 .env 파일이 존재합니다.")
        if input("   덮어쓰시겠습니까? (y/N): ").strip().lower() != "y":
            print("\n설정을 취소했습니다. 기존 .env 파일을 유지합니다.")
            sys.exit(0)

    env_data = {}

    # ─────────────────────────────────────────────────────────
    # [1] AT_Sig 실거래 키  (필수)
    # ─────────────────────────────────────────────────────────
    section("AT_Sig 실거래 API 키 — 자동매매 엔진용  [필수]")
    print("  키움 Open API 포털에서 발급받은 실거래 App Key / App Secret을 입력하세요.")
    env_data["AT_REAL_APP_KEY"]    = prompt("App Key    (AT 실거래)")
    env_data["AT_REAL_APP_SECRET"] = prompt("App Secret (AT 실거래)")

    # 공용 키 (shared/config.py)도 AT 실거래 키로 기본 설정
    env_data["KW_REAL_APP_KEY"]    = env_data["AT_REAL_APP_KEY"]
    env_data["KW_REAL_APP_SECRET"] = env_data["AT_REAL_APP_SECRET"]

    # ─────────────────────────────────────────────────────────
    # [2] AT_Sig 모의투자 키  (선택)
    # ─────────────────────────────────────────────────────────
    section("AT_Sig 모의투자 API 키 — 자동매매 모의 테스트용  [선택]")
    env_data["AT_PAPER_APP_KEY"]    = prompt("App Key    (AT 모의)", required=False)
    env_data["AT_PAPER_APP_SECRET"] = prompt("App Secret (AT 모의)", required=False)

    # ─────────────────────────────────────────────────────────
    # [3] Analyzer_Sig 실거래 키  (필수 — AT_Sig와 반드시 다른 계좌)
    # ─────────────────────────────────────────────────────────
    section("Analyzer_Sig 실거래 API 키 — 선도주 분석 엔진용  [필수]")
    print("  ⚠️  주의: AT_Sig와 Analyzer_Sig를 동시에 실행할 경우,")
    print("         동일 계좌 키를 사용하면 서버 부하(429 오류)가 발생합니다.")
    print("         반드시 별도 계좌(캐치 계좌 또는 제2실투 계좌)의 키를 입력하세요.")
    env_data["ANAL_REAL_APP_KEY"]    = prompt("App Key    (Analyzer 실거래) — 별도 계좌")
    env_data["ANAL_REAL_APP_SECRET"] = prompt("App Secret (Analyzer 실거래) — 별도 계좌")

    # ─────────────────────────────────────────────────────────
    # [4] Analyzer_Sig 모의투자 키 — AT_Sig 모의 키 자동 상속
    #     Analyzer_Sig는 실거래 분석 전용이므로 모의 모드 미사용.
    #     AT_Sig 모의 키가 있으면 그대로 물려받아 .env에 기록.
    # ─────────────────────────────────────────────────────────
    env_data["ANAL_PAPER_APP_KEY"]    = env_data.get("AT_PAPER_APP_KEY", "")
    env_data["ANAL_PAPER_APP_SECRET"] = env_data.get("AT_PAPER_APP_SECRET", "")


    # ─────────────────────────────────────────────────────────
    # [5] 텔레그램  (필수)
    # ─────────────────────────────────────────────────────────
    section("텔레그램 알림 설정  [필수]")
    print("  Bot Token: BotFather에서 /newbot 명령으로 발급")
    print("  Chat ID:   @userinfobot 에 /start 전송 후 확인")
    env_data["TELEGRAM_TOKEN"]   = prompt("Bot Token")
    env_data["TELEGRAM_CHAT_ID"] = prompt("Chat ID  ")

    # .env 저장
    write_env(env_path, env_data)

    # 결과 출력
    print()
    print(SEPARATOR)
    print("  ✅  모든 키가 성공적으로 저장되었습니다!")
    print(f"     저장 위치: {env_path}")
    print()
    print("  저장된 항목:")
    for key, val in env_data.items():
        masked = val[:6] + "***" if val else "(비어있음)"
        print(f"    {key:<30} = {masked}")
    print()
    print("  다음 단계:")
    print("  1. MASTER_START.bat 실행 → 전체 시스템 가동")
    print("  2. 처음에는 PAPER(모의) 모드로 동작 확인 후 REAL 전환")
    print(SEPARATOR)
    print()


if __name__ == "__main__":
    main()
