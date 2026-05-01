# -*- coding: utf-8 -*-
import sys
import os
import traceback
import logging
from PyQt6.QtWidgets import QApplication

# 경로 설정
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if script_dir not in sys.path:
	sys.path.insert(0, script_dir)
if project_root not in sys.path:
	sys.path.append(project_root)

# Analyzer 관련 모듈
from ui.main_window import AnalyzerWindow

def exception_hook(exctype, value, tb):
	"""전역 예외 처리기 (시스템 중단 방지 및 로그 기록)"""
	error_msg = "".join(traceback.format_exception(exctype, value, tb))
	logging.error(f"Uncaught exception: {error_msg}")
	
	try:
		with open("analyzer_fatal.log", "a", encoding='utf-8') as f:
			f.write(f"\n[{os.getpid()}] --- UNCAUGHT EXCEPTION ---\n")
			f.write(error_msg)
	except:
		pass

def main():
	# 로그 설정
	logging.basicConfig(
		level=logging.INFO,
		format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
		handlers=[
			logging.FileHandler("analyzer.log", encoding='utf-8')
		]
	)
	
	# 예외 처리기 등록
	sys.excepthook = exception_hook

	try:
		app = QApplication(sys.argv)
		app.setApplicationName("Sotdanji Analyzer")
		
		# 메인 윈도우 생성 및 표시
		window = AnalyzerWindow()
		window.show()
		
		# [관제 센터 신호] 초기화 성공 알림 (내부 리다이렉션 우회)
		sys.__stdout__.write("[CENTER] INITIALIZED\n")
		sys.__stdout__.flush()
		
		logging.info("Analyzer_Sig Started Successfully.")
		sys.exit(app.exec())
		
	except Exception as e:
		error_msg = traceback.format_exc()
		logging.error(f"Critical Startup Error: {error_msg}")
		with open("analyzer_fatal.log", "a", encoding='utf-8') as f:
			f.write(f"\n--- CRITICAL STARTUP ERROR ---\n{error_msg}")

if __name__ == "__main__":
	main()
