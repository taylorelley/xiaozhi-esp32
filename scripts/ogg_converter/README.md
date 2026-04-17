# ogg_covertor LittleWise AI OGG Sound Effect Batch Converter

This script is a batch OGG conversion tool that converts input audio files into the OGG format used by LittleWise.

It is built on the Python third-party library `ffmpeg-python` and **requires** an `ffmpeg` environment.

You can download the ffmpeg distribution for your system from [here](https://ffmpeg.org/download.html). Add it to your PATH, or place it in the same directory as the script.

Supports converting between OGG and other audio formats, volume adjustment, and more.

# Create and activate a virtual environment

```bash
# Create the virtual environment
python -m venv venv
# Activate the virtual environment
source venv/bin/activate # Mac/Linux
venv\Scripts\activate # Windows
```
# Download FFmpeg
Download ffmpeg from [here](https://ffmpeg.org/download.html).

Download the version matching your current system, and place the `ffmpeg` executable in the same directory as the script or add the executable's directory to your PATH.

# Install dependencies
Run this inside the virtual environment.

```bash
pip install ffmpeg-python
```

# Run the script
```bash
python ogg_covertor.py
```
