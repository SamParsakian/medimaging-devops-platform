FROM python:3.11-slim

WORKDIR /app

# libgomp1 is needed by torch/scipy's OpenMP-based math kernels at runtime -
# not included in the slim base image by default.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# torch/torchvision are installed first from the CPU-only wheel index, so
# torchxrayvision (installed next, from requirements.txt) doesn't pull in
# the much larger CUDA-enabled build and its nvidia-* dependencies - this
# service never uses a GPU.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Downloads the pre-trained model weights at build time, so starting the
# container never depends on internet access.
RUN python -c "import torchxrayvision as xrv; xrv.models.DenseNet(weights='densenet121-res224-all')"

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
