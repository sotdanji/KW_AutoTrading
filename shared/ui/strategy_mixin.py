"""
Strategy Management Mixin
- 전략 수식 편집기 UI 구성
- 수식 변환, 저장, 불러오기, 삭제, 검증
"""
import os
import logging
import json
import re
import shutil
from datetime import datetime

from PyQt6.QtWidgets import (
	QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
	QGroupBox, QLineEdit, QSplitter, QDialog, QListWidget,
	QDialogButtonBox, QMessageBox, QFileDialog, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class StrategyMixin:
	"""전략 수식 편집기 및 관리 기능을 제공하는 Mixin"""

	def append_log(self, msg):
		"""로깅 지원 (MainWindow의 log 메서드와 호환성 유지)"""
		if hasattr(self, 'log'):
			self.log(msg)
		else:
			print(msg)

	def setup_strategy_tab(self):
		"""Setup Strategy Tab (Integrated Analysis Logic)"""
		from PyQt6.QtWidgets import QScrollArea, QFrame, QWidget
		
		# Root layout for the tab
		root_layout = QVBoxLayout(self.tab_strategy)
		root_layout.setContentsMargins(0, 0, 0, 0)
		
		# Create Scroll Area
		scroll = QScrollArea()
		scroll.setWidgetResizable(True)
		scroll.setFrameShape(QFrame.Shape.NoFrame)
		scroll.setStyleSheet("background-color: transparent;")
		
		# Content widget for scroll area
		scroll_content = QWidget()
		scroll_content.setObjectName("strategy_scroll_content")
		layout = QVBoxLayout(scroll_content)
		layout.setContentsMargins(20, 20, 20, 20)
		layout.setSpacing(15)
		
		scroll.setWidget(scroll_content)
		root_layout.addWidget(scroll)
		
		# === Title Section ===
		title_layout = QHBoxLayout()
		title = QLabel("전략 수립 및 코드 검증")
		title.setObjectName("strategy_title")
		title.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
		title_layout.addWidget(title)
		title_layout.addStretch()
		
		# [UI Style] Button Style (Unified)
		btn_style = """
			QPushButton {
				background-color: #4a4a4a; 
				color: #ffffff; 
				border: 1px solid #666666; 
				border-radius: 5px; 
				font-weight: bold; 
				font-size: 13px;
				padding: 8px;
			}
			QPushButton:hover {
				background-color: #5a5a5a;
				border: 1px solid #999999;
			}
			QPushButton:pressed {
				background-color: #333333;
			}
		"""

		# Help button
		btn_help = QPushButton("❓ 도움말")
		btn_help.setMaximumWidth(100)
		btn_help.clicked.connect(self.show_formula_help)
		btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
		btn_help.setStyleSheet(btn_style)
		title_layout.addWidget(btn_help)
		
		layout.addLayout(title_layout)
		
		splitter = QSplitter(Qt.Orientation.Vertical)
		# Set minimum height for splitter to prevent squashing
		splitter.setMinimumHeight(600)
		
		# --- Top: Formula Input ---
		input_group = QGroupBox("📝 키움 수식 입력")
		input_layout = QVBoxLayout()
		input_layout.setContentsMargins(15, 20, 15, 15)
		input_layout.setSpacing(10)
		
		# Name
		name_layout = QHBoxLayout()
		name_label = QLabel("전략 이름:")
		name_label.setMinimumWidth(80)
		name_layout.addWidget(name_label)
		
		self.input_strategy_name = QLineEdit()
		self.input_strategy_name.setPlaceholderText("예: 골든 크로스")
		self.input_strategy_name.setMaximumHeight(35)
		name_layout.addWidget(self.input_strategy_name)
		input_layout.addLayout(name_layout)
		
		# Text Area
		self.text_formula_input = QTextEdit()
		self.text_formula_input.setPlaceholderText(
			"키움 수식을 입력하세요.\n\n"
			"예시:\n"
			"BBU = BBandsUp(20, 2);\n"
			"CCU = eavg(C, 20) + ATR(20) * 2;\n"
			"CrossUp(C, BBU)"
		)
		self.text_formula_input.setFont(QFont("Consolas", 10))
		self.text_formula_input.setMinimumHeight(150)
		input_layout.addWidget(self.text_formula_input)
		
		# Buttons
		btn_layout = QHBoxLayout()
		
		self.btn_convert = QPushButton("🔄 파이썬 코드로 변환")
		self.btn_convert.clicked.connect(self.on_convert_formula)
		self.btn_convert.setMinimumHeight(40)
		self.btn_convert.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_convert.setStyleSheet(btn_style)
		btn_layout.addWidget(self.btn_convert)
		
		btn_clear = QPushButton("🗑️ 리셋")
		btn_clear.setMaximumWidth(100)
		btn_clear.setMinimumHeight(40)
		btn_clear.clicked.connect(self.reset_strategy_input)
		btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
		btn_clear.setStyleSheet(btn_style)
		btn_layout.addWidget(btn_clear)
		
		btn_save = QPushButton("💾 저장")
		btn_save.setMaximumWidth(100)
		btn_save.setMinimumHeight(40)
		btn_save.clicked.connect(self.save_strategy)
		btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
		btn_save.setStyleSheet(btn_style)
		btn_layout.addWidget(btn_save)
		
		btn_load = QPushButton("📂 불러오기")
		btn_load.setMaximumWidth(120)
		btn_load.setMinimumHeight(40)
		btn_load.clicked.connect(self.load_strategy_popup)
		btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
		btn_load.setStyleSheet(btn_style)
		btn_layout.addWidget(btn_load)
		
		btn_delete = QPushButton("🗑 삭제")
		btn_delete.setMaximumWidth(100)
		btn_delete.setMinimumHeight(40)
		btn_delete.clicked.connect(self.delete_strategy_popup)
		btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
		btn_delete.setStyleSheet("background-color: #d32f2f; color: white;")
		btn_layout.addWidget(btn_delete)
		
		input_layout.addLayout(btn_layout)
		input_group.setLayout(input_layout)
		splitter.addWidget(input_group)
		
		# --- Bottom: Python Code ---
		output_group = QGroupBox("🐍 변환된 파이썬 코드 (검증 및 실매매 적용)")
		output_layout = QVBoxLayout()
		output_layout.setContentsMargins(15, 20, 15, 15)
		output_layout.setSpacing(10)
		
		self.text_formula_preview = QTextEdit()
		self.text_formula_preview.setPlaceholderText(
			"변환된 파이썬 코드가 여기에 표시됩니다.\n"
			"변환 후 코드를 수동으로 편집하여 검증할 수 있습니다."
		)
		self.text_formula_preview.setFont(QFont("Consolas", 10))
		self.text_formula_preview.setMinimumHeight(200)
		output_layout.addWidget(self.text_formula_preview)
		output_group.setLayout(output_layout)
		splitter.addWidget(output_group)
		
		splitter.setSizes([300, 300]) # 50:50 ratio
		layout.addWidget(splitter)
		
		# Validation Section (Now part of the scrollable content)
		validation_bar = QHBoxLayout()
		self.btn_validate = QPushButton("✅ 코드 검증 (샘플 데이터)")
		self.btn_validate.setMinimumHeight(50)
		self.btn_validate.clicked.connect(self.validate_converted_code)
		self.btn_validate.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_validate.setStyleSheet(btn_style + "QPushButton { font-size: 15px; background-color: #2e7d32; }") 
		validation_bar.addWidget(self.btn_validate)
		layout.addLayout(validation_bar)
		
		# Description
		desc = QLabel("※ 'cond' 변수가 True일 때 매수합니다. 검증 버튼을 눌러 문법 오류를 잡으세요.")
		desc.setStyleSheet("color: #888; font-size: 11px;")
		desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
		layout.addWidget(desc)
		
		# Info Label
		info_label = QLabel(
			"💡 <b>팁</b>: 작성하신 전략은 설정 탭의 [전략 선택] 항목에서 지정해야 실제 매매에 적용됩니다."
		)
		info_label.setStyleSheet("color: #a0a0a0; padding: 10px; background-color: #2a2a2a; border-radius: 5px;")
		layout.addWidget(info_label)

	# --- Strategy Feature Methods ---
	def on_convert_formula(self):
		"""수식을 파이썬 코드로 변환하는 슬롯"""
		# 중복 클릭 방지
		if hasattr(self, 'btn_convert'):
			self.btn_convert.setEnabled(False)
			QApplication.processEvents()

		formula = self.text_formula_input.toPlainText().strip()
		if not formula:
			QMessageBox.warning(self, "오류", "수식을 입력하세요.")
			if hasattr(self, 'btn_convert'): self.btn_convert.setEnabled(True)
			return

		try:
			# Lazy import with standardized shared path
			try:
				from shared.formula_parser import FormulaParser
				from shared.hangul_converter import HangulVariableConverter
			except ImportError:
				# Fallback for different project structures
				from core.formula_parser import FormulaParser
				from core.hangul_converter import HangulVariableConverter

			self.append_log("수식 변환 중...")
			
			h_converter = HangulVariableConverter()
			# Convert Korean variables to safe placeholders
			safe_formula = h_converter.convert(formula)
			
			parser = FormulaParser()
			py_code = parser.parse(safe_formula)
			
			# Update UI
			self.text_formula_preview.setPlainText(py_code)
			self.append_log("✅ 수식 변환 성공")
			self.text_formula_preview.setStyleSheet("border: 2px solid #00cc66;") # Success Green
			
		except Exception as e:
			import traceback
			err_details = traceback.format_exc()
			self.append_log(f"❌ 변환 오류: {e}")
			logging.error(f"Formula Conversion Error:\n{err_details}")
			self.text_formula_preview.setStyleSheet("border: 2px solid #cc3333;") # Error Red
			QMessageBox.critical(self, "변환 실패", f"수식 변환 중 오류가 발생했습니다.\n\n{e}")
		finally:
			if hasattr(self, 'btn_convert'): 
				self.btn_convert.setEnabled(True)

	def get_strategies_dir(self):
		# __file__ is in ui/ subfolder, go up two levels to KW_AutoTrading root
		project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
		s_dir = os.path.join(project_root, "shared", "strategies")
		if not os.path.exists(s_dir):
			os.makedirs(s_dir)
		return s_dir

	def save_strategy(self):
		name = self.input_strategy_name.text().strip()
		formula = self.text_formula_input.toPlainText()
		code = self.text_formula_preview.toPlainText()
		
		if not name or not formula:
			QMessageBox.warning(self, "경고", "전략 이름과 수식을 입력하세요.")
			return
			
		# Clean any legacy prefix if the user happens to have them
		if name.startswith("00_기본전략_"):
			name = name.replace("00_기본전략_", "", 1)
			
		# [안실장 픽스] 사용자가 확장자를 안 붙였을 경우 강제로 .json을 붙임
		if not name.endswith('.json'):
			name += '.json'
			
		save_name = name
		s_dir = self.get_strategies_dir()
				
		safe_name = re.sub(r'[<>:"/\\|?*]', '_', save_name)
		if not safe_name.endswith('.json'):
			safe_name += '.json'
		filepath = os.path.join(s_dir, safe_name)
		
		data = {
			'name': save_name,
			'formula': formula,
			'python_code': code,
			'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		}
		
		try:
			with open(filepath, 'w', encoding='utf-8') as f:
				json.dump(data, f, indent=4, ensure_ascii=False)
			self.append_log(f"전략 저장 완료: {save_name}")
			QMessageBox.information(self, "저장 성공", f"전략 '{name}'이(가) 저장되었습니다.")
			
			# 이름을 저장된 이름으로 업데이트하여 UI 반영
			self.input_strategy_name.setText(save_name)
			
			# [안실장 픽스] 설정 탭의 전략 선택 리스트 즉시 갱신
			if hasattr(self, 'load_strategy_list'):
				self.load_strategy_list()
		except Exception as e:
			QMessageBox.critical(self, "저장 실패", str(e))

	def load_strategy_popup(self):
		s_dir = self.get_strategies_dir()
		if not os.path.exists(s_dir):
			QMessageBox.information(self, "알림", "저장된 전략이 없습니다.")
			return

		files = [f for f in os.listdir(s_dir) if f.endswith('.json')]
		files.sort() # [NEW] 일반적인 가나다순/숫자순 정렬 (00_ 폴더명 최상단 위치)
		
		if not files:
			QMessageBox.information(self, "알림", "저장된 전략이 없습니다.")
			return

		dialog = QDialog(self)
		dialog.setWindowTitle("전략 불러오기")
		dialog.setMinimumWidth(300)
		layout = QVBoxLayout(dialog)
		
		layout.addWidget(QLabel("전략을 선택하세요:"))
		list_widget = QListWidget()
		list_widget.addItems(files)
		list_widget.itemDoubleClicked.connect(dialog.accept)
		layout.addWidget(list_widget)
		
		btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
		btns.accepted.connect(dialog.accept)
		btns.rejected.connect(dialog.reject)
		layout.addWidget(btns)
		
		if dialog.exec() == QDialog.DialogCode.Accepted:
			item = list_widget.currentItem()
			if item:
				self.load_strategy_file(item.text())


	def load_strategy_file(self, full_name):
		# 확장자가 포함된 전체 이름을 받아 처리합니다.
		filepath = os.path.join(self.get_strategies_dir(), full_name)
		try:
			with open(filepath, 'r', encoding='utf-8') as f:
				data = json.load(f)
			
			self.input_strategy_name.setText(data.get('name', ''))
			self.text_formula_input.setPlainText(data.get('formula', ''))
			self.text_formula_preview.setPlainText(data.get('python_code', ''))
			self.text_formula_preview.setStyleSheet("")
			self.append_log(f"전략 로드: {name}")
		except Exception as e:
			self.append_log(f"로드 실패: {e}")

	def reset_strategy_input(self):
		"""입력 필드 초기화"""
		self.input_strategy_name.clear()
		self.text_formula_input.clear()
		self.text_formula_preview.clear()
		self.text_formula_preview.setStyleSheet("")
		self.append_log("전략 입력 초기화됨")

	def delete_strategy_popup(self):
		"""삭제 팝업"""
		s_dir = self.get_strategies_dir()
		if not os.path.exists(s_dir): return
		
		files = [f for f in os.listdir(s_dir) if f.endswith('.json')]
		files.sort()
		if not files:
			QMessageBox.information(self, "알림", "삭제할 전략이 없습니다.")
			return
			
		dialog = QDialog(self)
		dialog.setWindowTitle("전략 삭제")
		dialog.setMinimumWidth(300)
		layout = QVBoxLayout(dialog)
		
		layout.addWidget(QLabel("삭제할 전략을 선택하세요 (복구 불가):"))
		list_widget = QListWidget()
		list_widget.addItems(files)
		layout.addWidget(list_widget)
		
		btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
		btns.button(QDialogButtonBox.StandardButton.Ok).setText("삭제")
		btns.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet("color: red;")
		btns.accepted.connect(dialog.accept)
		btns.rejected.connect(dialog.reject)
		layout.addWidget(btns)
		
		if dialog.exec() == QDialog.DialogCode.Accepted:
			item = list_widget.currentItem()
			if item:
				full_name = item.text()
				filepath = os.path.join(s_dir, full_name)
				try:
					os.remove(filepath)
					self.append_log(f"전략 삭제: {name}")
					QMessageBox.information(self, "삭제 완료", f"{name} 삭제됨")
					if self.input_strategy_name.text() == name:
						self.reset_strategy_input()
				except Exception as e:
					QMessageBox.critical(self, "오류", str(e))

	def validate_converted_code(self):
		"""파이썬 코드 검증 슬롯"""
		py_code = self.text_formula_preview.toPlainText().strip()
		if not py_code:
			QMessageBox.warning(self, "오류", "검증할 코드가 없습니다. 먼저 변환 버튼을 누르세요.")
			return

		self.append_log("🔍 코드 검증 시작 (샘플 데이터 생성 중)...")
		
		try:
			import pandas as pd
			import numpy as np
			
			# Setup Execution Context
			try:
				from shared.execution_context import get_execution_context
			except ImportError:
				from core.execution_context import get_execution_context
			
			# 1. Generate realistic sample data
			from shared.formula_validator import FormulaValidator
			df = FormulaValidator()._create_sample_data(periods=120)

			
			# 2. Setup environment
			exec_globals = get_execution_context(df)
			local_vars = {}
			
			# 3. Execute validation
			# IMPORTANT: We use local_vars for result extraction
			exec(py_code, exec_globals, local_vars)
			
			# 4. Result check
			if 'cond' in local_vars:
				cond = local_vars['cond']
				
				# Verify type
				if not isinstance(cond, (pd.Series, np.ndarray, list)):
					raise TypeError(f"'cond' 변수가 예상된 타입(Series)이 아닙니다: {type(cond)}")
				
				# Count signals
				if hasattr(cond, 'sum'):
					count = int(cond.sum())
				else:
					count = list(cond).count(True)
				
				msg = f"✅ 검증 성공! (샘플 데이터 {count}회 포착)"
				self.append_log(msg)
				
				self.text_formula_preview.setStyleSheet("border: 2px solid #00cc66;") # Success
				QMessageBox.information(self, "검증 완료", 
					f"작성하신 수식이 정상적으로 수행되었습니다.\n\n"
					f"[결과]\n"
					f"데이터 기간: {len(df)}일\n"
					f"신호 발생 횟수: {count}회\n\n"
					f"※ 'cond' 변수가 정상적으로 생성되었습니다.")
			else:
				# Check if it was defined in globals (sometimes exec behavior varies)
				if 'cond' in exec_globals:
					self.append_log("⚠️ 주의: 'cond' 변수가 전역 영역(globals)에 생성되었습니다.")
					# Treat as success but log warning
					pass
				else:
					raise NameError("파이썬 코드 실행 후 'cond' 변수가 생성되지 않았습니다.\n마지막 줄에 조건식을 입력했는지 확인하세요.")
				
		except Exception as e:
			import traceback
			err_details = traceback.format_exc()
			self.append_log(f"❌ 검증 실패: {e}")
			# Log the converted code to help debugging
			logging.error(f"Code Validation Error:\n{err_details}\nConverted Code:\n{py_code}")
			
			self.text_formula_preview.setStyleSheet("border: 2px solid #cc3333;") # Error
			QMessageBox.critical(self, "검증 실패", f"코드 실행 중 오류가 발생했습니다:\n\n{str(e)}\n\n(상세 내용은 로그를 확인하세요)")

	def show_formula_help(self):
		msg = """
		<h3 style='color:#00cc66;'>💡 전략 선택 도움말</h3>
		<b>[조건검색식 + 전략추가] 매매 모드일 경우:</b><br><br>
		1. <b>전략 생성</b><br>
		이 화면에서 수식을 작성하고 파이썬 코드로 변환한 뒤 저장을 누릅니다.<br><br>
		2. <b>전략 적용</b><br>
		설정 탭의 <b>[전략 선택]</b> 란에서 방금 저장한 전략을 선택하면 매매 엔진이 해당 조건을 필터로 적용합니다.<br>
		<hr>
		<h3>📊 수식 도움말</h3>
		<b>기본 변수:</b> O, H, L, C, V<br>
		<b>함수:</b><br>
		- ma(C, 20): 단순이동평균<br>
		- ema(C, 20): 지수이동평균<br>
		- macd(C, 12, 26)<br>
		- rsi(C, 14)<br>
		- CrossUp(A, B), CrossDown(A, B)<br>
		<br>
		<b>예제 (크로스업 돌파):</b><br>
		A = ma(C, 20);<br>
		cond = CrossUp(C, A);
		"""
		QMessageBox.information(self, "도움말", msg)
