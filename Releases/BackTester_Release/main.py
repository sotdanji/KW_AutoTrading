import sys
import os
from PyQt6.QtWidgets import QApplication, QMessageBox

# Version info
__version__ = "1.0.0"
__app_name__ = "Sotdanji Backtesting Lab"

from ui.main_window import MainWindow

def main():
    # Setup Logging
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    import logging
    from logging.handlers import TimedRotatingFileHandler
    
    log_file = os.path.join(log_dir, "backtester.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7, encoding='utf-8')
        ]
    )
    
    logging.info("==========================================")
    logging.info(f"BackTester Started - Version {__version__}")
    logging.info("==========================================")

    try:
        app = QApplication(sys.argv)
        app.setApplicationName(__app_name__)
        app.setApplicationVersion(__version__)
        
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Critical Error: {e}", exc_info=True)
        # Show error dialog if UI fails to start
        error_app = QApplication(sys.argv) if not QApplication.instance() else QApplication.instance()
        QMessageBox.critical(
            None,
            "프로그램 시작 오류",
            f"프로그램을 시작할 수 없습니다:\n\n{str(e)}\n\n"
            f"settings.json 파일이 올바른지 확인하고,\n"
            f"필요한 패키지가 모두 설치되었는지 확인하세요.\n\n"
            f"자세한 내용은 README.md를 참고하세요."
        )
        sys.exit(1)

if __name__ == "__main__":
    main()

