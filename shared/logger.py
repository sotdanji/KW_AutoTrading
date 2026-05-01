import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_FILE_HANDLERS = {}

def setup_logger(name, log_dir="logs", log_file="application.log", console_out=True, level=logging.DEBUG):
	"""
	공통 로거 설정 함수 - [MUST use Tabs] 원칙 적용
	"""
	logger = logging.getLogger(name)
	logger.setLevel(level)
	
	# 이미 핸들러가 있으면 중복 설정 방지
	if logger.handlers:
		return logger
		
	formatter = logging.Formatter(
		'%(asctime)s - %(name)s - %(levelname)s - %(message)s',
		datefmt='%Y-%m-%d %H:%M:%S'
	)
	
	# 로그 디렉토리 생성
	try:
		if log_dir and log_dir != ".":
			if not os.path.exists(log_dir):
				os.makedirs(log_dir, exist_ok=True)
	except Exception as e:
		print(f"Warning: Failed to create log directory: {e}")
		log_dir = "."
		
	# 파일 핸들러 (Rotating - 10MB 크기로 최대 5개 파일 유지)
	global _FILE_HANDLERS
	try:
		log_path = os.path.join(log_dir, log_file) if log_dir else log_file
		abs_path = os.path.abspath(log_path)
		
		if abs_path not in _FILE_HANDLERS:
			file_handler = RotatingFileHandler(
				log_path, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
			)
			file_handler.setFormatter(formatter)
			file_handler.setLevel(logging.DEBUG)
			_FILE_HANDLERS[abs_path] = file_handler
			
		logger.addHandler(_FILE_HANDLERS[abs_path])
	except Exception as e:
		print(f"Warning: Failed to create file handler: {e}")
		
	# [안실장 유지보수 가이드] 중앙 집중형 오류 로깅 추가
	try:
		from shared.config import get_data_path
		central_log_dir = get_data_path("logs")
		os.makedirs(central_log_dir, exist_ok=True)
		fatal_log_path = os.path.join(central_log_dir, "fatal_errors.log")
		abs_fatal_path = os.path.abspath(fatal_log_path)
		
		if abs_fatal_path not in _FILE_HANDLERS:
			fatal_handler = RotatingFileHandler(
				fatal_log_path, maxBytes=10*1024*1024, backupCount=10, encoding='utf-8'
			)
			fatal_handler.setFormatter(formatter)
			fatal_handler.setLevel(logging.ERROR)
			_FILE_HANDLERS[abs_fatal_path] = fatal_handler
			
		logger.addHandler(_FILE_HANDLERS[abs_fatal_path])
	except Exception as e:
		pass
		
	# 콘솔 핸들러
	if console_out:
		console_handler = logging.StreamHandler(sys.stdout)
		console_handler.setFormatter(formatter)
		console_handler.setLevel(logging.INFO)
		logger.addHandler(console_handler)
		
	return logger

def get_logger(name, log_dir="logs", log_file="application.log", console_out=True, level=logging.DEBUG):
	"""
	로거를 가져옵니다. 없으면 새로 생성합니다.
	"""
	logger = logging.getLogger(name)
	if not logger.handlers:
		return setup_logger(name, log_dir=log_dir, log_file=log_file, console_out=console_out, level=level)
	return logger
