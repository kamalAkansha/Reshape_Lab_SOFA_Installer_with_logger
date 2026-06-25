FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3.10-distutils \
    python3-pip \
    libpython3.10 \
    libassimp5 \
    libgl1 \
    libglu1-mesa \
    libglew2.2 \
    libqt5webenginewidgets5 \
    libqt5charts5 \
    libqt5opengl5 \
    libx11-xcb1 \
    libxkbcommon-x11-0 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python mathematical dependencies
RUN python3.10 -m pip install numpy scipy

# Force Qt to use X11 forwarding
ENV QT_QPA_PLATFORM=xcb

# Map SOFA and STLIB Python module paths globally
ENV PYTHONPATH=/bundle/plugins/SofaPython3/lib/python3/site-packages:/bundle/plugins/STLIB/lib/python3/site-packages

WORKDIR /bundle
CMD ["./bin/runSofa"]
