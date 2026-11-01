# Проверка: может ли обычная программа открыть микрофон по умолчанию (MME, общий режим),
# пока работает Voicemeeter. Запуск: powershell -ExecutionPolicy Bypass -File tools\mic-test.ps1
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class Mci {
  [DllImport("winmm.dll", CharSet=CharSet.Unicode)]
  public static extern int mciSendString(string cmd, StringBuilder ret, int len, IntPtr cb);
  public static string Run(string c){ var sb=new StringBuilder(256); int r=mciSendString(c,sb,256,IntPtr.Zero); return r==0 ? "ok" : ("ERR "+r); }
}
"@
$wav = "$env:TEMP\mic-test.wav"
$r1 = [Mci]::Run("open new type waveaudio alias mt")
$r2 = [Mci]::Run("record mt")
Start-Sleep -Milliseconds 1500
$r3 = [Mci]::Run("save mt `"$wav`"")
[Mci]::Run("close mt") | Out-Null
$size = if (Test-Path $wav) { (Get-Item $wav).Length } else { 0 }
"open=$r1 record=$r2 save=$r3 bytes=$size"
