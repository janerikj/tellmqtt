FROM python:3.9-bullseye
WORKDIR /tellmqtt
COPY tellmqtt/ .
RUN pip install --progress-bar off --no-cache-dir -r requirements.txt
ENV TELLMQTT_OREGON_CHECKSUM=true
CMD ["python", "-m", "tellmqtt", "-d", "/dev/tellstickDuo", "-h", "localhost"]

# Build:
# docker build -t tellmqtt-image .

# Run:
# docker run --device /dev/tellstickDuo:/dev/tellstickDuo tellmqtt-image
