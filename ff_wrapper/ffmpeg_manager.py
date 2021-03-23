import threading
import time
import os
import datetime
from ffmpeg import FFMpegProc
from config import Config
from logger import Logger
from logbuffer import progress_str_to_dict


class FFMpegManager:

    def __init__(self, ffmpeg: FFMpegProc):
        self.ffmpeg = ffmpeg
        self.cfg = Config()
        self.THREAD_TIMEOUT = 0.5  # Время задержки while true главного цикла менеджера
        self._thread = None  # Setted in self.run()
        self._finish = False
        self._logger = Logger("FFMpegManager")
        self._enc_last_error = False
        self._enc_last_check_time = None  # Setted in _check_encoding_state
        self._enc_check_started = False  # Setted in _check_encoding_state
        # FPS, который берется у стрима при старте проверки статуса кодирования и с которым идет сравнениe
        self._enc_base_fps = None
        self._enc_min_fps = None  # FPS, ниже которого стрим считается сбойным
        self._enc_min_speed = None  # Устанавливается в is_speed_valid
        # Устанавливается в момент возникновения первой ошибки и становится None при ее отсутствии
        self._enc_error_start_time = None
        self._stdout_stuck_last = None  # Устанавливается в _check_stdout_stuck
        self._stdout_stuck_start = None  # Устанавливается в _check_stdout_stuck

    def shutdown_all(self):
        self.ffmpeg.stop()
        self.stop()

    def run(self):
        t = threading.Thread(target=self._run, daemon=True)
        self._thread = t
        t.start()

    def _run(self):
        first_run = True
        while True:
            if first_run:
                time.sleep(self.cfg.MANAGER_START_DELAY)
                first_run = False
                self._logger.info("Manager thread started (with delay {}s)".format(self.cfg.MANAGER_START_DELAY))
                self._logger.info("Encoding checker will be started in {}s ...".format(self.cfg.ENCODING_CHECK_START_DELAY))
            if self._finish is True:
                self._logger.info('Manager thread stopped')
                break
            self._check_running_state()
            self._check_encoding_state()
            time.sleep(self.THREAD_TIMEOUT)

    def _check_running_state(self):
        if not self.ffmpeg.process or self.ffmpeg.process and self.ffmpeg.process.poll() == 0:
            self._logger.info('FFMpeg is not running, exit...\n')
            stdout_buf = self.ffmpeg.get_stdout_buf()
            logs, _ = stdout_buf.get_last_items(100)
            for item in logs:
                dt, line = item[0], item[1]
                print('{}  {}'.format(dt, line))
            self.shutdown_all()

    def _is_stdout_stuck(self) -> bool:
        stdout_buf = self.ffmpeg.get_stdout_buf()
        stdout_items, _ = stdout_buf.get_last_items(1)
        if not stdout_items:
            return False
        stdout_dt, _ = stdout_items[0]
        if self._stdout_stuck_last is None:
            self._stdout_stuck_last = stdout_dt
            self._logger.info("Encoding checker: stdout stuck check started. Exit if stuck > {}s".format(
                self.cfg.ENCODING_MAX_STDOUT_STUCK_TIME
            ))
            return False
        if stdout_dt == self._stdout_stuck_last:
            if self._stdout_stuck_start is None:
                self._stdout_stuck_start = datetime.datetime.now()
                return False
            max_stdout_stuck = datetime.timedelta(seconds=self.cfg.ENCODING_MAX_STDOUT_STUCK_TIME)
            now = datetime.datetime.now()
            delta = now - self._stdout_stuck_start
            if delta > datetime.timedelta(seconds=2):
                self._logger.warning("Stdout is stuck - ({})".format(delta))
            if delta > max_stdout_stuck:
                self._logger.warning("Stdout is completly stuck ({})".format(now))
                return True
        else:
            self._stdout_stuck_last = stdout_dt
            self._stdout_stuck_start = None
        return False

    def _check_encoding_state(self):
        if self.cfg.ENCODING_DISABLE_CHECK:
            return
        if datetime.datetime.now() - self.ffmpeg.start_time < datetime.timedelta(seconds=self.cfg.ENCODING_CHECK_START_DELAY):
            return
        if not self._enc_check_started:
            self._logger.info("Encoding checker started (with delay {}s)".format(
                self.cfg.ENCODING_CHECK_START_DELAY + self.cfg.MANAGER_START_DELAY)
                )
            self._enc_check_started = True
        is_stdout_stuck = self._is_stdout_stuck()
        if is_stdout_stuck:
            self.shutdown_all()
        progress_buf = self.ffmpeg.get_progress_buf()
        progress_items, _ = progress_buf.get_last_items(1)
        if not progress_items:
            return
        progress_dt, progress = progress_items[0]
        if progress_dt and progress_dt == self._enc_last_check_time:
            self._logger.debug("Skip encoding check, same dt")
            return
        if not self._enc_last_check_time:
            self._enc_last_check_time = progress_dt
        progress = progress_str_to_dict(progress)
        is_fps_valid, fps = self._is_fps_valid(progress)
        is_speed_valid, speed = self._is_speed_valid(progress)
        if not is_fps_valid and not is_speed_valid:
            now = datetime.datetime.now()
            if self._enc_error_start_time is None:
                self._enc_error_start_time = now
                self._logger.info("Error in encoding. fps={}, speed={}, start_time={}".format(
                    fps, speed, self._enc_error_start_time)
                    )
            if now - self._enc_error_start_time > datetime.timedelta(seconds=self.cfg.ENCODING_MAX_ERROR_TIME):
                self._logger.error("Encoding check failed. fps={}, speed={}, dt={}".format(fps, speed, now))
                self.ffmpeg.stop()
                self.shutdown_all()
        else:
            self._enc_error_start_time = None

    def _is_fps_valid(self, progress: dict) -> (bool, int):
        current_fps = float(progress['fps'])
        if not self._enc_base_fps:
            self._enc_base_fps = current_fps
            if current_fps < self.cfg.ENCODING_MIN_BASE_FPS:
                self._enc_min_fps = self.cfg.ENCODING_MIN_BASE_FPS
            else:
                self._enc_min_fps = current_fps - self.cfg.ENCODING_DELTA_FPS
            self._logger.info("Encoding checker: base fps={}, exit if fps < {}".format(
                current_fps, self._enc_min_fps)
                )
            return True, current_fps
        if current_fps < self._enc_min_fps:
            return False, current_fps
        return True, current_fps

    def _is_speed_valid(self, progress: dict) -> (bool, float):
        speed = float(progress['speed'].replace('x', ''))
        if not speed:
            return False, speed
        if not self._enc_min_speed:
            if speed < self.cfg.ENCODING_MIN_SPEED:
                self._enc_min_speed = speed - self.cfg.ENCODING_DELTA_SPEED
            else:
                self._enc_min_speed = self.cfg.ENCODING_MIN_SPEED
            self._logger.info("Encoding checker: base speed={}, exit if speed < {}".format(
                speed, self._enc_min_speed)
                )
            return True, speed
        else:
            if speed < self._enc_min_speed:
                return False, speed
            return True, speed

    def stop(self):
        self._logger.info('Stopping manager thread...')
        self._finish = True
