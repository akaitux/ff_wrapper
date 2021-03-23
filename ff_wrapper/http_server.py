import socket
import http.server
try:
    from http.server import ThreadingHTTPServer as HTTPServer
except ImportError:
    from http.server import HTTPServer as HTTPServer
    print("Warning - python lower than 3.7 and HTTP Server running in one-thread mode")
import json
from ffmpeg import FFMpegProc
from config import Config


DT_FORMAT = '%Y-%m-%d %H:%M:%S'


class _ThreadingHTTPServer(HTTPServer):

    def __init__(self, *args, ffmpeg=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ffmpeg = ffmpeg
        self.cfg = Config()


class _Handler(http.server.BaseHTTPRequestHandler):

    protocol_version = 'HTTP/1.0'

    def do_GET(self):
        if self.path.startswith('/last_stdout'):
            return self._get_last_stdout()
        elif self.path.startswith('/last_progress'):
            return self._get_last_progress()
        elif self.path.startswith('/start_time'):
            return self._get_start_time()
        elif self.path.startswith('/cmd'):
            return self._get_cmd()
        elif self.path.startswith('/get_container_id'):
            return self._get_container_id()
        elif self.path.startswith('/get_pid'):
            return self._get_pid()
        elif self.path.startswith('/get_ffmpeg_pid'):
            return self._get_ffmpeg_pid()

    def _parse_params(self, path) -> dict:
        params = {}
        if '?' in path:
            params_src = self.path.split('?')[1]
            params_src = params_src.split('&')
            for param in params_src:
                if '=' in param:
                    k, v = param.split('=')
                    params[k] = v
                else:
                    params[param] = True
        return params

    def _get_last_stdout(self):
        buf = self.server.ffmpeg.get_stdout_buf()
        self._get_last_logs(buf)

    def _get_last_progress(self):
        buf = self.server.ffmpeg.get_progress_buf()
        self._get_last_logs(buf)

    def _get_last_logs(self, buf):
        """
        params: count <int> - количество последних строк
                json <bool> - [ [<dt>, <line>] ]
                range <str> - 0-10000
        """
        count = 20
        params = self._parse_params(self.path)
        if 'count' in params:
            try:
                count = int(params['count'])
            except ValueError:
                content = 'count must be int\n'.encode('utf-8')
                self.send_response(400)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(content)
                return
        is_json = params.get('json', False)
        if count > 0:
            lines, _ = buf.get_last_items(count)
        else:
            lines, _ = buf.get_all()
        if is_json:
            response = []
            for dt, line in lines:
                response.append(('{}'.format(dt.strftime(DT_FORMAT)), line))
            try:
                response = json.dumps(response).encode('utf-8')
            except ValueError:
                self.send_response(500)
                self.send_header('content-type', 'text/plain')
                self.end_headers()
                self.wfile.write('error while dumps json from: \n {}\n'.format(str(lines)).encode('utf-8'))
                return
        else:
            response = ''
            for dt, line in lines:
                response += '<{}> {}\n'.format(dt.strftime(DT_FORMAT), line)
            response = response.encode('utf-8')

        self.send_response(200)
        if is_json:
            self.send_header('Content-type', 'text/json')
        else:
            self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(response)

    def _get_start_time(self):
        start_time = self.server.ffmpeg.start_time
        if not start_time:
            self.send_response(500)
            self.send_header('content-type', 'text/plain')
            self.end_headers()
            self.wfile.write('Stream is not started'.encode('utf-8'))
            return
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(start_time.strftime(DT_FORMAT).encode('utf-8'))

    def _get_cmd(self):
        args = self.server.ffmpeg.args
        if not args:
            self.send_response(500)
            self.send_header('content-type', 'text/plain')
            self.end_headers()
            self.wfile.write('Args is empty'.encode('utf-8'))
            return
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(args.encode('utf-8'))

    def _get_container_id(self):
        cfg = Config()
        container_id = cfg.CONTAINER_ID
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(container_id.encode('utf-8'))

    def _get_pid(self):
        cfg = Config()
        pid = cfg.PID
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(pid.encode('utf-8'))

    def _get_ffmpeg_pid(self):
        cfg = Config()
        pid = cfg.FFMPEG_PID
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(pid.encode('utf-8'))


def _is_port_in_use(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def get_http_server(ffmpeg: FFMpegProc):
    cfg = Config()
    max_errors = 100  # Максимальное количество попыток поиска открытого порта
    while True:
        if _is_port_in_use(cfg.HTTP_HOST, cfg.HTTP_PORT):
            if max_errors == 0:
                print("Port not found, search limit reached")
                break
            print("Port {} already in use, find next...".format(cfg.HTTP_PORT))
            cfg.HTTP_PORT += 1
            max_errors -= 1
            continue
        print("HTTP Server will be available on {}:{}".format(cfg.HTTP_HOST, cfg.HTTP_PORT))
        break
    cfg.save_status_to_files()
    server_address = (cfg.HTTP_HOST, int(cfg.HTTP_PORT))
    if ffmpeg is None:
        raise Exception("Error. Init HTTP Server without ffmpeg")
    return _ThreadingHTTPServer(server_address, _Handler, ffmpeg=ffmpeg)
