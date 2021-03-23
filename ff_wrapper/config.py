import os
import sys
import typing
from subprocess import Popen, PIPE


class Config:
    _instance = None
    _first_run: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._first_run = True
        else:
            cls._first_run = False
        return cls._instance

    def __init__(self, app_cfg: typing.Tuple[dict, None] = None):
        if not self._first_run:
            return
        self.CONTAINER_NAME = os.getenv('CONTAINER_NAME', None)
        self.CONTAINER_ID = self._get_container_id()
        self.PID = str(os.getpid())
        self.FFMPEG_PID = ''
        self.WORKDIR = os.getenv('WORKDIR', '/tmp/ff_wrapper')
        self.PROGRESS_FIFO_PATH = os.path.join(self.WORKDIR, 'pipes/')
        self.LOGS_PATH_BASE = os.getenv('LOGS_PATH', '/var/log/ffmpeg/')
        if self.CONTAINER_NAME:
            self.LOGS_PATH = os.path.join(self.LOGS_PATH_BASE, 'ff_wrapper_' + str(self.CONTAINER_NAME))
        elif self.CONTAINER_ID:
            self.LOGS_PATH = os.path.join(self.LOGS_PATH_BASE, 'ff_wrapper_' + str(self.CONTAINER_ID[:13]))
        else:
            self.LOGS_PATH = os.path.join(self.LOGS_PATH_BASE, 'ff_wrapper_' + str(self.PID))
        self.STATUS_PATH = os.path.join(self.WORKDIR, 'status/')
        # 100к строк ~= 14 часам логов и 120мб ram
        self.PROGRESS_BUFFER_LEN = self._get_int_env('PROGRESS_BUFFER_LEN', 100000)
        self.STDOUT_BUFFER_LEN = self._get_int_env('STDOUT_BUFFER_LEN', 100000)
        self.NO_FILE_LOG = os.getenv('NO_FILE_LOG', False)
        self.LOG_ROTATION_MODE = os.getenv('LOG_ROTATION_MODE', 'days')  # days or size
        self.LOG_ROTATION_DAYS = self._get_int_env('LOG_ROTATION_DAYS', 1)
        self.LOG_ROTATION_MAX_KBYTES = self._get_int_env('LOG_ROTATION_MAX_KBYTES', 25000)  # in kbytes
        self.LOG_ROTATION_BACKUP = self._get_int_env('LOG_ROTATION_BACKUP', 3)
        self.IS_DEBUG = os.getenv('IS_DEBUG', False)
        # seconds, задержка перед стартом менеджера проверок
        self.MANAGER_START_DELAY = self._get_int_env('MANAGER_START_DELAY', 5)
        # seconds, задержка перед стартом проверки кодирования
        self.ENCODING_CHECK_START_DELAY = self._get_int_env('ENCODING_CHECK_START_DELAY', 55)
        self.ENCODING_DISABLE_CHECK = os.getenv('ENCODING_DISABLE_CHECK', False)
        # Значение, ниже которого кодирование будет считаться ошибочным
        self.ENCODING_MIN_SPEED = self._get_float_env('ENCODING_MIN_SPEED', 0.80)
        # Если базовая скорость ниже, чем минимально возможная скорость - минимально возможная скорость становится равной
        #   ENCODING_MIN_SPEED = <базовая скорость> - ENCODING_DELTA_SPEED
        self.ENCODING_DELTA_SPEED = self._get_float_env('ENCODING_DELTA_SPEED', 0.20)
        # Значение, которое вычитается из текущего fps и если результат ниже - кодирование остановится
        self.ENCODING_DELTA_FPS = self._get_int_env('ENCODING_DELTA_FPS', 10)
        # Если базовый фпс (без дельты) ниже, чем это значение - стрим считается сбойным
        self.ENCODING_MIN_BASE_FPS = self._get_float_env('ENCODING_MIN_BASE_FPS', 14)
        # Сколько секунд может продолжаться ошибка до остановки стрима менеджером
        self.ENCODING_MAX_ERROR_TIME = self._get_int_env('ENCODING_MAX_ERROR_TIME', 10)
        # Сколько секунд может не обновляться stdout
        self.ENCODING_MAX_STDOUT_STUCK_TIME = self._get_int_env('ENCODING_MAX_STDOUT_STUCK_TIME', 15)

        self.create_dirs()
        self.exit_if_already_running()
        self.save_status_to_files()

    def _get_int_env(self, env_name: str, default) -> int:
        try:
            env_var = os.getenv(env_name, default)
            return int(env_var)
        except ValueError:
            print("Error. {} env parameter must be int ({})".format(env_name, env_var))
            os._exit(1)

    def _get_float_env(self, env_name: str, default) -> float:
        try:
            env_var = os.getenv(env_name, default)
            return float(env_var)
        except ValueError:
            print("Error. {} env parameter must be float ({})".format(env_name, env_var))
            os._exit(1)

    def _get_container_id(self) -> str:
        id = ''
        with open('/proc/1/cpuset', 'r') as f:
            id = f.read()
        if id.startswith('/docker'):
            id = id.split('/')[-1]
        else:
            id = ''
        return id

    def _get_pids(self) -> list:
        pids = []
        process = Popen(['ps', '-eo', 'pid'], stdout=PIPE, stderr=PIPE)
        stdout, _ = process.communicate()
        for line in stdout.splitlines():
            line = line.decode('utf-8')
            pids.append(line.strip())
        return pids

    def exit_if_already_running(self):
        if self.PID == '1':
            return
        pid_path = os.path.join(self.STATUS_PATH, 'PID')
        if not os.path.exists:
            return
        try:
            with open(pid_path, 'r') as f:
                already_running_pid = f.read()
                pids = self._get_pids()
                if self.PID != already_running_pid and already_running_pid in pids:
                    print('WORKDIR {} is busy by process with pid {}'.format(self.WORKDIR, already_running_pid))
                    sys.exit(1)
        except OSError:
            print("PID check. Can't open file {}, creating new".format(pid_path))

    def create_dirs(self):
        if not os.path.exists(self.PROGRESS_FIFO_PATH):
            try:
                os.makedirs(self.PROGRESS_FIFO_PATH)
            except Exception as e:
                print("Error while init app. Can't create pipes dir: {}".format(self.PROGRESS_FIFO_PATH))
                raise e
        if not os.path.exists(self.STATUS_PATH):
            try:
                os.makedirs(self.STATUS_PATH)
            except Exception as e:
                print("Error while init app. Can't create status dir: {}".format(self.STATUS_PATH))
                raise e
        if not self.NO_FILE_LOG and not os.path.exists(self.LOGS_PATH):
            try:
                os.makedirs(self.LOGS_PATH)
            except Exception as e:
                print("Error while init app. Can't create log dir: {}".format(self.LOGS_PATH))
                raise e

    def save_status_to_files(self):
        for k, v in vars(self).items():
            if not k.startswith('_'):
                with open(os.path.join(self.STATUS_PATH, k), 'w') as f:
                    f.write(str(v))
