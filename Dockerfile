FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    PORT=8080

WORKDIR /app

# FFmpeg is required by Whisper, Tesseract provides scanned-PDF OCR, and
# libgomp is required by the Linux builds of OpenCV and PyTorch.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ffmpeg \
        libgomp1 \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

# Install CPU-only PyTorch wheels to keep the Cloud Run image free of CUDA
# libraries. The matching entries in requirements.txt are then already met.
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.2.2 torchvision==0.17.2 \
    && python -m pip install -r requirements.txt

# Ultralytics declares the GUI OpenCV distribution as a dependency. Remove it
# if pip installed it transitively, then restore the headless cv2 files.
RUN python -m pip uninstall --yes opencv-python opencv-contrib-python \
    && python -m pip install --force-reinstall --no-deps opencv-python-headless==4.10.0.84

RUN useradd --create-home --uid 10001 appuser \
    && chown appuser:appuser /app

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8080

# Shell form is intentional: Cloud Run supplies PORT, while 8080 remains a
# safe local default when the image is run directly.
CMD exec streamlit run app.py \
    --server.address=0.0.0.0 \
    --server.port=${PORT:-8080} \
    --server.headless=true
