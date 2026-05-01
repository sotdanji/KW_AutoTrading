---
name: pyqt6-ui
description: PyQt6 기반 다크 모드 GUI 개발 표준
---

# 🎨 PyQt6 UI Development Skill

## 1. Framework & Theme
- **Framework**: PyQt6
- **Theme**: 차분하고 가독성이 뛰어난 **다크 테마(Dark Theme)** 일관성 유지.
- **Components**: `shared/ui/styles.py`에 정의된 공용 스타일과 Mixin을 최우선으로 사용.

## 2. Interaction & UX
- **Non-blocking**: 모든 무거운 작업(API 호출, 데이터 분석)은 반드시 별도 스레드(QThread 또는 Task)에서 처리하여 UI 프리징을 방지함.
- **Feedback**: 
  - 로딩 중에는 `QProgressBar`나 인디케이터를 통해 진행 상태를 표시.
  - 치명적 오류는 `QMessageBox`를 통해 사용자에게 즉각 알림.
- **Validation**: 매매 주문 등 중요 입력값은 전송 전 반드시 유효성 검사를 수행함.

## 3. Layout Standards
- 다양한 해상도에서 깨지지 않는 레이아웃 엔진(`QVBoxLayout`, `QHBoxLayout`) 사용.
- 고해상도(HiDPI) 지원 설정 포함.
