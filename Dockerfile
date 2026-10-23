# Next Post desk + the live auto-clipper, in one image. Run both with: docker compose up -d
# Keys come from .env and sarang/.env at run time; they are never copied into the image.
FROM python:3.12-slim

# ffmpeg cuts clips; libegl/libgles are what MediaPipe needs on a machine without a screen
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libegl1 libgles2 libgl1 curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /app

# the desk
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# the auto-clipper's packages (cached unless its lock file changes)
COPY sarang/pyproject.toml sarang/uv.lock sarang/
RUN cd sarang && uv sync --frozen --no-install-project --no-dev

# the MediaPipe models the clipper listens and looks with
RUN mkdir -p sarang/models && cd sarang/models \
 && base=https://storage.googleapis.com/mediapipe-models \
 && curl -fsSL -o yamnet.tflite $base/audio_classifier/yamnet/float32/1/yamnet.tflite \
 && curl -fsSL -o efficientdet_lite0.tflite $base/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite \
 && curl -fsSL -o blaze_face_short_range.tflite $base/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite \
 && curl -fsSL -o pose_landmarker_lite.task $base/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task

COPY . .
RUN cd sarang && uv sync --frozen --no-dev

EXPOSE 8765
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8765"]
