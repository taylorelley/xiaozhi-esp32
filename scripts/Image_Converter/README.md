# LVGL Image Conversion Tool

This directory contains two Python scripts for processing and converting images into LVGL format:

## 1. LVGLImage (LVGLImage.py)

Imported from the LVGL [official repo](https://github.com/lvgl/lvgl), the conversion script [LVGLImage.py](https://github.com/lvgl/lvgl/blob/master/scripts/LVGLImage.py).

## 2. LVGL Image Conversion Tool (lvgl_tools_gui.py)

Invokes `LVGLImage.py` to batch-convert images into the LVGL image format.
It can be used to modify the default LittleWise emoticons. A detailed tutorial is available [here](https://www.bilibili.com/video/BV12FQkYeEJ3/).

### Features

- Graphical operation with a more friendly interface
- Supports batch image conversion
- Automatically detects image format and selects the best color format
- Multi-resolution support

### Usage

Create a virtual environment
```bash
# Create venv
python -m venv venv
# Activate the environment
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate      # Windows
```

Install dependencies
```bash
pip install -r requirements.txt
```

Run the conversion tool

```bash
# Activate the environment
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate      # Windows
# Run
python lvgl_tools_gui.py
```
