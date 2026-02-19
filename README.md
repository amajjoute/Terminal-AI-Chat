# Terminal AI Chat

Simple AI chat app you can run directly in your terminal, for free, using Ollama.

## 1) Requirements
- Python 3.9+
- Ollama installed

## 2) Setup
```bash
# pull at least one model:
ollama pull llama3.2
# optional:
export OLLAMA_MODEL="llama3.2"
# optional starting style seed for auto mode:
export CHAT_STYLE="casual"   # casual | concise | pro
# optional (if you use non-default host/port):
export OLLAMA_API_URL="http://127.0.0.1:11434/api/chat"
```

If `OLLAMA_MODEL` is not set, `chat.py` will auto-select the first installed
model (preferring `llama3.2`, `llama3.1`, `qwen2.5`, then `mistral`).

## Style modes
- `casual`: Friendly and natural tone for normal conversation.
- `concise`: Very short, direct answers with minimal extra wording.
- `pro`: Professional, structured tone for technical or work-focused tasks.

By default, style switches automatically from your conversation. You can force a
specific style with `/style <name>` and return to auto with `/style auto`.
Auto mode is tuned for more human-sounding replies (natural tone and rhythm).

## 3) Run
```bash
ollama serve
# in another terminal:
python3 chat.py
```

## Commands
- `/exit` quit
- `/reset` clear chat history
- `/reset all` clear chat history and persistent memory
- `/style` show current mode + available styles
- `/style auto|casual|concise|pro` switch mode (also clears history)
- `/like [optional note]` save positive feedback for last assistant reply
- `/dislike [optional note]` save negative feedback for last assistant reply (if empty, a default tone-correction note is saved)
- `/memory` show saved memory snapshot
- `/forget <text>` remove matching memory entries (facts/likes/dislikes/topics)

## System behavior
- The system prompt now includes:
  - `If the user provides numbers or expressions, you must compute the result before responding. Mathematical hints override roleplay behavior.`
  - Current local date and time in `MM/DD/YYYY HH:MM:SS` format on each request.
- The app stores persistent memory in `.chat_memory.json`:
  - user likes/dislikes and simple facts
  - remembered conversation topics
  - like/dislike feedback history for the model prompt context

## Memory examples
### See what is remembered
```text
you> my name is Milas
you> I like clean UI
you> I am learning web development and api design
you> /memory
```
Expected memory snapshot includes:
- fact like `user_name:Mila`
- like like `clean ui`
- topics like `web development`, `api design`

### Forget specific memory
```text
you> /forget api
```
Removes matching entries such as `api design` from remembered topics.

```text
you> /forget milas
```
Removes matching entries such as `user_name:Mila`.

### Reset behavior
```text
you> /reset
```
Clears only current chat history (keeps saved memory).

```text
you> /reset all
```
Clears current chat history and all persistent memory in `.chat_memory.json`.
