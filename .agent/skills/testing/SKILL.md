---
name: testing
description: 자동매매 엔진 및 전략 무결성 검증 표준
---

# 🧪 System Testing Skill

## 1. Testing Framework
- **Primary Tool**: `pytest`
- **Location**: 모든 테스트 코드는 프로젝트 루트의 `tests/` 폴더 내에 위치함.

## 2. Test Coverage
- **Unit Tests**: 신호 생성 로직, 지표 계산 함수, 데이터 파싱 모듈에 대한 단위 테스트 필수.
- **Integration Tests**: API 모듈과 DB 연동 로직 간의 통합 테스트 수행.
- **Mocking**: 실제 API 호출 없이 로직을 검증할 수 있도록 Mock 객체 적극 활용.

## 3. Deployment & Validation
- 코드 변경 후 반드시 기존 테스트 세트(`run_all.bat` 또는 `pytest`)를 통과해야 함.
- 치명적인 로직 수정 시에는 백업(`/Backups`) 생성 후 작업을 진행함.
