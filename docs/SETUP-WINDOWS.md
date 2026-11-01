# Настройка на Windows

Один раз, примерно 15 минут. Нужны: Windows 10/11, Zoom с подключённым Zoom Phone,
Microsoft Edge, Python 3.10+.

## 1. Voicemeeter Banana

1. Скачай с официального сайта: <https://vb-audio.com/Voicemeeter/banana.htm>
   (бесплатно, donationware).
2. Запусти установщик **от имени администратора**, подтверди установку драйвера.
3. **Перезагрузи компьютер** — без этого виртуальные устройства не появятся.
4. После перезагрузки в «Звук» появятся устройства:
   - воспроизведение: `Voicemeeter Input`, `Voicemeeter AUX Input`
   - запись: `Voicemeeter Out B1`, `Voicemeeter Out B2`

   В старых версиях они называются `VoiceMeeter Output` / `VoiceMeeter Aux Output` —
   тогда поправь имена в `config.json`.
5. **Не меняй устройства по умолчанию в Windows** — динамики и микрофон остаются прежними.
   Виртуальные устройства назначаются только Zoom и Edge.
   Установщик Voicemeeter 2.1 сам делает устройством по умолчанию `Voicemeeter VAIO3 Input`,
   и системный звук пропадает. Верни свои динамики: **Параметры → Система → Звук → Вывод**.

Через winget установка ставится одной командой:
`winget install --id VB-Audio.Voicemeeter.Banana --exact`.

## 2. Скрипт

```powershell
git clone https://github.com/magomed-esendirov/Sesame-AI-Phone-Calls.git
cd Sesame-AI-Phone-Calls
copy config.example.json config.json
python maya.py setup
```

`setup` подключает микрофон и динамики к Voicemeeter, подписывает полосы и включает
режим `off`.

Чтобы `setup` сам назначил устройства для Edge и Zoom, положи
[SoundVolumeView](https://www.nirsoft.net/utils/sound_volume_view.html) (NirSoft, бесплатно)
в папку `tools\` и запусти `setup` ещё раз. Без него — шаги 3 и 4 вручную.

## 3. Edge — браузер для Maya

1. **Параметры → Система → Звук → Микшер громкости** (открой Edge, чтобы он появился в списке):
   - Microsoft Edge → **Устройство вывода**: `Voicemeeter AUX Input`
   - Microsoft Edge → **Устройство ввода**: `Voicemeeter Out B1`
2. Открой Sesame в Edge (`python maya.py open`), войди, разреши доступ к микрофону.
3. Если сайт даёт выбрать микрофон — выбери `Voicemeeter Out B1`.
   В Edge: `edge://settings/content/microphone`.

Основной браузер (Chrome) остаётся как был.

## 4. Zoom

**Настройки → Звук**:

| Параметр | Значение |
|---|---|
| Динамик | `Voicemeeter Input` |
| Микрофон | `Voicemeeter Out B2` |
| Автоматически регулировать громкость микрофона | **выключить** |
| Подавление фонового шума | **Низкий** (иначе Zoom может «резать» голос Maya) |
| Отдельное устройство для звонка (рингтон) | твои динамики — чтобы звонок не уходил Maya |

## 5. Проверка без звонка

1. `python maya.py brief` — скажи Maya «привет». Она должна ответить, ты её слышишь.
2. `python maya.py call` — Maya больше не слышит тебя (микрофон отключён от всех линий).
3. В Zoom: **Настройки → Звук → Проверить микрофон** — пока Maya говорит, индикатор должен двигаться.
4. Позвони на свой мобильный: `python maya.py dial +1XXXXXXXXXX`. Ответь и поговори с Maya.

## Если что-то не так

| Симптом | Что проверить |
|---|---|
| Maya не слышит абонента | Динамик Zoom = `Voicemeeter Input`; микрофон Edge = `Voicemeeter Out B1`; `python maya.py status` → у Zoom есть `B1` |
| Абонент не слышит Maya | Вывод Edge = `Voicemeeter AUX Input`; микрофон Zoom = `Voicemeeter Out B2`; у Maya есть `B2` |
| Ты ничего не слышишь | В Voicemeeter у A1 выбраны твои динамики (`python maya.py setup`) |
| Пропал весь системный звук | Устройство вывода Windows по умолчанию — снова твои динамики, не `Voicemeeter VAIO3 Input` |
| Треск / заикание | Voicemeeter → Menu → System Settings → увеличь Buffering WDM до 1024 |
| Maya перебивает или молчит | Подними громкость полосы ZOOM в Voicemeeter (фейдер +3…+6 dB) — телефонный звук тихий |
| Эхо у абонента | Убедись, что твой микрофон не идёт в B2 в режиме `call` (`status`) |
| `zoomphonecall://` не открывает Zoom | Zoom → Настройки → Телефон → сделай Zoom приложением по умолчанию для звонков |
