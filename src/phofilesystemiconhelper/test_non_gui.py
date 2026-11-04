# !/usr/bin/env python

# Released to the public domain.
# http://creativecommons.org/publicdomain/zero/1.0/
import os
import sys
import ctypes
from ctypes import wintypes

def update_folder_icon():

    # http://msdn.microsoft.com/en-us/library/ms644950
    SendMessageTimeout = ctypes.windll.user32.SendMessageTimeoutA
    SendMessageTimeout.restype = wintypes.LPARAM  # aka LRESULT
    SendMessageTimeout.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                   wintypes.UINT, wintypes.UINT, ctypes.c_void_p]

    # http://msdn.microsoft.com/en-us/library/bb762118
    SHChangeNotify = ctypes.windll.shell32.SHChangeNotify
    SHChangeNotify.restype = None
    SHChangeNotify.argtypes = [wintypes.LONG, wintypes.UINT, wintypes.LPCVOID, wintypes.LPCVOID]

    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    SHCNE_ASSOCCHANGED = 0x08000000

    SendMessageTimeout(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 0, SMTO_ABORTIFHUNG, 5000, None)
    SHChangeNotify(SHCNE_ASSOCCHANGED, 0, None, None)


def set_folder_icon(folder_path, icon_path):
	if not os.path.isdir(folder_path):
		print("Folder Required To Set The Icon!")
		return

	shell32 = ctypes.windll.shell32

	folder_path = os.path.abspath(folder_path)
	icon_path = os.path.abspath(icon_path)

	fcs = SHFOLDERCUSTOMSETTINGS()
	fcs.dwSize = sizeof(fcs)
	fcs.dwMask = FCSM_ICONFILE
	fcs.pszIconFile = icon_path
	fcs.cchIconFile = 0
	fcs.iIconIndex = 0

	hr = shell32.SHGetSetFolderCustomSettings(byref(fcs), folder_path, FCS_FORCEWRITE)
	if hr:
		raise WindowsError(win32api.FormatMessage(hr))

	sfi = SHFILEINFO()
	hr = shell32.SHGetFileInfoW(folder_path, 0, byref(sfi), sizeof(sfi),
								SHGFI_ICONLOCATION)

	if hr == 0:
		raise WindowsError(win32api.FormatMessage(hr))

	shell32.SHUpdateImageW(sfi.szDisplayName, sfi.iIcon, 0, 0)



def main():
    SendMessageTimeout(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 0, SMTO_ABORTIFHUNG, 5000, None)
    SHChangeNotify(SHCNE_ASSOCCHANGED, 0, None, None)

if __name__ == "__main__":
    main()