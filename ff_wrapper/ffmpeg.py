import subprocess
import shutil
import os
import threading
import datetime
import logging
import time
import signal
import re
import typing
from logbuffer import LogBuffer
from logger import Logger, get_file_logger_handler
from config import Config


class FFMpegProc:

    def __init__(self, args: str):
        self.args = args
        self.first_fps_value = self._get_first_fps_value()
        self.cfg = Config()
        self.bin = self._find_bin()
        self._progress_fifo_path = None  # setted in self._create_fifo
        self._progress_logs_buf = LogBuffer(self.cfg.PROGRESS_BUFFER_LEN)  # (datetime.now, str)
        self._progressbuf_thread_object = None
        self._stdoutbuf_thread_object = None
        self._stdout_logs_writer_thread_object = None
        self._stdout_logs_writer_logger = None  # setted in _stdout_filelog_start_writer
        self._stdout_logsbuf = LogBuffer(self.cfg.STDOUT_BUFFER_LEN)  # (datetime.now, str)
        self.start_time = None  # setted in self.run
        self.progress_last_state = {}  # Last string from progress
        self._logger = Logger('FFmpegProc')
        self._finish = False
        self.process = None

    @property
    def finish(self):
        return self._finish

    def _join_threads(self):
        if self._progressbuf_thread_object:
            self._progressbuf_thread_object.join()
        if self._stdoutbuf_thread_object:
            self._stdoutbuf_thread_object.join()
        if self._stdout_logs_writer_thread_object: 
            self._stdout_logs_writer_thread_object.join()

    def get_progress_buf(self):
        return self._progress_logs_buf

    def get_stdout_buf(self):
        return self._stdout_logsbuf

    def stop(self):
        self._finish = True
        if self.process:
            self.process.kill()
            self.process.wait()
        self._join_threads()

    def _find_bin(self):
        return shutil.which('ffmpeg')

    def _progress_start_piperead_thread(self, fifo_path: str):
        t = threading.Thread(target=self._progress_start_piperead, args=(fifo_path,), daemon=True)
        self._progressbuf_thread_object = t
        t.start()
        self._logger.info('FFMpeg progress thread started')

    def _parse_progress_line_to_dict(self, line) -> dict:
        dct = {}
        if not line:
            return dct
        line = line.split(' ')
        for el in line:
            k, v = el.split('=')
            dct[k] = v
        dct['_time'] = datetime.datetime.now()
        return dct

    def _progress_start_piperead(self, fifo_path: str):
        # В PIPE progress пишется последовательно по 12 элементов, после чего они повторяются
        t = self._progressbuf_thread_object
        with open(fifo_path, 'r') as fifo:
            buffer = [None] * 30
            n = 0
            for line in fifo:
                if self.finish:
                    self._logger.info('FFMpeg progress thread stopped')
                    break
                if 'progress' not in line:
                    # Вырезаем последний символ перевода строки через [:-1]
                    buffer[n] = line[:-1].replace(' ', '')
                    n += 1
                else:
                    buffer[n] = line[:-1].replace(' ', '')
                    line = ' '.join([x for x in buffer if x])
                    self._progress_logs_buf.append((datetime.datetime.now(), line))
                    self.progress_last_state = self._parse_progress_line_to_dict(line)
                    n = 0

    def _stdout_start_piperead_thread(self, process: subprocess.Popen):
        t = threading.Thread(target=self._stdout_start_piperead, args=(process,), daemon=True)
        self._stdoutbuf_thread_object = t
        t.start()
        self._logger.info('FFMpeg stdout thread started')

    def _stdout_start_piperead(self, process: subprocess.Popen):
        t = self._stdoutbuf_thread_object
        if not process:
            self._logger.error("Stdout reader failed, no ffmpeg process")
            return
        for line in process.stdout:
            if self.finish:
                self._logger.info('FFMpeg stdout thread stopped')
                break
            self._stdout_logsbuf.append((datetime.datetime.now(), line.strip()))

    def get_stream_id(self):
        id_str = ''
        if not self.args:
            return str(os.getpid)
        args = self.args.split(' ')
        if '-i' in args:
            for i, el in enumerate(args):
                if el == '-i' and len(el) > i + 1:
                    inp = args[i + 1]
                    inp = inp.replace('://', '_').replace('@', '').replace(':', '_').replace('/', '_')
                    id_str += inp
            if self.start_time:
                id_str += '__{}'.format(self.start_time.strftime('%Y_%m_%d__%H_%M_%S'))
        if not id_str:
            id_str = str(os.getpid())
        return id_str

    def _stdout_filelog_start_writer_thread(self):
        start_time = self.start_time.strftime('%Y_%m_%d__%H_%M_%S')
        log_path = os.path.join(self.cfg.LOGS_PATH, 'ffmpeg_{}.log'.format(start_time))
        self._logger.info('Logs - {}'.format(self.cfg.LOGS_PATH))
        logger = logging.getLogger("FFMpeg stdout")
        self._stdout_logs_writer_logger = logger
        logger.setLevel(logging.INFO)
        try:
            def handler_namer(filename):
                log_directory = os.path.split(filename)[0]
                filename = filename.split('/')[-1]
                filename = filename[:filename.find('.log')]
                filename = os.path.join(log_directory, filename)
                if not os.path.exists('{}.log'.format(filename)):
                    return '{}.log'.format(filename)
                index = 0
                f = '{}.log.{}'.format(filename, index)
                while os.path.exists(f):
                    index += 1
                    f = '{}.log.{}'.format(filename, index)
                return f
            handler = get_file_logger_handler(log_path)
            handler.namer = handler_namer
        except PermissionError as e:
            self._logger.error('PermissionError:  Permission denied: {}'.format(log_path))
            raise e
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        t = threading.Thread(target=self._stdout_filelog_start_writer, args=(logger,), daemon=True)
        self._stdout_logs_writer_thread_object = t

        def sighup_handler(signum, frame):
            handler.doRollover()

        signal.signal(signal.SIGHUP, sighup_handler)
        self._logger.info('FFMpeg logs writer thread started')
        t.start()

    def _stdout_filelog_start_writer(self, logger: logging.Logger):
        t = self._stdout_logs_writer_thread_object
        stdout_buf = self.get_stdout_buf()
        last_position = 0
        while True:
            if self.finish:
                self._logger.info('FFMpeg logs writer thread stopped')
                break
            current_position = stdout_buf.get_current_position()
            objs, last_position = stdout_buf.get_last_items(current_position - last_position)
            if objs and len(objs[0]) == 2:
                for dt, line in objs:
                    logger.info('<{}> {}'.format(dt.strftime('%Y-%m-%d %H:%M:%S'), line))
            time.sleep(0.5)

    def _create_fifo(self, name) -> str:
        """
        Возвращает путь к созданному fifo pipe
        """
        path = os.path.join(self.cfg.PROGRESS_FIFO_PATH, '{}_{}'.format(os.getpid(), name))
        if os.path.exists(path):
            os.remove(path)
        try:
            os.mkfifo(path)
        except OSError as e:
            self._logger.debug(str(e))
            return None
        self._progress_fifo_path = path
        return path

    def _add_progress_to_cmd(self, cmd: str, fifo_path: str) -> str:
        cmd = cmd.split(' ')
        cmd = ' '.join([cmd[0], '-progress {}'.format(fifo_path)] + cmd[1:])
        return cmd

    def get_process_status(self) -> typing.Tuple[str, str]:
        pid, status = None, None
        process = subprocess.Popen(['ps', '-eo', 'pid,stat', str(self.process.pid)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = process.communicate()
        for line in stdout.splitlines()[1:]:
            line = line.decode('utf-8').strip()
            try:
                _pid, _status = line.split(' ')
                if _pid == str(self.process.pid):
                    pid, status = _pid, _status
            except Exception as e:
                self._logger.debug("Error while splitting line ({}) with ps -eo pid,stat: {}".format(line, str(e)))
        return pid, status

    def _get_first_fps_value(self) -> str:
        fps = []
        search = re.search(r'-r \d{2}', self.args)
        if search:
            fps_value = search.group(0).split(' ')[-1]
            fps_pos = search.start()
            fps.append((fps_pos, fps_value))
        search = re.search(r'fps=\d{2}', self.args)
        if search:
            fps_value = search.group(0).split('=')[-1]
            fps_pos = search.start()
            fps.append((fps_pos, fps_value))
        if not fps:
            return
        return min(fps, key=lambda x: x[0])[1]

    def run(self) -> subprocess.Popen:
        """
        После вызова метода требуется зациклить выполнение программы, т.к. после завершения основного потока кодирование остановится
        """
        if self.process:
            self._logger.warning("Already running")
            return self.process
        if not self.args:
            cmd = self.bin
            process = subprocess.run(cmd.split(' '), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            print(process.stdout)
            return
        cmd = '{} {}'.format(self.bin, self.args)
        fifo_path = self._create_fifo("progress")
        if not fifo_path:
            error = "Error while creating fifo progress file, {}".format(self.cfg.PROGRESS_FIFO_PATH)
            raise Exception(error)
        cmd = self._add_progress_to_cmd(cmd, fifo_path)
        self.start_time = datetime.datetime.now()
        process = subprocess.Popen(cmd.split(' '), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        self.process = process
        self._progress_start_piperead_thread(fifo_path)
        self._stdout_start_piperead_thread(process)
        try:
            if self.cfg.NO_FILE_LOG is False:
                self._stdout_filelog_start_writer_thread()
        except PermissionError:
            return
        return process
