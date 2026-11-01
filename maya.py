"""
Maya Phone Bridge — звонки по телефону голосом Maya (Sesame AI) через Zoom Phone.

Управляет маршрутизацией звука в Voicemeeter Banana через официальный Remote API
(VoicemeeterRemote64.dll). Внешних зависимостей нет; для горячих клавиш нужен
пакет `keyboard` (pip install keyboard).

Схема (Voicemeeter Banana):

    Zoom  -> динамик  "Voicemeeter Input"      -> полоса VAIO (3) -> B1 (+A1)
    Edge  -> динамик  "Voicemeeter AUX Input"  -> полоса AUX  (4) -> B2 (+A1)
    Твой микрофон                              -> полоса HW1  (0) -> по режиму

    B1 = "Voicemeeter Out B1"  -> микрофон для Maya (Edge)
    B2 = "Voicemeeter Out B2"  -> микрофон для Zoom
    A1 = твои динамики/наушники (ты слышишь обе стороны)

Команды:
    python maya.py setup            разовая настройка Voicemeeter (+ маршрутизация Edge/Zoom)
    python maya.py brief            инструктаж: ты говоришь с Maya, звонок её не слышит
    python maya.py call             звонок: Maya <-> абонент, ты слушаешь
    python maya.py takeover         перехват: ты говоришь с абонентом, Maya молчит, но слышит
    python maya.py whisper          подсказка: звонок + Maya слышит тебя, абонент — нет
    python maya.py off              всё разведено, ничего никуда не уходит
    python maya.py status           показать текущую маршрутизацию
    python maya.py dial +15551234567  режим call + набор номера в Zoom Phone
    python maya.py open             открыть Sesame в Edge
    python maya.py hotkeys          горячие клавиши Ctrl+Alt+1..5
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"

DEFAULT_CONFIG = {
    # Папка установки Voicemeeter (там лежит VoicemeeterRemote64.dll)
    "voicemeeter_dir": r"C:\Program Files (x86)\VB\Voicemeeter",
    # Физические устройства (имена как в Панели управления → Звук)
    "mic": "Microphone Array on SoundWire Device (5- Cirrus Logic XU)",
    "speakers": "Speakers (Cirrus Logic XU (with APO Extensions))",
    # Браузер, в котором живёт Maya (отдельный от основного, чтобы не тащить в звонок YouTube)
    "maya_browser_exe": "msedge.exe",
    "zoom_exe": "Zoom.exe",
    "sesame_url": "https://www.sesame.com/",
    # Имена виртуальных устройств Voicemeeter Banana (в старых версиях: "VoiceMeeter Output"/"VoiceMeeter Aux Output")
    "vm_zoom_out": "Voicemeeter Input",
    "vm_maya_out": "Voicemeeter AUX Input",
    "vm_maya_mic": "Voicemeeter Out B1",
    "vm_zoom_mic": "Voicemeeter Out B2",
    # NirSoft SoundVolumeView (необязательно) — для автоматической маршрутизации по приложениям
    "soundvolumeview": r"tools\SoundVolumeView.exe",
}

# Индексы Voicemeeter Banana
MIC, HW2, HW3, ZOOM, MAYA = 0, 1, 2, 3, 4
STRIP_NAMES = {MIC: "Твой микрофон", ZOOM: "Zoom (абонент)", MAYA: "Maya"}
BUSES = ("A1", "A2", "A3", "B1", "B2")

OFF = dict(A1=0, A2=0, A3=0, B1=0, B2=0, Mute=0)


def route(**kw) -> dict:
    return {**OFF, **kw}


# Для каждого режима — что куда идёт.
#   A1 = твои уши, B1 = уши Maya, B2 = уши абонента
MODES: dict[str, dict[int, dict]] = {
    "off": {
        MIC: route(),
        ZOOM: route(A1=1),
        MAYA: route(A1=1),
    },
    "brief": {
        MIC: route(B1=1),          # Maya слышит тебя
        ZOOM: route(A1=1),         # звонок (если идёт) слышишь только ты
        MAYA: route(A1=1),         # ты слышишь Maya, абонент — нет
    },
    "call": {
        MIC: route(),              # твой микрофон никуда не идёт
        ZOOM: route(A1=1, B1=1),   # Maya и ты слышите абонента
        MAYA: route(A1=1, B2=1),   # абонент и ты слышите Maya
    },
    "takeover": {
        MIC: route(B1=1, B2=1),    # абонент слышит тебя, Maya тоже (держит контекст)
        ZOOM: route(A1=1, B1=1),
        MAYA: route(Mute=1),       # Maya заглушена
    },
    "whisper": {
        MIC: route(B1=1),          # Maya слышит тебя, абонент — нет
        ZOOM: route(A1=1, B1=1),
        MAYA: route(A1=1, B2=1),
    },
}

MODE_HELP = {
    "off": "всё разведено",
    "brief": "инструктаж — говоришь с Maya",
    "call": "звонок — Maya говорит с абонентом",
    "takeover": "перехват — говоришь ты, Maya молчит",
    "whisper": "подсказка — Maya слышит тебя, абонент нет",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


class Voicemeeter:
    """Тонкая обёртка над VoicemeeterRemote64.dll."""

    BANANA = 2

    def __init__(self, cfg: dict):
        if os.name != "nt":
            sys.exit("Voicemeeter работает только в Windows.")
        name = "VoicemeeterRemote64.dll" if ctypes.sizeof(ctypes.c_void_p) == 8 else "VoicemeeterRemote.dll"
        path = Path(cfg["voicemeeter_dir"]) / name
        if not path.exists():
            sys.exit(f"Не найден {path}. Установи Voicemeeter Banana (см. docs/SETUP-WINDOWS.md) "
                     f"или поправь voicemeeter_dir в config.json.")
        dll = ctypes.WinDLL(str(path))
        dll.VBVMR_Login.restype = ctypes.c_long
        dll.VBVMR_Logout.restype = ctypes.c_long
        dll.VBVMR_RunVoicemeeter.argtypes = [ctypes.c_long]
        dll.VBVMR_GetVoicemeeterType.argtypes = [ctypes.POINTER(ctypes.c_long)]
        dll.VBVMR_IsParametersDirty.restype = ctypes.c_long
        dll.VBVMR_GetParameterFloat.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_float)]
        dll.VBVMR_SetParametersW.argtypes = [ctypes.c_wchar_p]
        dll.VBVMR_SetParametersW.restype = ctypes.c_long
        self.dll = dll

    def __enter__(self) -> "Voicemeeter":
        rc = self.dll.VBVMR_Login()
        if rc < 0:
            sys.exit(f"Не удалось подключиться к Voicemeeter (код {rc}).")
        if rc == 1:  # клиент подключён, но сам Voicemeeter не запущен
            print("Запускаю Voicemeeter Banana…")
            self.dll.VBVMR_RunVoicemeeter(self.BANANA)
        kind = ctypes.c_long(0)
        for _ in range(50):
            if self.dll.VBVMR_GetVoicemeeterType(ctypes.byref(kind)) == 0:
                break
            time.sleep(0.2)
        else:
            sys.exit("Voicemeeter не ответил. Запусти Voicemeeter Banana вручную и повтори.")
        if kind.value != self.BANANA:
            sys.exit("Нужен именно Voicemeeter Banana (запущена другая редакция).")
        self.sync()
        return self

    def __exit__(self, *exc) -> None:
        time.sleep(0.15)  # дать движку применить последние параметры
        self.dll.VBVMR_Logout()

    def sync(self) -> None:
        for _ in range(20):
            if self.dll.VBVMR_IsParametersDirty() <= 0:
                return
            time.sleep(0.02)

    def run(self, script: str) -> None:
        rc = self.dll.VBVMR_SetParametersW(script)
        if rc != 0:
            raise RuntimeError(f"Voicemeeter отклонил скрипт (код {rc}): {script}")

    def get(self, name: str) -> float:
        self.sync()
        val = ctypes.c_float()
        if self.dll.VBVMR_GetParameterFloat(name.encode("ascii"), ctypes.byref(val)) != 0:
            raise RuntimeError(f"Не удалось прочитать {name}")
        return val.value


def apply_mode(vm: Voicemeeter, mode: str) -> None:
    parts = []
    for strip in (MIC, HW2, HW3, ZOOM, MAYA):
        r = MODES[mode].get(strip, route())
        parts += [f"Strip[{strip}].{k}={int(v)}" for k, v in r.items()]
    vm.run(";".join(parts) + ";")
    beep(mode)
    print(f"Режим: {mode.upper()} — {MODE_HELP[mode]}")


def beep(mode: str) -> None:
    """Короткий сигнал в системные динамики (не попадает в звонок)."""
    try:
        import winsound
        tone = {"off": 400, "brief": 600, "call": 900, "takeover": 1200, "whisper": 750}[mode]
        winsound.Beep(tone, 120)
    except Exception:
        pass


def cmd_setup(cfg: dict) -> None:
    with Voicemeeter(cfg) as vm:
        q = lambda s: s.replace('"', "")
        vm.run(
            f'Strip[{MIC}].device.wdm="{q(cfg["mic"])}";'
            f'Bus[0].device.wdm="{q(cfg["speakers"])}";'
            f'Strip[{MIC}].Label="MIC (you)";'
            f'Strip[{ZOOM}].Label="ZOOM (callee)";'
            f'Strip[{MAYA}].Label="MAYA";'
        )
        time.sleep(1.0)  # смена устройств перезапускает аудиодвижок
        apply_mode(vm, "off")
    print("Voicemeeter настроен: HW1 = микрофон, A1 = динамики, полосы подписаны.")
    setup_app_routing(cfg)


def setup_app_routing(cfg: dict) -> None:
    svv = Path(cfg["soundvolumeview"])
    if not svv.is_absolute():
        svv = ROOT / svv
    if not svv.exists():
        found = shutil.which("SoundVolumeView.exe")
        svv = Path(found) if found else None
    if not svv:
        print("\nSoundVolumeView не найден — назначь устройства приложениям вручную:\n"
              "  Параметры → Система → Звук → Микшер громкости:\n"
              f"    {cfg['maya_browser_exe']}: вывод = {cfg['vm_maya_out']}, ввод = {cfg['vm_maya_mic']}\n"
              f"  В Zoom (Настройки → Звук): динамик = {cfg['vm_zoom_out']}, микрофон = {cfg['vm_zoom_mic']}\n"
              "  (или положи SoundVolumeView.exe в папку tools\\ и повтори setup)")
        return
    pairs = [
        (cfg["vm_maya_out"], cfg["maya_browser_exe"]),
        (cfg["vm_maya_mic"], cfg["maya_browser_exe"]),
        (cfg["vm_zoom_out"], cfg["zoom_exe"]),
        (cfg["vm_zoom_mic"], cfg["zoom_exe"]),
    ]
    for device, exe in pairs:
        subprocess.run([str(svv), "/SetAppDefault", device, "all", exe], check=False)
        print(f"  {exe}: {device}")
    print("Маршрутизация по приложениям назначена (перезапусти Edge и Zoom, если они открыты).")


def cmd_status(cfg: dict) -> None:
    with Voicemeeter(cfg) as vm:
        state = {s: {b: int(vm.get(f"Strip[{s}].{b}")) for b in (*BUSES, "Mute")} for s in STRIP_NAMES}
    current = next((m for m, r in MODES.items()
                    if all(state[s] == r[s] for s in STRIP_NAMES)), "нестандартный")
    print(f"Текущий режим: {current}")
    for s, name in STRIP_NAMES.items():
        on = [b for b in BUSES if state[s][b]]
        mute = "  [MUTE]" if state[s]["Mute"] else ""
        print(f"  {name:<16} → {', '.join(on) or '—'}{mute}")
    print("  (A1 = ты, B1 = Maya, B2 = абонент)")


def cmd_dial(cfg: dict, number: str) -> None:
    clean = re.sub(r"[\s\-().]", "", number)
    if not re.fullmatch(r"\+?\d{3,15}", clean):
        sys.exit(f"Странный номер: {number}")
    with Voicemeeter(cfg) as vm:
        apply_mode(vm, "call")
    print(f"Набираю {clean} в Zoom Phone…")
    os.startfile(f"zoomphonecall://{clean}")


def cmd_open(cfg: dict) -> None:
    os.startfile("microsoft-edge:" + cfg["sesame_url"])


def cmd_hotkeys(cfg: dict) -> None:
    try:
        import keyboard
    except ImportError:
        sys.exit("Нужен пакет keyboard: pip install keyboard")
    keys = {"ctrl+alt+1": "brief", "ctrl+alt+2": "call", "ctrl+alt+3": "takeover",
            "ctrl+alt+4": "whisper", "ctrl+alt+0": "off"}
    with Voicemeeter(cfg) as vm:
        for combo, mode in keys.items():
            keyboard.add_hotkey(combo, apply_mode, args=(vm, mode))
            print(f"  {combo:<11} {mode:<9} {MODE_HELP[mode]}")
        print("Горячие клавиши активны. Ctrl+C — выход.")
        try:
            keyboard.wait()
        except KeyboardInterrupt:
            pass


def main() -> None:
    p = argparse.ArgumentParser(description="Maya Phone Bridge — Zoom Phone ⇄ Sesame AI")
    sub = p.add_subparsers(dest="cmd", required=True)
    for m in MODES:
        sub.add_parser(m, help=MODE_HELP[m])
    sub.add_parser("setup", help="разовая настройка")
    sub.add_parser("status", help="текущая маршрутизация")
    d = sub.add_parser("dial", help="режим call + набор номера")
    d.add_argument("number")
    sub.add_parser("open", help="открыть Sesame в Edge")
    sub.add_parser("hotkeys", help="горячие клавиши")
    args = p.parse_args()
    cfg = load_config()

    if args.cmd in MODES:
        with Voicemeeter(cfg) as vm:
            apply_mode(vm, args.cmd)
    elif args.cmd == "setup":
        cmd_setup(cfg)
    elif args.cmd == "status":
        cmd_status(cfg)
    elif args.cmd == "dial":
        cmd_dial(cfg, args.number)
    elif args.cmd == "open":
        cmd_open(cfg)
    elif args.cmd == "hotkeys":
        cmd_hotkeys(cfg)


if __name__ == "__main__":
    main()
