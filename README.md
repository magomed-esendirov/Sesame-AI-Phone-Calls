# Sesame AI Phone Calls

Put **Maya** from [Sesame AI](https://www.sesame.com/) on real calls from a Windows PC: Zoom,
Microsoft Teams, WhatsApp, Telegram, Skype, SIP softphones — any app that uses the computer's
audio.

You dial a number, the other person picks up, and Maya runs the conversation. She hears the
caller and answers in one of the most realistic AI voices available today. Through Sesame's
connectors she already knows the context of your work: email, files, calendar. You hear both
sides and can jump into the call at any moment.

> **What was tested.** Zoom Phone on Windows 11: an outbound call to a mobile number, with
> Maya handling the whole conversation. Other apps work the same way (you only pick the audio
> devices in them), but I haven't tested them myself.

## How it works

Neither Sesame nor calling apps expose an audio API, so they are connected at the audio-device
level through the virtual mixer **Voicemeeter Banana**. A small Python script, `maya.py`,
drives it via the official Voicemeeter Remote API.

```
                ┌──────────────────── Voicemeeter Banana ────────────────────┐
  Call app ────►│ "Voicemeeter Input"  ──► CALL strip ───► B1 ──┐            │
  (Zoom, Teams, │                                    └──► A1 ──┼──► your    │
   WhatsApp…)   │                                              │    speakers │
  Maya / Edge ─►│ "Voicemeeter AUX Input" ► MAYA strip ──► B2 ─┼─┐  (you hear│
  (speaker)     │                                    └──► A1 ──┘ │   both    │
                │                                                │   sides)  │
  Your mic ────►│ HW1 ──► MIC strip ──► B1 (+B2 on takeover)     │           │
                └───────────────────────────────┬────────────────┼───────────┘
                                                │                │
                         "Voicemeeter Out B1" ◄─┘                └─► "Voicemeeter Out B2"
                          = Maya's mic (Edge)                        = call app's mic
```

Maya hears only the caller and the caller hears only Maya, so there is no feedback loop or echo.
Maya lives in a **separate browser (Edge)**: audio routing only affects that browser, so YouTube
in your main Chrome never leaks into a call.

## Usage

There are two modes, and they switch **automatically**:

| Mode | When | Who hears whom |
|---|---|---|
| **PC** | no call | Maya hears you — talk to her as usual |
| **Phone** | the call app produces sound (ringback, caller) | Maya hears the caller and speaks into the call; your mic is off, you listen to both sides |

After the call (20 seconds of silence) it goes back to **PC**. Manual switch: `Ctrl+Alt+M`.

**Takeover — `Ctrl+Alt+T`.** Jump into the call yourself: the caller hears you, Maya goes quiet
but keeps listening, so she keeps the context. Press `Ctrl+Alt+T` again to hand the call back
to Maya.

## Quick start

1. Install Voicemeeter Banana and set up Edge and your call app — step by step in
   **[docs/SETUP-WINDOWS.md](docs/SETUP-WINDOWS.md)** (about 15 minutes, once).
2. One-time setup:
   ```powershell
   python maya.py setup
   ```
3. Every time: open Maya in Edge (`python maya.py open`) and run **`start.bat`**
   (double-click). Keep its window open — it switches the modes.
4. Tell Maya who you're calling and why, then dial — as usual in your app, or:
   ```powershell
   python maya.py dial +15551234567
   ```

Other commands: `python maya.py status` (current mode and which devices Edge and the call app
actually use), `python maya.py levels` (who is producing sound right now), `python maya.py stop`
(close Voicemeeter and release the microphone), `python maya.py --help`.

> Keep the call app **out of the Edge window where Maya runs**: Windows assigns audio devices
> per program, so they would hear each other in a loop.

> The script's console messages are in Russian for now; the commands and the setup above are
> all you need.

## Call apps

In any app, pick two devices: **speaker `Voicemeeter Input`** and **microphone
`Voicemeeter Out B2`**.

| App | Where | Tested |
|---|---|---|
| Zoom / Zoom Phone | Settings → Audio | ✅ |
| Microsoft Teams | Settings → Devices | — |
| Telegram Desktop | Settings → Calls | — |
| WhatsApp, Skype, SIP softphones, others | in the app's settings, or if it has none — Windows Settings → System → Sound → Volume mixer → the app | — |

`dial` opens the number using the `dial_uri` template from `config.json`:
`zoomphonecall://{number}` for Zoom Phone (default) or `tel:{number}` for whatever app Windows
uses for phone links. The call app's exe name (`call_app_exe`) is only used by `status`.

## Cost

- **Voicemeeter Banana** — free (donationware).
- **Maya in Sesame** — free at the time of writing.
- **Telephony** — the only real cost: your Zoom Phone plan or another provider. Calls inside
  WhatsApp, Telegram or Teams cost nothing extra.

So you end up with an essentially free phone assistant with one of the most realistic voices
around and access to all of Sesame's connectors.

## Ideas (not implemented)

These are hypotheses that build on this setup. I haven't built any of them.

- **Maya dials by herself.** A custom connector (MCP server) plus a skill for Maya with one tool,
  `dial(number)`, that runs `python maya.py dial …` on the PC. Say "Maya, call John" and she
  places the call.
- **Calling from a contact list.** Connect Maya to your contacts (Google Contacts, a CRM,
  a spreadsheet) through the same MCP: "call John from the client list" → look up the number →
  `dial`.
- **Inbound calls.** An automation on an incoming call that launches Sesame and `start`, answers
  the call (Zoom auto-answer or a hotkey), and lets Maya greet the caller.
- **A "phone assistant" skill.** Memory and instructions for Maya: introduce herself as an AI
  assistant, take messages, book meetings in the calendar, send a call summary to email, Notion
  or a CRM afterwards.
- **Connecting and transferring.** Transfer the call to a colleague or add them to the
  conversation (transfer and conference in Zoom Phone) — Maya as a receptionist.
- **No drivers.** A browser extension that pipes audio tab-to-tab, if the call app also runs in
  a browser.
- **24/7 server mode.** A Linux server, a SIP number (Twilio, Telnyx) and a headless browser with
  Maya: calls on command from your phone and inbound calls without your PC switched on.

Given Sesame's connectors to email, documents, databases and memory, the list of scenarios is
practically open-ended.

## Laws and ethics

Maya's voice is nearly indistinguishable from a human's, so:

- **Maya should introduce herself as an AI assistant** at the start of a call — put that in her
  instructions.
- In the US, calls using an artificial voice fall under the TCPA (FCC ruling, 2024): calls to
  mobile numbers need the person's prior consent, marketing calls need written consent.
  Automated calling of strangers is off limits.
- If you record calls, follow recording-consent laws (many US states require all parties to
  consent).
- Check the terms of service of Sesame and of your calling provider.

## Configuration

Copy `config.example.json` to `config.json` and adjust: microphone and speaker names, the browser
for Maya, Sesame's URL, the call app and the dialing template. `config.json` is git-ignored.

## License

[MIT](LICENSE)
