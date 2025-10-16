# Chat Max (Tkinter client)

Simple Tkinter-based chat client that sends messages to a Flask server endpoint and displays replies.

This client keeps a short persistent conversation history in `chat_history.json` and includes that history as plain-text context inside the single `message` field that is posted to the server, currently an entirely local one.

## Files

- `chatmax.py` - Main Tkinter GUI client. Sends requests to `http://192.168.123.128:5003/chat` by default.
- `chat_history.json` - Created next to `chatmax.py` after the first message; stores recent messages (user and AI) as JSON.