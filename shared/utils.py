import datetime

def format_price(price: int) -> str:
    """가격을 천단위 콤마로 포맷팅"""
    return f"{price:,}"

def format_rate(rate: float) -> str:
    """등락률을 소수점 2자리 + %로 포맷팅"""
    sign = "+" if rate > 0 else ""
    return f"{sign}{rate:.2f}%"

def format_volume(volume: int) -> str:
    """거래대금/거래량을 천단위 콤마로 포맷팅"""
    return f"{volume:,}"

def get_current_time_str() -> str:
    """현재 시간을 포맷된 문자열로 반환 (예: 2026-03-04 17:35:00)"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def parse_kiwoom_date(date_str: str) -> datetime.date | None:
    """키움증권 API 날짜 문자열(YYYYMMDD)을 date 객체로 변환"""
    if not date_str or len(date_str) != 8:
        return None
    try:
        return datetime.datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        return None
