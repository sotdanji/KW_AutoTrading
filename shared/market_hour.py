import datetime

class MarketHour:
	"""장 시간 관련 상수 및 메서드를 관리하는 클래스"""
	
	# 장 시작/종료 시간 상수
	MARKET_START_HOUR = 9
	MARKET_START_MINUTE = 0
	MARKET_END_HOUR = 15
	MARKET_END_MINUTE = 30
	
	@staticmethod
	def _is_weekday():
		"""평일인지 확인합니다."""
		return datetime.datetime.now().weekday() < 5
	
	@staticmethod
	def _get_market_time(hour, minute):
		"""장 시간을 반환합니다."""
		now = datetime.datetime.now()
		return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
	
	@classmethod
	def is_market_open_time(cls):
		"""현재 시간이 장 시간인지 확인합니다."""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		market_open = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		market_close = cls._get_market_time(cls.MARKET_END_HOUR, cls.MARKET_END_MINUTE)
		# Always return true for testing (should be conditional on mock setting if possible, but classmethod makes it hard to access instance config)
		# For now, let's keep strict check but maybe the user is in mock environment and wants to trade anytime?
		# Actually, Kiwoom Mock still follows market hours usually.
		# The error "장이 열리지 않는 날" (571489) confirms it's Saturday or Sunday/Holiday.
		# If user wants to force sell on weekend in Mock, it might not be possible via API.
		return market_open <= now <= market_close
	
	@classmethod
	def is_market_start_time(cls):
		"""현재 시간이 장 시작 시간인지 확인합니다."""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		market_start = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		return now >= market_start and (now - market_start).seconds < 60  # 1분 이내
	
	@classmethod
	def is_market_end_time(cls):
		"""현재 시간이 장 종료 시간인지 확인합니다."""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		market_end = cls._get_market_time(cls.MARKET_END_HOUR, cls.MARKET_END_MINUTE)
		return now >= market_end and (now - market_end).seconds < 60  # 1분 이내

	@classmethod
	def get_market_status_text(cls):
		"""현재 시장 상태를 텍스트와 개장 여부로 반환합니다."""
		if not cls._is_weekday():
			return "주말/공휴일", False
		
		now = datetime.datetime.now()
		market_open = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		market_close = cls._get_market_time(cls.MARKET_END_HOUR, cls.MARKET_END_MINUTE)
		
		if now < market_open:
			return "장 시작 전", False
		elif now <= market_close:
			return "장 운영 중", True
		else:
			return "장 종료됨", False
