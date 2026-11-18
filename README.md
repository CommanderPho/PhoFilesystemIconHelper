# PhoFilesystemIconHelper
A tool to enable changing folder/file icons on Windows

# Requires
https://www.imagemagick.org/script/download.php#windows
### Install via:
```ps1
winget install ImageMagick.Q16-HDRI
```

ImageMagick is only needed for the vendored **magico** PNG→folder-icon pipeline. ICNS→ICO conversion uses **Pillow** (already a project dependency) and works on Windows without ImageMagick or macOS `iconutil`.

## Convert ICNS → ICO (Windows)

Convert a single macOS `.icns` to a multi-size Windows `.ico`:

```ps1
uv run python -m phofilesystemiconhelper icns-to-ico path\to\icon.icns
uv run python -m phofilesystemiconhelper icns-to-ico path\to\icon.icns -o path\to\out.ico
```

Batch-convert a directory:

```ps1
uv run python -m phofilesystemiconhelper icns-to-ico path\to\icns_dir -o path\to\out_dir
uv run python -m phofilesystemiconhelper icns-to-ico path\to\icns_dir -o path\to\out_dir --recursive
```

Or from Python:

```python
from phofilesystemiconhelper import icns_to_ico

icns_to_ico(r"path\to\icon.icns")  # writes icon.ico beside the source
```

The GUI icon picker also accepts `.icns` and converts beside the source before apply.

## Disk icons: index → match → apply

Build a SQLite database of every `.icns` / `.ico` under a folder (recursive), match them to local HDD/SSD hardware, and apply the best icon as the **OS volume icon** (Explorer drive letter / Finder volume).

Recommended library root (avoid also indexing the duplicate `EnvironmentCustomization` mirror unless you intend to):

`EXTERNAL/EXTRACTED_CUSTOM_ICONS/Icons`

```ps1
# 1) Index icons
uv run python -m phofilesystemiconhelper icons index "EXTERNAL/EXTRACTED_CUSTOM_ICONS/Icons"

# 2) List hardware disks
uv run python -m phofilesystemiconhelper disks list

# 3) Show best icon per disk
uv run python -m phofilesystemiconhelper disks match

# 4) Dry-run apply (default)
uv run python -m phofilesystemiconhelper disks apply

# 5) Actually apply (Windows: must run elevated for HKLM DriveIcons)
uv run python -m phofilesystemiconhelper disks apply --yes

# 6) Disk Icon Manager GUI (Windows + macOS)
uv run python -m phofilesystemiconhelper gui
uv run python -m phofilesystemiconhelper gui --db data/icon_index.sqlite --include-system
```

The GUI lists each disk with its **current** volume icon, the **suggested** icon from the DB, and actions to apply the suggestion, choose/drag a custom `.ico`/`.icns`, or revert to the OS default. On Windows, use **Restart elevated** (or launch an admin shell) before Apply / Revert for fixed drives.

Notes:
- DB defaults to `data/icon_index.sqlite`; conversions for the wrong platform format go to `data/icon_cache/`.
- Windows fixed drives use `HKLM\...\Explorer\DriveIcons\<Letter>\DefaultIcon` (admin required). Removable/external disks also get `autorun.inf` + `.ico` on the volume root.
- macOS writes `{mount}/.VolumeIcon.icns` and sets the custom-icon flag when possible. System volume is skipped unless `--include-system`.
- Matching is fuzzy over filename tokens (vendor / model / media / capacity / bus), preferring `New Drive Icons` and `DriveIcons` packs.

## Related Projects/Repos
https://github.com/customIcon/customIcons
https://github.com/sameera-madushan/PosterPy

https://wincopies.com/
https://github.com/pierresprim/WinCopies.Util

https://github.com/customIcon/driveIconPatcher


https://github.com/Nickelony/IconUtilities
https://github.com/esvres/magico

# C# Example
https://www.codeproject.com/articles/9331/create-icons-for-folders-in-windows-explorer-using

## Related Resources/References
https://blog.jihongo.com/en/posts/2020/08/08/customize-windows-folder-icon/
https://learn.microsoft.com/en-us/windows/win32/shell/how-to-customize-folders-with-desktop-ini

## Current Progress
https://stackoverflow.com/questions/71981958/is-there-a-way-to-only-update-one-folders-desktop-ini
https://stackoverflow.com/questions/1115012/custom-windows-folder-icon
https://stackoverflow.com/questions/9670033/how-to-notify-a-folder-using-shchangenotify
https://discuss.python.org/t/is-there-a-library-to-change-windows-10-default-program-icon/5846/3
https://stackoverflow.com/questions/1193711/changing-extension-icon-programmatically/1194227#1194227
https://superuser.com/questions/410085/is-there-a-way-to-easily-set-the-icon-a-folder-uses
https://stackoverflow.com/questions/41392818/change-directory-folder-icon-using-c-sharp-programmatically


folder_path = "C:/Users/pho/repos/PhoFilesystemIconHelper/test/test_folder"
icon_path = "C:/Users/pho/repos/PhoFilesystemIconHelper/data/icons/Colors.01.ico"


## Extract Disk Icons

uv run python extract_disk_texture.py -- --input "E:/Dropbox (Personal)/personalStore/records/Computer Storage Information/iCloud 2026-11-17/IMG_5858.png" --drive-type 3.5 --enhance --export-obj

    H\ScreenRecordings\L\Backups


    
## Main RUn
```ps1

uv run python -m phofilesystemiconhelper icons index "EXTERNAL/EXTRACTED_CUSTOM_ICONS/Icons"
uv run python -m phofilesystemiconhelper disks list
uv run python -m phofilesystemiconhelper disks match

```