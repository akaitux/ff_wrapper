import logging
from config import Config
import os
import datetime
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler


def get_file_logger_handler(log_path: str) -> logging.Handler:
    cfg = Config()
    if cfg.LOG_ROTATION_MODE == 'days':
        handler = TimedRotatingFileHandler(log_path,
                                           when="d",
                                           interval=cfg.LOG_ROTATION_DAYS,
                                           backupCount=cfg.LOG_ROTATION_BACKUP,
                                           )
        return handler
    elif cfg.LOG_ROTATION_MODE == 'size':
        handler = RotatingFileHandler(log_path,
                                      maxBytes=cfg.LOG_ROTATION_MAX_KBYTES * 1024,
                                      backupCount=cfg.LOG_ROTATION_BACKUP,
                                      )
        return handler
    err = 'Wrong LOG_ROTATION_MODE value ({})'.format(cfg.LOG_ROTATION_MODE)
    raise Exception(err)


class Logger(logging.Logger):

    _instance = None
    _first_run: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._first_run = True
        else:
            cls._first_run = False
        return cls._instance

    def __init__(self, *args, **kwargs):
        if not self._first_run:
            return
        super().__init__(*args, **kwargs)
        self.cfg = Config()
        self.start_time = datetime.datetime.now()
        if self.cfg.IS_DEBUG:
            self.setLevel('DEBUG')
        else:
            self.setLevel('INFO')

        std_handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S %Z")
        std_handler.setFormatter(formatter)
        self.addHandler(std_handler)

        start_time = self.start_time.strftime('%Y_%m_%d__%H_%M_%S')
        log_path = os.path.join(self.cfg.LOGS_PATH, 'manager_{}.log'.format(start_time))
        file_handler = get_file_logger_handler(log_path)
        file_handler.setFormatter(formatter)
        self.addHandler(file_handler)
