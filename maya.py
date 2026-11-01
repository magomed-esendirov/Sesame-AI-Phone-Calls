"""
Maya Phone Bridge — голос Maya (Sesame AI) в любом приложении для звонков на Windows:
Zoom, Microsoft Teams, WhatsApp, Telegram, Skype, SIP-софтфоны и т. д.
Проверено на Zoom Phone (исходящий звонок на мобильный номер).

Управляет маршрутизацией звука в Voicemeeter Banana через официальный Remote API
(VoicemeeterRemote64.dll). Внешних зависимостей нет; для горячих клавиш нужен
пакет `keyboard` (pip install keyboard).

Схема (Voicemeeter Banana):

    Звонилка -> динамик "Voicemeeter Input"      -> полоса VAIO (3) -> B1 (+A1)
    Edge     -> динамик "Voicemeeter AUX Input"  -> полоса AUX  (4) -> B2 (+A1)
    Твой микрофон                                -> полоса HW1  (0) -> по режиму

    B1 = "Voicemeeter Out B1"  -> микрофон для Maya (Edge)
    B2 = "Voicemeeter Out B2"  -> микрофон для звонилки (Zoom, Teams, WhatsApp…)
    A1 = твои динамики/наушники (ты слышишь обе стороны)

Команды:
    python maya.py setup            разовая настройка Voicemeeter (+ устройства для Edge)
    python maya.py start            ЗАПУСК: автопереключение компьютер/телефон, Ctrl+Alt+M, Ctrl+Alt+T
    python maya.py pc               Maya слышит тебя (за компьютером)
    python maya.py phone            Maya слышит собеседника и говорит в звонок
    python maya.py takeover         перехват: ты говоришь с собеседником, Maya молчит и слушает
    python maya.py off              всё разведено, ничего никуда не уходит
    python maya.py status           показать текущую маршрутизацию
    python maya.py dial +15551234567  режим phone + набор номера (шаблон dial_uri в config.json)
    python maya.py open             открыть Sesame в Edge
    python maya.py levels [сек]     живые уровни: микрофон / звонок / Maya (диагностика)
    python maya.py stop             закрыть Voicemeeter и освободить устройства
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import threading
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # кириллица в консоли Windows (cp1252 при перенаправлении)
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    "sesame_url": "https://www.sesame.com/",
    # Приложение для звонков: exe — для проверки в `status`; dial_uri — как набирать номер.
    #   Zoom Phone: "zoomphonecall://{number}"; системный обработчик (Teams, Phone Link…): "tel:{number}"
    "call_app_exe": "Zoom.exe",
    "dial_uri": "zoomphonecall://{number}",
    # Имена виртуальных устройств Voicemeeter Banana (в старых версиях: "VoiceMeeter Output"/"VoiceMeeter Aux Output")
    "vm_call_out": "Voicemeeter Input",
    "vm_maya_out": "Voicemeeter AUX Input",
    "vm_maya_mic": "Voicemeeter Out B1",
    "vm_call_mic": "Voicemeeter Out B2",
    # NirSoft SoundVolumeView (необязательно) — для автоматической маршрутизации по приложениям
    "soundvolumeview": r"tools\SoundVolumeView.exe",
    # Автопереключение (start): порог «есть звук» и сколько секунд тишины = конец звонка
    "auto_threshold_db": -45,
    "auto_hold_seconds": 20,
}

# Индексы Voicemeeter Banana
MIC, HW2, HW3, CALL, MAYA = 0, 1, 2, 3, 4
STRIP_NAMES = {MIC: "Твой микрофон", CALL: "Звонок", MAYA: "Maya"}
BUSES = ("A1", "A2", "A3", "B1", "B2")

OFF = dict(A1=0, A2=0, A3=0, B1=0, B2=0, Mute=0)


def route(**kw) -> dict:
    return {**OFF, **kw}


# Для каждого режима — что куда идёт.
#   A1 = твои уши, B1 = уши Maya, B2 = уши собеседника
MODES: dict[str, dict[int, dict]] = {
    "off": {
        MIC: route(),
        CALL: route(A1=1),
        MAYA: route(A1=1),
    },
    "pc": {
        MIC: route(B1=1),          # Maya слышит тебя
        CALL: route(A1=1),         # звонилку слышишь только ты
        MAYA: route(A1=1),         # ты слышишь Maya
    },
    "phone": {
        MIC: route(),              # твой микрофон никуда не идёт
        CALL: route(A1=1, B1=1),   # Maya и ты слышите собеседника
        MAYA: route(A1=1, B2=1),   # собеседник и ты слышите Maya
    },
    "takeover": {
        MIC: route(B1=1, B2=1),    # собеседник слышит тебя, Maya тоже (держит контекст)
        CALL: route(A1=1, B1=1),   # ты и Maya слышите собеседника
        MAYA: route(Mute=1),       # Maya замолчала
    },
}

MODE_HELP = {
    "off": "всё разведено",
    "pc": "КОМПЬЮТЕР — Maya слышит тебя",
    "phone": "ТЕЛЕФОН — Maya слышит собеседника и говорит в звонок",
    "takeover": "ПЕРЕХВАТ — говоришь ты, Maya молчит и слушает",
}


LEGACY_KEYS = {"zoom_exe": "call_app_exe", "vm_zoom_out": "vm_call_out", "vm_zoom_mic": "vm_call_mic"}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for old, new in LEGACY_KEYS.items():  # старые config.json (версия «только Zoom»)
            if old in user:
                user.setdefault(new, user.pop(old))
        cfg.update(user)
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
        dll.VBVMR_GetParameterStringW.argtypes = [ctypes.c_char_p, ctypes.c_wchar_p]
        dll.VBVMR_GetLevel.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.POINTER(ctypes.c_float)]
        desc = [ctypes.c_long, ctypes.POINTER(ctypes.c_long), ctypes.c_wchar_p, ctypes.c_wchar_p]
        dll.VBVMR_Input_GetDeviceDescW.argtypes = desc
        dll.VBVMR_Output_GetDeviceDescW.argtypes = desc
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
        for _ in range(150):  # первый запуск Voicemeeter может занимать 10–20 секунд
            if self.dll.VBVMR_GetVoicemeeterType(ctypes.byref(kind)) == 0:
                break
            time.sleep(0.2)
        else:
            sys.exit("Voicemeeter не ответил. Запусти Voicemeeter Banana вручную и повтори.")
        if kind.value != self.BANANA:
            sys.exit("Нужен именно Voicemeeter Banana (запущена другая редакция).")
        time.sleep(0.3)  # сразу после входа параметры ещё не подтянуты — иначе читаются заводские
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

    # Каналы входов Banana для измерения уровня (pre-fader): HW1 = 0-1, VAIO = 6-13, AUX = 14-21
    LEVEL_CHANNELS = {MIC: (0, 1), CALL: (6, 7), MAYA: (14, 15)}

    def level_db(self, strip: int) -> float:
        """Пиковый уровень полосы до фейдера, дБ (не зависит от маршрутизации и mute)."""
        peak = 0.0
        val = ctypes.c_float()
        for ch in self.LEVEL_CHANNELS[strip]:
            if self.dll.VBVMR_GetLevel(0, ch, ctypes.byref(val)) == 0:
                peak = max(peak, abs(val.value))
        return 20 * math.log10(peak) if peak > 1e-6 else -120.0

    DEV_MME, DEV_WDM = 1, 3

    def devices(self, output: bool) -> list[tuple[int, str]]:
        """Список (тип драйвера, имя) физических устройств, которые видит Voicemeeter."""
        count = (self.dll.VBVMR_Output_GetDeviceNumber if output else self.dll.VBVMR_Input_GetDeviceNumber)()
        get = self.dll.VBVMR_Output_GetDeviceDescW if output else self.dll.VBVMR_Input_GetDeviceDescW
        found = []
        for i in range(max(count, 0)):
            kind = ctypes.c_long()
            name, hwid = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(512)
            if get(i, ctypes.byref(kind), name, hwid) == 0:
                found.append((kind.value, name.value))
        return found

    def find_mme(self, wanted: str, output: bool) -> str | None:
        """MME обрезает имена до 31 символа — ищем устройство по началу имени."""
        for kind, name in self.devices(output):
            if kind == self.DEV_MME and name and (wanted.startswith(name) or name.startswith(wanted[:31])):
                return name
        return None

    def get_str(self, name: str) -> str:
        self.sync()
        buf = ctypes.create_unicode_buffer(512)
        if self.dll.VBVMR_GetParameterStringW(name.encode("ascii"), buf) != 0:
            return "?"
        return buf.value


def read_routes(vm: Voicemeeter) -> dict[int, dict[str, int]]:
    return {s: {b: int(vm.get(f"Strip[{s}].{b}")) for b in (*BUSES, "Mute")} for s in STRIP_NAMES}


def current_mode(state: dict[int, dict[str, int]]) -> str | None:
    return next((m for m, r in MODES.items() if all(state[s] == r[s] for s in STRIP_NAMES)), None)


def apply_mode(vm: Voicemeeter, mode: str, verify: bool = False) -> None:
    parts = []
    for strip in (MIC, HW2, HW3, CALL, MAYA):
        r = MODES[mode].get(strip, route())
        parts += [f"Strip[{strip}].{k}={int(v)}" for k, v in r.items()]
    script = ";".join(parts) + ";"
    vm.run(script)
    if verify:  # после перезапуска аудиодвижка команды могут теряться — повторяем до применения
        for _ in range(10):
            time.sleep(0.5)
            if current_mode(read_routes(vm)) == mode:
                break
            vm.run(script)
        else:
            print(f"Внимание: режим {mode} не подтвердился, проверь `python maya.py status`.")
    beep(mode)
    print(f"Режим: {MODE_HELP[mode]}", flush=True)


def beep(mode: str) -> None:
    """Короткий сигнал в системные динамики (не попадает в звонок)."""
    try:
        import winsound
        tone = {"off": 400, "pc": 600, "phone": 900, "takeover": 1200}[mode]
        winsound.Beep(tone, 120)
    except Exception:
        pass


def hw_device(vm: Voicemeeter, wanted: str, output: bool) -> str:
    """Параметр подключения физического устройства.

    Используем MME: в нём устройство всегда в общем режиме, и микрофон/динамики
    остаются доступны другим программам (Claude, Telegram, браузер). WDM в Voicemeeter
    может захватить устройство монопольно.
    """
    q = lambda s: s.replace('"', "")
    mme = vm.find_mme(wanted, output)
    if mme:
        return f'device.mme="{q(mme)}"'
    print(f"Внимание: MME-версия «{wanted}» не найдена, подключаю через WDM.")
    return f'device.wdm="{q(wanted)}"'


def cmd_setup(cfg: dict) -> None:
    with Voicemeeter(cfg) as vm:
        vm.run(
            f'Strip[{MIC}].{hw_device(vm, cfg["mic"], output=False)};'
            f'Bus[0].{hw_device(vm, cfg["speakers"], output=True)};'
            f'Strip[{MIC}].Label="MIC (you)";'
            f'Strip[{CALL}].Label="CALL (remote)";'
            f'Strip[{MAYA}].Label="MAYA";'
        )
        time.sleep(3.0)  # смена устройств перезапускает аудиодвижок
        apply_mode(vm, "pc", verify=True)
    print("Voicemeeter настроен: HW1 = микрофон, A1 = динамики, полосы подписаны.")
    setup_app_routing(cfg)


def setup_app_routing(cfg: dict) -> None:
    svv = find_svv(cfg)
    if not svv:
        print("\nSoundVolumeView не найден — назначь устройства приложениям вручную:\n"
              "  Параметры → Система → Звук → Микшер громкости:\n"
              f"    {cfg['maya_browser_exe']}: вывод = {cfg['vm_maya_out']}, ввод = {cfg['vm_maya_mic']}\n"
              f"  В приложении для звонков: динамик = {cfg['vm_call_out']}, микрофон = {cfg['vm_call_mic']}\n"
              "  (или положи SoundVolumeView.exe в папку tools\\ и повтори setup)")
        return
    # Полные пути устройств: короткие имена («Voicemeeter Input» / «Voicemeeter AUX Input»)
    # на практике путались. Приложение для звонков не трогаем — устройства выбираются в его настройках.
    drv = "VB-Audio Voicemeeter VAIO\\Device\\"
    exe = cfg["maya_browser_exe"]
    for device, direction in ((cfg["vm_maya_out"], "Render"), (cfg["vm_maya_mic"], "Capture")):
        subprocess.run([str(svv), "/SetAppDefault", f"{drv}{device}\\{direction}", "all", exe], check=False)
        print(f"  {exe}: {device}")
    print(f"Устройства для {exe} назначены. Перезагрузи вкладку Sesame (F5), если она открыта.\n"
          f"В приложении для звонков выбери: динамик = {cfg['vm_call_out']}, микрофон = {cfg['vm_call_mic']}.")


def find_svv(cfg: dict) -> Path | None:
    svv = Path(cfg["soundvolumeview"])
    if not svv.is_absolute():
        svv = ROOT / svv
    if svv.exists():
        return svv
    found = shutil.which("SoundVolumeView.exe")
    return Path(found) if found else None


def app_devices(cfg: dict) -> dict[tuple[str, str], set[str]] | None:
    """Какие устройства реально используют аудиосессии Edge и звонилки: {(exe, Render|Capture): {устройства}}."""
    import csv
    import tempfile
    svv = find_svv(cfg)
    if not svv:
        return None
    out = Path(tempfile.gettempdir()) / "maya_svv.csv"
    subprocess.run([str(svv), "/scomma", str(out)], check=False)
    for _ in range(30):
        if out.exists() and out.stat().st_size:
            break
        time.sleep(0.1)
    raw = out.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", errors="replace")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = raw.decode("mbcs", errors="replace")
    rows = list(csv.DictReader(text.splitlines()))
    if rows and "Item ID" not in rows[0]:  # другой набор колонок — диагностика недоступна
        return None
    names = {r["Item ID"]: r["Name"] for r in rows if r.get("Type") == "Device"}
    exes = {cfg["maya_browser_exe"].lower(), cfg["call_app_exe"].lower()}
    result: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        exe = Path(r.get("Process Path") or "").name.lower()
        if r.get("Type") == "Application" and exe in exes:
            dev = names.get(r["Item ID"].split("|")[0], r.get("Device Name", "?"))
            result.setdefault((exe, r["Direction"]), set()).add(dev)
    return result


def check_apps(cfg: dict) -> None:
    devs = app_devices(cfg)
    if devs is None:
        return
    edge, app = cfg["maya_browser_exe"].lower(), cfg["call_app_exe"].lower()
    name = Path(app).stem
    expect = {
        (edge, "Capture"): cfg["vm_maya_mic"], (edge, "Render"): cfg["vm_maya_out"],
        (app, "Capture"): cfg["vm_call_mic"], (app, "Render"): cfg["vm_call_out"],
    }
    labels = {(edge, "Capture"): "Maya слушает", (edge, "Render"): "Maya говорит в",
              (app, "Capture"): f"{name} слушает", (app, "Render"): f"{name} говорит в"}
    print("  Приложения (живые аудиосессии):")
    for key, want in expect.items():
        got = devs.get(key)
        if not got:
            print(f"    {labels[key]:<16} — нет активной сессии")
            continue
        # Приложения держат и старые неактивные сессии, поэтому «лишние» устройства — не ошибка,
        # а вот отсутствие нужного — ошибка.
        extra = sorted(got - {want})
        if want in got:
            line = f"    OK {labels[key]:<16} {want}"
            if extra:
                line += f"   (ещё сессии: {', '.join(extra)})"
        else:
            line = f"    !! {labels[key]:<16} {', '.join(sorted(got))}   (нужно: {want})"
        print(line)


def cmd_status(cfg: dict) -> None:
    with Voicemeeter(cfg) as vm:
        state = read_routes(vm)
        mic_dev = vm.get_str(f"Strip[{MIC}].device.name")
        a1_dev = vm.get_str("Bus[0].device.name")
    print(f"Текущий режим: {current_mode(state) or 'нестандартный'}")
    print(f"  Микрофон (HW1): {mic_dev or '— не выбран'}")
    print(f"  Динамики (A1):  {a1_dev or '— не выбраны'}")
    for s, name in STRIP_NAMES.items():
        on = [b for b in BUSES if state[s][b]]
        mute = "  [MUTE]" if state[s]["Mute"] else ""
        print(f"  {name:<16} → {', '.join(on) or '—'}{mute}")
    print("  (A1 = ты, B1 = Maya, B2 = собеседник)")
    check_apps(cfg)


def cmd_stop(cfg: dict) -> None:
    with Voicemeeter(cfg) as vm:
        vm.run("Command.Shutdown=1;")
    print("Voicemeeter закрыт, микрофон и динамики свободны.")


def cmd_dial(cfg: dict, number: str) -> None:
    clean = re.sub(r"[\s\-().]", "", number)
    if not re.fullmatch(r"\+?\d{3,15}", clean):
        sys.exit(f"Странный номер: {number}")
    with Voicemeeter(cfg) as vm:
        apply_mode(vm, "phone")
    uri = cfg["dial_uri"].format(number=clean)
    print(f"Набираю {clean}: {uri}")
    os.startfile(uri)


def cmd_open(cfg: dict) -> None:
    os.startfile("microsoft-edge:" + cfg["sesame_url"])


class Controller:
    """Текущий режим + автопереключение по звуку из приложения для звонков.

    Авто: в режиме pc появился звук из звонилки (гудки, собеседник) → phone.
    В phone/takeover тишина со всех сторон дольше hold секунд → pc.
    Режим off авто не трогает.
    """

    def __init__(self, vm: Voicemeeter, cfg: dict, auto: bool):
        self.vm, self.auto = vm, auto
        self.threshold = float(cfg.get("auto_threshold_db", -45))
        self.hold = float(cfg.get("auto_hold_seconds", 20))
        self.lock = threading.Lock()
        self.mode = current_mode(read_routes(vm)) or "pc"
        self.last_activity = time.monotonic()

    def set(self, mode: str, reason: str = "") -> None:
        with self.lock:
            apply_mode(self.vm, mode)
            self.mode = mode
            self.last_activity = time.monotonic()
        if reason:
            print(f"  ↳ {reason}")

    def tick(self) -> None:
        now = time.monotonic()
        if now - getattr(self, "_synced", 0) > 2:  # режим мог поменять кто-то снаружи (CLI, Voicemeeter)
            self._synced = now
            with self.lock:
                actual = current_mode(read_routes(self.vm))
                if actual and actual != self.mode:
                    self.mode, self.last_activity = actual, now
        with self.lock:
            mode = self.mode
            call = self.vm.level_db(CALL) > self.threshold
            maya = self.vm.level_db(MAYA) > self.threshold
            mic = self.vm.level_db(MIC) > self.threshold
        now = time.monotonic()
        if mode == "pc" and call:
            self.set("phone", "в звонке появился звук — Maya переключилась на звонок")
        elif mode in ("phone", "takeover"):
            if call or maya or (mode == "takeover" and mic):
                self.last_activity = now
            elif now - self.last_activity > self.hold:
                self.set("pc", f"{int(self.hold)} с тишины — звонок окончен, Maya снова слышит тебя")

    def toggle(self) -> None:
        self.set("phone" if self.mode == "pc" else "pc", "переключено вручную (Ctrl+Alt+M)")

    def takeover(self) -> None:
        self.set("phone" if self.mode == "takeover" else "takeover",
                 "Ctrl+Alt+T: " + ("разговор снова у Maya" if self.mode == "takeover" else "ты в разговоре"))


def disable_quick_edit() -> None:
    """Клик мышью в консоли Windows включает выделение (QuickEdit) и замораживает программу
    на первом же print — автопереключение зависает. Отключаем QuickEdit для этого окна."""
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT, ENABLE_EXTENDED_FLAGS = 0x40, 0x80
            k32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT) | ENABLE_EXTENDED_FLAGS)
    except Exception:
        pass


def cmd_start(cfg: dict, auto: bool = True) -> None:
    disable_quick_edit()
    try:
        import keyboard
    except ImportError:
        keyboard = None
        print("(Ctrl+Alt+M недоступна: pip install keyboard)")
    with Voicemeeter(cfg) as vm:
        ctl = Controller(vm, cfg, auto)
        if ctl.mode != "pc":
            ctl.set("pc")
        if keyboard:
            keyboard.add_hotkey("ctrl+alt+m", ctl.toggle)
            keyboard.add_hotkey("ctrl+alt+t", ctl.takeover)
            print("Ctrl+Alt+M — переключить компьютер / телефон вручную")
            print("Ctrl+Alt+T — перехват: ты говоришь с собеседником, Maya молчит (ещё раз — вернуть Maya)")
        if auto:
            print(f"Авто: звук в звонке → ТЕЛЕФОН, {int(ctl.hold)} с тишины → КОМПЬЮТЕР")
        print("Не закрывай это окно. Ctrl+C — выход.", flush=True)
        try:
            while True:
                if auto:
                    ctl.tick()
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass


def cmd_levels(cfg: dict, seconds: float) -> None:
    """Живые уровни — для диагностики: кто реально звучит."""
    with Voicemeeter(cfg) as vm:
        print("дБ:   микрофон |  звонок  |   Maya     (тишина ≈ -120, речь ≈ -30…-10)")
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            peaks = {s: -120.0 for s in (MIC, CALL, MAYA)}
            t = time.monotonic() + 1.0
            while time.monotonic() < t:
                for s in peaks:
                    peaks[s] = max(peaks[s], vm.level_db(s))
                time.sleep(0.05)
            print(f"     {peaks[MIC]:8.1f} | {peaks[CALL]:8.1f} | {peaks[MAYA]:8.1f}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="Maya Phone Bridge — любые звонки ⇄ Sesame AI (Maya)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for m in MODES:
        sub.add_parser(m, help=MODE_HELP[m])
    sub.add_parser("setup", help="разовая настройка")
    sub.add_parser("status", help="текущая маршрутизация")
    d = sub.add_parser("dial", help="режим phone + набор номера")
    d.add_argument("number")
    sub.add_parser("open", help="открыть Sesame в Edge")
    h = sub.add_parser("start", help="запуск: автопереключение компьютер/телефон, Ctrl+Alt+M, Ctrl+Alt+T")
    h.add_argument("--no-auto", action="store_true", help="без автопереключения")
    lv = sub.add_parser("levels", help="живые уровни сигнала (диагностика)")
    lv.add_argument("seconds", nargs="?", type=float, default=15)
    sub.add_parser("stop", help="закрыть Voicemeeter и освободить устройства")
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
    elif args.cmd == "start":
        cmd_start(cfg, auto=not args.no_auto)
    elif args.cmd == "levels":
        cmd_levels(cfg, args.seconds)
    elif args.cmd == "stop":
        cmd_stop(cfg)


if __name__ == "__main__":
    main()
