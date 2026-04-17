# SPIFFS Assets Builder

This script builds the SPIFFS asset partition of an ESP32 project, packaging various resource files into a format usable on the device.

## Features

- Handles the wake-word network model (WakeNet Model)
- Integrates text font files
- Processes emoji image collections
- Automatically generates the asset index file
- Packages the final `assets.bin` file

## Dependencies

- Python 3.6+
- Relevant asset files

## Usage

### Basic Syntax

```bash
./build.py --wakenet_model <wakenet_model_dir> \
    --text_font <text_font_file> \
    --emoji_collection <emoji_collection_dir>
```

### Argument Reference

| Argument | Type | Required | Description |
|------|------|------|------|
| `--wakenet_model` | Directory path | No | Path to the wake-word network model directory |
| `--text_font` | File path | No | Path to the text font file |
| `--emoji_collection` | Directory path | No | Path to the emoji image collection directory |

### Examples

```bash
# Full argument example
./build.py \
    --wakenet_model ../../managed_components/espressif__esp-sr/model/wakenet_model/wn9_nihaoxiaozhi_tts \
    --text_font ../../components/xiaozhi-fonts/build/font_puhui_common_20_4.bin \
    --emoji_collection ../../components/xiaozhi-fonts/build/emojis_64/

# Process only the font file
./build.py --text_font ../../components/xiaozhi-fonts/build/font_puhui_common_20_4.bin

# Process only the emoji collection
./build.py --emoji_collection ../../components/xiaozhi-fonts/build/emojis_64/
```

## Workflow

1. **Create the build directory structure**
   - `build/` - main build directory
   - `build/assets/` - asset file directory
   - `build/output/` - output file directory

2. **Process the wake-word network model**
   - Copy the model file to the build directory
   - Use `pack_model.py` to generate `srmodels.bin`
   - Copy the generated model file to the asset directory

3. **Process the text font**
   - Copy the font file to the asset directory
   - Supports `.bin` format font files

4. **Process the emoji collection**
   - Scan image files in the specified directory
   - Supports `.png` and `.gif` formats
   - Automatically generate the emoji index

5. **Generate configuration files**
   - `index.json` - asset index file
   - `config.json` - build configuration file

6. **Package the final assets**
   - Use `spiffs_assets_gen.py` to generate `assets.bin`
   - Copy it to the build root directory

## Output Files

After the build finishes, the following files are generated under `build/`:

- `assets/` - all asset files
- `assets.bin` - final SPIFFS asset file
- `config.json` - build configuration
- `output/` - intermediate output files

## Supported Asset Formats

- **Model file**: `.bin` (processed through pack_model.py)
- **Font file**: `.bin`
- **Image file**: `.png`, `.gif`
- **Config file**: `.json`

## Error Handling

The script includes robust error handling:

- Checks whether source files/directories exist
- Validates subprocess execution results
- Provides detailed error messages and warnings

## Notes

1. Make sure all dependent Python scripts are in the same directory
2. Use absolute paths or paths relative to the script directory for asset files
3. The build process cleans up previous build artifacts
4. The generated `assets.bin` size is limited by the SPIFFS partition size
