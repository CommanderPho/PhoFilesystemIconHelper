Uses [`ExtractIconExW` function](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-extracticonexw) to extract icons from libraries. This function should be compatible with both, __Windows PowerShell 5.1 and PowerShell 7+__. It will extract both icons, large and small, from a given index (`-InconIndex`). The function outputs 2 `FileInfo` instances pointing to the created icons given in `-DestinationFolder`. If no destination folder is provided, the icons will be extracted to the PowerShell current directory (`$pwd`).

```powershell
# Extracts to PWD
Invoke-ExtractIconEx -InconIndex 1

# Targeting a different library
Invoke-ExtractIconEx -SourceLibrary user32.dll -InconIndex 1

# Using a different target folder
Invoke-ExtractIconEx path\to\my\folder -InconIndex 1
```