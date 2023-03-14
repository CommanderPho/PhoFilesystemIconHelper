function Invoke-ExtractIconEx {
    [CmdletBinding(PositionalBinding = $false)]
    param(
        [Parameter()]
        [ValidateNotNull()]
        [string] $SourceLibrary = 'shell32.dll',

        [Parameter(Position = 0)]
        [string] $DestinationFolder = $pwd.Path,

        [Parameter(Position = 1)]
        [int] $InconIndex
    )

    $refAssemblies = @(
        [Drawing.Icon].Assembly.Location

        if ($IsCoreCLR) {
            $pwshLocation = Split-Path -Path ([psobject].Assembly.Location) -Parent
            $pwshRefAssemblyPattern = [IO.Path]::Combine($pwshLocation, 'ref', '*.dll')
            (Get-Item -Path $pwshRefAssemblyPattern).FullName
        }
    )

    Add-Type -AssemblyName System.Drawing
    Add-Type '
    using System;
    using System.ComponentModel;
    using System.Runtime.InteropServices;
    using System.Drawing;
    using System.IO;

    namespace Win32Native
    {
        internal class SafeIconHandle : SafeHandle
        {
            [DllImport("user32.dll")]
            private static extern bool DestroyIcon(IntPtr hIcon);

            public SafeIconHandle() : base(IntPtr.Zero, true) { }

            public override bool IsInvalid
            {
                get
                {
                    return handle == IntPtr.Zero;
                }
            }

            protected override bool ReleaseHandle()
            {
                return DestroyIcon(handle);
            }
        }

        public static class ShellApi
        {
            [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
            private static extern uint ExtractIconExW(
                string szFileName,
                int nIconIndex,
                out SafeIconHandle phiconLarge,
                out SafeIconHandle phiconSmall,
                uint nIcons);

            private static void ExtractIconEx(string fileName, int iconIndex, out SafeIconHandle iconLarge,
                out SafeIconHandle iconSmall)
            {
                if (ExtractIconExW(fileName, iconIndex, out iconLarge, out iconSmall, 1) == uint.MaxValue)
                {
                    throw new Win32Exception();
                }
            }

            public static FileInfo[] ExtractIcon(string sourceExe,
                string destinationFolder, int iconIndex)
            {
                SafeIconHandle largeIconHandle;
                SafeIconHandle smallIconHandle;

                ExtractIconEx(sourceExe, iconIndex, out largeIconHandle, out smallIconHandle);

                using (largeIconHandle)
                using (smallIconHandle)
                using (Icon largeIcon = Icon.FromHandle(largeIconHandle.DangerousGetHandle()))
                using (Icon smallIcon = Icon.FromHandle(smallIconHandle.DangerousGetHandle()))
                {
                    FileInfo[] outFiles = new FileInfo[2]
                    {
                        new FileInfo(Path.Combine(destinationFolder, string.Format("{0}-largeIcon-{1}.bmp", sourceExe, iconIndex))),
                        new FileInfo(Path.Combine(destinationFolder, string.Format("{0}-smallIcon-{1}.bmp", sourceExe, iconIndex)))
                    };

                    largeIcon.ToBitmap().Save(outFiles[0].FullName);
                    smallIcon.ToBitmap().Save(outFiles[1].FullName);

                    return outFiles;
                }
            }
        }
    }
    ' -ReferencedAssemblies $refAssemblies

    $DestinationFolder = $PSCmdlet.GetUnresolvedProviderPathFromPSPath($DestinationFolder)
    [Win32Native.ShellApi]::ExtractIcon($SourceLibrary, $DestinationFolder, $InconIndex)
}