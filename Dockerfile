# ==============================================================================
# TOACD Deployment A: GitHub Edition (Production Container)
# Base: Ubuntu 22.04 LTS with LLVM/Clang compiler & PyTorch CPU runtime
# ==============================================================================

FROM ubuntu:22.04

LABEL maintainer="TOACD Research Team"
LABEL version="1.0-github"
LABEL description="TOACD Multi-Agent Compiler Optimization Selector — GitHub Edition"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install Clang, LLVM, Python 3, build utilities, and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    clang \
    llvm \
    llvm-dev \
    build-essential \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Symlink python
RUN ln -s /usr/bin/python3 /usr/bin/python || true

# Point toolchain to system binaries
ENV TOACD_CLANG_PATH=/usr/bin/clang
ENV TOACD_OPT_PATH=/usr/bin/opt

# Create non-root unprivileged user for compiler execution sandboxing
RUN useradd -m -u 1000 -s /bin/bash appuser

WORKDIR /app

# Copy dependency manifest and install CPU-optimized packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# Copy source tree
COPY . /app

# Ensure test fixtures omitted from Git are compiled deterministically from test_cases
RUN mkdir -p /app/Codes/ir_output && \
    clang -O0 -Xclang -disable-O0-optnone -S -emit-llvm /app/Codes/test_cases/security_checks.c -o /app/Codes/ir_output/security_checks_O0.ll && \
    clang -O1 -S -emit-llvm /app/Codes/test_cases/security_checks.c -o /app/Codes/ir_output/security_checks_O1.ll && \
    clang -O2 -S -emit-llvm /app/Codes/test_cases/security_checks.c -o /app/Codes/ir_output/security_checks_O2.ll && \
    clang -O3 -S -emit-llvm /app/Codes/test_cases/security_checks.c -o /app/Codes/ir_output/security_checks_O3.ll

# Ensure non-root appuser owns app directory and create runtime dirs
RUN mkdir -p /app/scratch /app/data /app/temp && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/status || exit 1

# Start the Tornado web server binding to assigned port
CMD ["sh", "-c", "python 'Codes/Python Scripts/run_web.py' --host 0.0.0.0 --port ${PORT:-8080}"]
