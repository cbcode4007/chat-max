# Chat Max

Simple Tkinter-based chat client that sends messages to a Flask server endpoint and displays replies.

This client keeps a short persistent conversation history in `chat_history.json` and includes that history as plain-text context inside the single `message` field that is posted to the server, currently an entirely local one.

## Files

- `chatmax.py` - Main Tkinter GUI client. Sends POST requests to Flask servers, formatted in specific ways.
- `chat_history.json` - Created next to `chatmax.py` after the first message; stores recent messages (user and AI) as JSON.

## Features

- Persistent conversation history: the client stores recent messages to `chat_history.json` and includes that history as context when sending to the server (keeps compatibility with servers that accept a single `message` payload or a `messages` array depending on the script variant).
- Non-blocking network requests: sends to the server are performed in a background thread so the UI stays responsive. While awaiting a reply the UI inserts an "AI is typing..." placeholder and disables send controls.
- Preferences file: the client reads `preferences.txt` next to the script and appends its contents as an extra system instruction when sending requests. If `preferences.txt` is missing, the client can auto-generate a concise preferences file by asking the server to extract user preferences from recent user messages and saving the result.
- Preference extraction and merging: when new preferences are extracted they are merged into `preferences.txt` by canonical keys (text before " is "), replacing or appending lines as necessary and truncating to a configurable maximum size.
- Personality UI: a separate "Personality" window (menu → Personality → Configure...) exposes discrete sliders for Friendliness (0-3), Professionalism (0-2), Profanity (0-2), Age, and Gender (0-2). The slider settings are converted into a short system instruction appended to the outgoing request so you can control the assistant's voice and behavior.
- Adaptive Personality window: the Personality window no longer uses a fixed geometry; it is resizable and the summary text will reflow as you resize the window.
- File menu: New/Save/Load conversation support (JSON format). "New" clears the current conversation display and in-memory history. Save/Load operate on the serialized conversation format and preserve timestamps when present.
- Read-only chat area and safe rendering: the chat display is a read-only ScrolledText widget. Programmatic updates enable/disable the widget safely, and the chat is re-rendered from the in-memory history for robustness.
- Timestamps: history entries include timestamps and saved conversations are backward-compatible with older two-element (role, message) entries.