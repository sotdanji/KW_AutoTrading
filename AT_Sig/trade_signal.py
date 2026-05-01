from PyQt6.QtCore import QObject, pyqtSignal

class TradeSignal(QObject):
    """
    매수/매도 확인 요청을 UI로 보내기 위한 시그널 클래스.
    Singleton 패턴으로 어디서든 접근 가능하게 합니다.
    """
    _instance = None
    
    # 신호 정의: type(buy/sell), data(dict)
    ask_confirmation = pyqtSignal(str, dict)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
