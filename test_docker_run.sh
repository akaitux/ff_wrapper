sudo docker build -t ffw-ffmpeg-nvidia-test .
sudo docker run --name ffw-ffmpeg -e ENCODING_CHECK_START_DELAY=20 --rm -ti ffw-ffmpeg-nvidia-test -i http://rtmp-server:1935/spas -vcodec h264 -b:v 1M -maxrate 1M -bufsize 2M -y -f flv /dev/null
