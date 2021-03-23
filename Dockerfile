FROM jrottenberg/ffmpeg:4.1-vaapi

RUN apt-get update; apt-get -y install python3

RUN mkdir /ff_wrapper
ADD ./ff_wrapper  /ff_wrapper

ENTRYPOINT ["/ff_wrapper/main.py"]
