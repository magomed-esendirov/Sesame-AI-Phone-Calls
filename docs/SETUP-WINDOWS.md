# Windows setup

Once, about 15 minutes. You need Windows 10/11, Microsoft Edge, Python 3.10+ and an app for
calls (tested with Zoom Phone).

## 1. Voicemeeter Banana

1. Download it from the official site: <https://vb-audio.com/Voicemeeter/banana.htm>
   (free, donationware), or with winget:
   `winget install --id VB-Audio.Voicemeeter.Banana --exact`.
2. Run the installer **as administrator** and confirm the driver installation.
3. **Restart the computer** if the virtual devices don't show up.
4. In Sound settings you should now have:
   - playback: `Voicemeeter Input`, `Voicemeeter AUX Input`
   - recording: `Voicemeeter Out B1`, `Voicemeeter Out B2`

   Older versions call them `VoiceMeeter Output` / `VoiceMeeter Aux Output` — then fix the
   names in `config.json`.
5. **Don't change the Windows default devices** — your speakers and mic stay the default.
   Virtual devices are assigned only to Edge and the call app.
   The Voicemeeter 2.1 installer makes `Voicemeeter VAIO3 Input` the default output, which
   silences all system sound. Switch back to your speakers:
   **Settings → System → Sound → Output**.

## 2. The script

```powershell
git clone https://github.com/magomed-esendirov/Sesame-AI-Phone-Calls.git
cd Sesame-AI-Phone-Calls
copy config.example.json config.json
python maya.py setup
pip install keyboard
```

`setup` connects your mic and speakers to Voicemeeter (in shared MME mode, so other apps keep
the mic), labels the strips and turns on the **PC** mode.

To let `setup` assign Edge's devices automatically, put
[SoundVolumeView](https://www.nirsoft.net/utils/sound_volume_view.html) (NirSoft, free) into
the `tools\` folder and run `setup` again. Without it, do step 3.1 by hand.

## 3. Edge — Maya's browser

1. **Settings → System → Sound → Volume mixer** (open Edge first so it shows up):
   - Microsoft Edge → **Output device**: `Voicemeeter AUX Input`
   - Microsoft Edge → **Input device**: `Voicemeeter Out B1`
2. In Edge open `edge://settings/content/microphone` and choose `Voicemeeter Out B1`
   (there may be two entries — "Default" and the device itself; either works).
3. Open Sesame in Edge (`python maya.py open`), sign in, allow the microphone.
   If the Sesame tab was already open, reload it (F5) so it picks up the new devices.

Your main browser (Chrome) stays as it is.

## 4. The call app

Pick **speaker `Voicemeeter Input`** and **microphone `Voicemeeter Out B2`**. For Zoom,
**Settings → Audio**:

| Setting | Value |
|---|---|
| Speaker | `Voicemeeter Input` |
| Microphone | `Voicemeeter Out B2` |
| Automatically adjust microphone volume | **off** |
| Background noise suppression | **Low** (otherwise Zoom may cut Maya's voice) |
| Separate device for ringtone | your speakers — so the ringtone doesn't go to Maya |

For other apps see the table in the [README](../README.md#call-apps).

## 5. Test without a call

1. Run `start.bat` — **PC** mode. Say "hi" to Maya: she should answer.
2. `Ctrl+Alt+M` — **Phone** mode: Maya no longer hears you. `Ctrl+Alt+M` again — back.
3. `python maya.py status` — every app line should start with `OK`.
4. Call your own mobile and answer it **in another room** (otherwise the phone picks up your
   voice from the room and you get an echo). As soon as the call app produces sound, the mode
   switches to **Phone** by itself.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Maya doesn't hear you | Is `start.bat` running? `python maya.py status` → mode `pc`. Don't click into its console window on older versions — Windows freezes the program while text is selected |
| Maya doesn't hear anyone at all | `status` → "Maya слушает" must be `Voicemeeter Out B1`. If it isn't, set Edge's mic (step 3) and reload the Sesame tab |
| Maya doesn't hear the caller | Call app speaker = `Voicemeeter Input`; `status` → the call strip goes to `B1` in Phone mode |
| The caller hears silence | Edge output = `Voicemeeter AUX Input`; call app mic = `Voicemeeter Out B2` |
| You hear nothing | Voicemeeter A1 is your speakers (`python maya.py setup`) |
| Other apps (Claude, Telegram) lost the mic | `python maya.py setup` attaches the mic via MME (shared). To release everything right away: `python maya.py stop` |
| All system sound is gone | The Windows default output must be your speakers, not `Voicemeeter VAIO3 Input` |
| Crackling / stuttering | Voicemeeter → Menu → System Settings → raise WDM buffering to 1024 |
| Maya talks over the caller or stays silent | Raise the CALL strip fader in Voicemeeter (+3…+6 dB) — phone audio is quiet |
| `zoomphonecall://` doesn't open Zoom | Zoom → Settings → Phone → make Zoom the default calling app, or set `dial_uri` to `tel:{number}` |
