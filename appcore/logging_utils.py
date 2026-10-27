"""统一日志记录（文件 + 控制台）。

沿用原项目的 Logger.info / success / warning / error / debug 接口，
输出格式与写入位置保持不变（app.log / error.log）。
"""

import datetime
import threading
import traceback

from .config import APP_LOG_FILE, ERROR_LOG_FILE


class Logger:
    """统一日志记录器"""

    LEVEL_INFO = "INFO"
    LEVEL_SUCCESS = "SUCCESS"
    LEVEL_WARNING = "WARNING"
    LEVEL_ERROR = "ERROR"
    LEVEL_DEBUG = "DEBUG"

    _lock = threading.Lock()

    @staticmethod
    def _format(level, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        return f"{timestamp} [{level}] {message}"

    @staticmethod
    def _write(level, message):
        formatted = Logger._format(level, message)
        try:
            print(formatted)
        except Exception:
            # 控制台编码不支持部分字符时不影响日志文件写入
            pass

        with Logger._lock:
            try:
                with open(APP_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass

        return formatted

    @staticmethod
    def info(message):
        return Logger._write(Logger.LEVEL_INFO, message)

    @staticmethod
    def success(message):
        return Logger._write(Logger.LEVEL_SUCCESS, message)

    @staticmethod
    def warning(message):
        return Logger._write(Logger.LEVEL_WARNING, message)

    @staticmethod
    def error(message):
        return Logger._write(Logger.LEVEL_ERROR, message)

    @staticmethod
    def debug(message):
        return Logger._write(Logger.LEVEL_DEBUG, message)


def log_exception(e, context=""):
    """记录异常到 error.log"""
    error_msg = f"[{datetime.datetime.now()}] {context}: {str(e)}\n"
    error_msg += traceback.format_exc()
    try:
        print(error_msg)
    except Exception:
        pass
    try:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(error_msg + "\n")
    except Exception:
        pass
