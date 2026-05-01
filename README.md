# 🏠 Sotdanji Trading System

> **솥단지 자동매매 시스템** — 주도주 발굴부터 전략 검증, 자동매매까지

---

## 📦 프로젝트 구조

```
KW_AutoTrading/
│
├── Analyzer_Sig/      주도주 분석 + 전략 검증 통합 엔진
├── AT_Sig/            자동매매 시그널 실행 시스템
│   └── ui/            Mixin 모듈 (strategy, account, settings)
├── shared/            공유 라이브러리 (수식 파서, 지표, 전략 등)
├── tests/             통합 테스트 스위트 (pytest)
│
├── Master_Control.py  통합 관제 및 프로세서 컨트롤러 (Golden Star)
├── MASTER_START.bat   전체 시스템 통합 실행
├── pytest.ini         테스트 설정
└── .gitignore         API 키 보안 설정
```

---

## 🔗 시스템 구성 및 관계

```
      ┌──────────────────────────────────┐
      │       Master_Control.py          │
      │   (통합 관제 및 Golden Star 분석)   │
      └────────────────┬─────────────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
┌──────────────┐              ┌──────────────┐
│              │ ◄─────────── │              │
│   AT_Sig     │  분석 데이터   │ Analyzer_Sig │
│  (자동매매)   │  및 전략 전송  │ (분석/백테스트)│
└──────┬───────┘              └──────────────┘
       │ ▲
       │ │ analysis_results.json (실시간 동기화)
       └─┘
```

| 연동 | 방식 | 주기 |
|------|------|:----:|
| Analyzer → AT_Sig | `lead_watchlist.json` 및 DB 공유 | 실시간 |
| Master → 각 모듈 | QProcess 기반 프로세스 제어 | - |

---

## 🚀 실행 방법

### 통합 실행 (권장)
```powershell
# 관제 센터 실행 (모든 앱 일괄 제어 가능)
d:\AG\KW_AutoTrading\MASTER_START.bat
```

### 개별 실행
```powershell
# Analyzer_Sig (분석 및 백테스팅)
python d:\AG\KW_AutoTrading\Analyzer_Sig\Anal_Main.py

# AT_Sig (자동매매)
python d:\AG\KW_AutoTrading\AT_Sig\Trade_Main.py
```

---

## 🔑 API 키 설정 (신규 사용자 필수)

API 키는 소스코드가 아닌 **`.env` 파일**에 안전하게 저장합니다.

### ✅ 방법 1 — 자동 설정 (권장)

프로젝트 루트에서 아래 명령어를 실행하면 대화형 마법사가 키를 안내합니다:

```powershell
python setup_keys.py
```

실행 화면 예시:
```
==============================================================
  🔑  KW AutoTrading  —  API 키 설정 마법사 v2
==============================================================

[ AT_Sig 실거래 API 키 — 자동매매 엔진용  (필수) ]
  App Key    (AT 실거래): xxxxxxxxxxxxxx
  App Secret (AT 실거래): xxxxxxxxxxxxxx

[ AT_Sig 모의투자 API 키  (선택) ]
  App Key    (AT 모의) (Enter로 건너뜀): xxxxxx
  App Secret (AT 모의) (Enter로 건너뜀): xxxxxx

[ Analyzer_Sig 실거래 API 키 — 선도주 분석 엔진용  (필수) ]
  ⚠️  동시 실행 시 반드시 별도 계좌(캐치 또는 제2실투 계좌) 키 입력
  App Key    (Analyzer 실거래) — 별도 계좌: yyyyyyyyyyyyyy
  App Secret (Analyzer 실거래) — 별도 계좌: yyyyyyyyyyyyyy
  ℹ️  Analyzer 모의 키는 AT_Sig 모의 키를 자동 상속합니다.

[ 텔레그램 알림 설정  (필수) ]
  Bot Token: 1234567890:AAAAA...
  Chat ID:   987654321

  ✅  모든 키가 성공적으로 저장되었습니다!
```

---

### ✏️ 방법 2 — 수동 설정

1. 프로젝트 루트의 **`.env.example`** 파일을 복사하여 **`.env`** 로 저장
2. `.env` 파일을 텍스트 편집기로 열어 키 입력:

```env
KW_REAL_APP_KEY=여기에_실거래_APP_KEY_입력
KW_REAL_APP_SECRET=여기에_실거래_APP_SECRET_입력
```

---

### 📋 키움 REST API 키 발급 방법

1. [키움증권 홈페이지](https://www.kiwoom.com) 로그인
2. **트레이딩 → Open API → REST API 신청** 메뉴 접속
3. 실거래 계좌 보유 시 → 실거래 API / 모의투자 시 → 모의투자 API 신청
4. 발급된 **App Key**와 **App Secret**을 `.env` 파일에 저장

> ⚠️ `.env` 파일은 `.gitignore`에 등록되어 있어 Git에 올라가지 않습니다.
> 절대 타인에게 공유하거나 인터넷에 노출하지 마세요.

---

## 📁 공유 라이브러리 (shared/)

전체 시스템이 공유하는 핵심 모듈:

| 모듈 | 역할 |
|------|------|
| `formula_parser.py` | 키움 수식 → 파이썬 코드 변환 |
| `indicators.py` | 기술적 지표 계산 (RSI, MACD, BB 등) |
| `execution_context.py` | 전략 실행 컨텍스트 |
| `accumulation_manager.py` | 창구별 매집 질 분석 엔진 |
| `strategies/` | 저장된 전략 JSON 파일 |

---

## 📖 사용자 매뉴얼

각 프로젝트 폴더의 `USER_MANUAL.md`를 참고하세요:

- [Analyzer_Sig 매뉴얼](Analyzer_Sig/USER_MANUAL.md)
- [AT_Sig 매뉴얼](AT_Sig/USER_MANUAL.md)

---

## 🧪 테스트

프로젝트 루트에서 명령어 하나로 전체 시스템 건강 상태를 검증합니다:

```powershell
pytest
```

---

## 기술 스택

- **OS**: Windows 전용 (HTS 연동에 `pywin32` 사용)
- **Language**: Python 3.10+
- **GUI**: PyQt6 (Dark Theme)
- **API**: 키움증권 REST / WebSocket API
- **Data**: Pandas, NumPy, SQLite
- **Env**: python-dotenv (API 키 관리)
- **Test**: pytest

---

**Sotdanji Lab**
*Last Updated: 2026-05-01 | v41 안정화 완료 — 배포 준비 상태*
