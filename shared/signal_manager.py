import json
import os
import time
from datetime import datetime
from .config import get_data_path

class MarketSignalManager:
    """
    프로그램 간 '시장 신호(Regime)'를 공유하기 위한 매니저.
    - Analyzer_Sig: 시장의 온도(Green/Yellow/Red)를 기록
    - AT_Sig: 기록된 신호를 읽어 매매 강도 조절
    - 독립 배포 시에도 파일 부재를 체크하여 안전하게 동작 (Loose Coupling)
    """
    def __init__(self):
        self.signal_path = get_data_path("market_signal.json")
        self.default_signal = {
            "regime": "NEUTRAL",      # BULL(강세), BEAR(약세), NEUTRAL(횡보)
            "score": 50,              # 0 ~ 100 점수
            "last_updated": "",
            "message": "시스템 초기 상태",
            "source": "None"
        }

    def save_signal(self, regime, score, message, source="Analyzer_Sig"):
        """시장 신호를 파일에 저장 (Analyzer_Sig 전용)"""
        data = {
            "regime": regime,
            "score": score,
            "message": message,
            "source": source,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            # 원자적 저장을 위해 임시 파일 사용 후 교체 권장되나, 여기선 단순화
            with open(self.signal_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"[MarketSignalManager] Save Error: {e}")
            return False

    def load_signal(self):
        """저장된 신호를 로드 (AT_Sig 및 타 프로젝트 공용)"""
        if not os.path.exists(self.signal_path):
            return self.default_signal

        try:
            # 파일이 수정 중이거나 잠겨있을 때를 대비한 안전장치
            if not os.path.exists(self.signal_path):
                return self.default_signal
                
            with open(self.signal_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return self.default_signal
                data = json.loads(content)
                
            # 유효성 체크
            last_updated = data.get("last_updated", "")
            if last_updated:
                try:
                    updated_time = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
                    # 30분 이상 경과 시 시장 종료로 간주하고 기본값 반환
                    if (datetime.now() - updated_time).total_seconds() > 1800:
                        return self.default_signal
                except ValueError:
                    return self.default_signal
                    
            return data
        except (json.JSONDecodeError, PermissionError, OSError) as e:
            # 파일 접근 중 충돌이나 파싱 오류 발생 시 시스템 중단 방지
            return self.default_signal

    def get_trading_multiplier(self):
        """
        신호에 따른 매매 비중 가중치 반환 (AT_Sig 활용용)
        - BULL: 1.2 (적극)
        - NEUTRAL: 1.0 (일반)
        - BEAR: 0.5 (보수/축소)
        """
        signal = self.load_signal()
        regime = signal.get("regime", "NEUTRAL")
        
        if regime == "BULL":
            return 1.2
        elif regime == "BEAR":
            return 0.5
        return 1.0
