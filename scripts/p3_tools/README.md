# P3 Audio Format Conversion and Playback Tools

This directory contains several Python scripts for working with the P3 audio format:

## 1. Audio Conversion Tool (convert_audio_to_p3.py)

Converts a regular audio file into the P3 format (a stream of 4-byte headers + Opus packets) and applies loudness normalization.

### Usage

```bash
python convert_audio_to_p3.py <input audio file> <output P3 file> [-l LUFS] [-d]
```

Optional option `-l` sets the target loudness for normalization (default -16 LUFS). Optional option `-d` disables loudness normalization.

If the input audio meets any of the following conditions, it is recommended to use `-d` to disable loudness normalization:
- The audio is very short
- The audio has already been loudness-adjusted
- The audio comes from the default TTS (the TTS currently used by LittleWise already has a default loudness of -16 LUFS)

Example:
```bash
python convert_audio_to_p3.py input.mp3 output.p3
```

## 2. P3 Audio Playback Tool (play_p3.py)

Plays a P3-format audio file.

### Features

- Decodes and plays P3-format audio files
- Applies a fade-out at the end of playback or on user interrupt to avoid pops
- Supports specifying the file to play via a command-line argument

### Usage

```bash
python play_p3.py <P3 file path>
```

Example:
```bash
python play_p3.py output.p3
```

## 3. Audio Reverse-Conversion Tool (convert_p3_to_audio.py)

Converts a P3-format file back to a regular audio file.

### Usage

```bash
python convert_p3_to_audio.py <input P3 file> <output audio file>
```

The output audio file must have an extension.

Example:
```bash
python convert_p3_to_audio.py input.p3 output.wav
```
## 4. Audio/P3 Batch Conversion Tool

A graphical tool supporting batch conversion of audio to P3 and P3 to audio.

![](./img/img.png)

### Usage
```bash
python batch_convert_gui.py
```

## Dependency Installation

Before using these scripts, make sure the required Python libraries are installed:

```bash
pip install librosa opuslib numpy tqdm sounddevice pyloudnorm soundfile
```

Or use the provided requirements.txt file:

```bash
pip install -r requirements.txt
```

## P3 Format Description

The P3 format is a simple streaming audio format structured as follows:
- Each audio frame consists of a 4-byte header followed by an Opus-encoded packet
- Header format: [1 byte type, 1 byte reserved, 2 bytes length]
- Fixed sample rate of 16000Hz, mono
- Each frame is 60ms long
