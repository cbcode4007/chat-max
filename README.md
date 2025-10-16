# Chat Max (Tkinter client)

Simple Tkinter-based chat client that sends messages to a Flask server endpoint and displays replies.

This client keeps a short persistent conversation history in `chat_history.json` and includes that history as plain-text context inside the single `message` field that is posted to the server, currently an entirely local one.

## Files

- `chatmax.py` - Main Tkinter GUI client. Sends POST requests to Flask servers, formatted in a specific way.
- `chat_history.json` - Created next to `chatmax.py` after the first message; stores recent messages (user and AI) as JSON.