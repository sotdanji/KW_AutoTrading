---
name: kiwoom-api
description: 키움증권 REST API 사용 및 통신 최적화 지침
---

# 💹 Kiwoom REST API Skill

## 1. API Selection
- **Target**: Kiwoom REST API (Open API+ 사용 안 함)
- **Primary Reference**: [키움 REST API 공식 가이드](https://openapi.kiwoom.com/guide/apiguide?dummyVal=0)를 무조건 최우선으로 참조함.
- **Local Reference**: `참고문서/` 폴더는 공식 가이드 확인 후에만 보조적으로 활용함.

## 2. Technical Implementation
- **Async Processing**: 모든 API 호출은 `asyncio`를 통한 비동기 처리를 기본으로 함.
- **Error Handling**: 
  - 네트워크 단절 및 타임아웃 대응 로직 필수.
  - Rate Limit (HTTP 429) 발생 시 지수 백오프(Exponential Backoff) 기반 재시도 적용.
- **Data Flow**: API 응답 데이터는 명확한 타입 힌트와 함께 처리하여 데이터 무결성을 보장함.

## 3. Critical Warnings
- 실전 매매 키와 모의 투자 키의 혼용 방지.
- 계좌 정보 및 개인 인증 정보(App Key, App Secret)가 코드에 노출되지 않도록 주의함 (`config.py` 활용).
