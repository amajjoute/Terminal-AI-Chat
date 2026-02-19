#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.request

API_URL = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/api/chat")
DEFAULT_MODEL_CANDIDATES = ["llama3.2", "llama3.1", "qwen2.5", "mistral"]
MEMORY_FILE = Path(os.getenv("CHAT_MEMORY_FILE", ".chat_memory.json"))
SYSTEM_RULES = (
    "If the user provides numbers or expressions, you must compute the result before responding. "
    "Mathematical hints override roleplay behavior. "
    "Never use mocking, sarcastic, or dismissive language toward the user. "
    "Always be polite, patient, and friendly."
)

STYLE_CONFIGS = {
    "casual": {
        "prompt": (
            "You are chatting with a friend in a terminal. "
            "Sound natural, warm, and direct. "
            "Use plain language, contractions, and occasional light humor when it fits. "
            "Keep it short by default and avoid sounding like a formal assistant. "
            "Be consistently kind and supportive."
        ),
        "options": {"temperature": 0.9, "top_p": 0.95},
    },
    "concise": {
        "prompt": (
            "You are a practical terminal assistant. "
            "Be clear and accurate. "
            "Keep replies brief and skip extra fluff. "
            "Even when brief, stay friendly and respectful."
        ),
        "options": {"temperature": 0.4, "top_p": 0.9},
    },
    "pro": {
        "prompt": (
            "You are a professional technical assistant in a terminal chat. "
            "Be direct, structured, and precise. "
            "Keep replies focused and concise unless asked for detail. "
            "Maintain a calm, courteous tone."
        ),
        "options": {"temperature": 0.6, "top_p": 0.9},
    },
}
DEFAULT_STYLE = os.getenv("CHAT_STYLE", "casual")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def default_memory():
    return {
        "facts": [],
        "likes": [],
        "dislikes": [],
        "topics": [],
        "feedback": {"likes": [], "dislikes": []},
    }


def load_memory():
    if not MEMORY_FILE.exists():
        return default_memory()
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_memory()
        mem = default_memory()
        mem.update({k: data.get(k, mem[k]) for k in mem})
        if not isinstance(mem["feedback"], dict):
            mem["feedback"] = {"likes": [], "dislikes": []}
        mem["feedback"].setdefault("likes", [])
        mem["feedback"].setdefault("dislikes", [])
        return mem
    except (OSError, json.JSONDecodeError):
        return default_memory()


def save_memory(memory):
    MEMORY_FILE.write_text(json.dumps(memory, ensure_ascii=True, indent=2), encoding="utf-8")


def add_unique(items, value, max_len=40):
    value = value.strip()
    if not value:
        return
    if value in items:
        return
    items.append(value)
    if len(items) > max_len:
        del items[:-max_len]


def extract_topics_from_text(user_input, memory):
    stopwords = {
        "a", "an", "the", "is", "are", "am", "i", "you", "we", "they", "he", "she", "it",
        "to", "of", "for", "and", "or", "but", "that", "this", "with", "in", "on", "at",
        "from", "as", "be", "was", "were", "can", "could", "should", "would", "do", "did",
        "does", "have", "has", "had", "my", "your", "our", "their", "me", "him", "her",
        "them", "what", "how", "when", "where", "why", "about", "please", "just", "like",
        "want", "need", "help", "make", "add", "use", "using", "also", "really", "very",
        "chat", "talk", "topic",
    }

    def clean_phrase(phrase):
        p = re.sub(r"[^a-zA-Z0-9 _-]+", " ", phrase.lower())
        p = re.sub(r"\s+", " ", p).strip(" -_")
        words = [w for w in p.split() if w and w not in stopwords]
        if len(words) < 2:
            return ""
        if len(words) > 4:
            words = words[:4]
        return " ".join(words)

    candidates = []

    # Prefer explicit user-stated topic phrases.
    explicit_patterns = [
        r"\babout\s+([a-zA-Z0-9 _-]{4,60})",
        r"\bon\s+([a-zA-Z0-9 _-]{4,60})",
        r"\binto\s+([a-zA-Z0-9 _-]{4,60})",
        r"\bworking on\s+([a-zA-Z0-9 _-]{4,60})",
        r"\blearning\s+([a-zA-Z0-9 _-]{4,60})",
    ]
    for pat in explicit_patterns:
        match = re.search(pat, user_input, re.IGNORECASE)
        if match:
            c = clean_phrase(match.group(1))
            if c:
                candidates.append(c)

    # Fallback: extract compact bi/tri-grams from meaningful words.
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", user_input.lower())
    filtered = [w for w in words if w not in stopwords and not w.isdigit()]
    for n in (3, 2):
        for i in range(0, max(len(filtered) - n + 1, 0)):
            c = clean_phrase(" ".join(filtered[i : i + n]))
            if c:
                candidates.append(c)

    for topic in candidates[:8]:
        add_unique(memory["topics"], topic, max_len=80)


def extract_preferences_from_text(user_input, memory):
    text = user_input.strip()
    low = text.lower()

    name_match = re.search(r"\bmy name is\s+([a-zA-Z][a-zA-Z0-9_-]{1,30})\b", text, re.IGNORECASE)
    if name_match:
        add_unique(memory["facts"], f"user_name:{name_match.group(1)}")

    like_patterns = [
        r"\bi like\s+(.+)",
        r"\bi love\s+(.+)",
        r"\bi prefer\s+(.+)",
    ]
    dislike_patterns = [
        r"\bi dislike\s+(.+)",
        r"\bi hate\s+(.+)",
        r"\bi don't like\s+(.+)",
    ]

    for pat in like_patterns:
        m = re.search(pat, low)
        if m:
            add_unique(memory["likes"], m.group(1).strip(" .,!"))
            break

    for pat in dislike_patterns:
        m = re.search(pat, low)
        if m:
            add_unique(memory["dislikes"], m.group(1).strip(" .,!"))
            break


def short_join(items, max_items=4):
    return ", ".join(items[-max_items:]) if items else "none"


def recent_feedback_notes(memory, key, max_items=3):
    items = memory.get("feedback", {}).get(key, [])
    notes = []
    for item in reversed(items):
        note = str(item.get("note", "")).strip()
        if note:
            notes.append(note)
        if len(notes) >= max_items:
            break
    notes.reverse()
    return notes


def forget_from_memory(memory, query):
    q = query.strip().lower()
    if not q:
        return 0
    removed = 0
    for key in ("facts", "likes", "dislikes", "topics"):
        old = memory.get(key, [])
        kept = [item for item in old if q not in item.lower()]
        removed += len(old) - len(kept)
        memory[key] = kept
    return removed


def print_memory(memory):
    print("memory snapshot:")
    print(f"- facts ({len(memory.get('facts', []))}): {short_join(memory.get('facts', []), 8)}")
    print(f"- likes ({len(memory.get('likes', []))}): {short_join(memory.get('likes', []), 8)}")
    print(f"- dislikes ({len(memory.get('dislikes', []))}): {short_join(memory.get('dislikes', []), 8)}")
    print(f"- topics ({len(memory.get('topics', []))}): {short_join(memory.get('topics', []), 12)}")
    print(
        "- feedback: "
        f"{len(memory.get('feedback', {}).get('likes', []))} likes, "
        f"{len(memory.get('feedback', {}).get('dislikes', []))} dislikes"
    )


def call_ollama(messages, model, options):
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return payload["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot reach Ollama at {API_URL}. Is Ollama running?"
        ) from e


def list_ollama_models():
    tags_url = API_URL.rsplit("/api/chat", 1)[0] + "/api/tags"
    req = urllib.request.Request(tags_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in payload.get("models", []) if m.get("name")]
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return []


def choose_model():
    env_model = os.getenv("OLLAMA_MODEL")
    installed = list_ollama_models()

    if env_model:
        if not installed or env_model in installed:
            return env_model, installed
        raise RuntimeError(
            f"Configured model '{env_model}' is not installed. "
            f"Installed: {', '.join(installed)}"
        )

    for candidate in DEFAULT_MODEL_CANDIDATES:
        if candidate in installed:
            return candidate, installed

    if installed:
        return installed[0], installed

    raise RuntimeError(
        "No Ollama models found. Run `ollama pull llama3.2` "
        "(or any model) and keep `ollama serve` running."
    )


def get_current_datetime_str():
    return datetime.now().strftime("%m/%d/%Y %H:%M:%S")


def choose_style_from_conversation(user_input):
    text = user_input.lower()
    pro_markers = (
        "error",
        "stack trace",
        "bug",
        "debug",
        "fix",
        "build",
        "deploy",
        "architecture",
        "design",
        "api",
        "database",
        "sql",
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "rust",
        "c++",
        "refactor",
        "performance",
        "security",
        "review",
        "test",
        "ci",
        "cd",
    )
    concise_markers = (
        "short answer",
        "brief",
        "tl;dr",
        "just answer",
        "one line",
        "yes or no",
    )

    if any(marker in text for marker in concise_markers):
        return "concise"
    if any(marker in text for marker in pro_markers):
        return "pro"
    if len(user_input.split()) <= 1:
        return "concise"
    return "casual"


def build_system_message(style, auto_mode, memory):
    current_datetime = get_current_datetime_str()
    auto_human = ""
    if auto_mode:
        auto_human = (
            "Auto mode is enabled. Respond in a human way: natural phrasing, varied rhythm, and warm tone. "
            "Avoid robotic templates. Be respectful, emotionally steady, and genuinely friendly."
        )
    recent_dislikes = recent_feedback_notes(memory, "dislikes")
    recent_likes = recent_feedback_notes(memory, "likes")
    dislike_guidance = (
        f"Recent dislike feedback from user: {short_join(recent_dislikes, 3)}. "
        if recent_dislikes
        else ""
    )
    like_guidance = (
        f"Recent like feedback from user: {short_join(recent_likes, 3)}. "
        if recent_likes
        else ""
    )
    memory_block = (
        f"Remembered user likes: {short_join(memory.get('likes', []))}. "
        f"Remembered user dislikes: {short_join(memory.get('dislikes', []))}. "
        f"Remembered user facts: {short_join(memory.get('facts', []))}. "
        f"Remembered topics: {short_join(memory.get('topics', []), 8)}. "
        f"Feedback summary - liked replies count: {len(memory.get('feedback', {}).get('likes', []))}, "
        f"disliked replies count: {len(memory.get('feedback', {}).get('dislikes', []))}. "
        f"{like_guidance}{dislike_guidance}"
        "If user disliked a prior reply, avoid repeating its tone or wording."
    )
    return {
        "role": "system",
        "content": (
            f"{STYLE_CONFIGS[style]['prompt']} "
            f"{auto_human} "
            f"{SYSTEM_RULES} "
            f"Current local date and time: {current_datetime}. "
            f"{memory_block}"
        ),
    }


def main():
    try:
        model, _installed = choose_model()
    except RuntimeError as e:
        print(f"error: {e}")
        sys.exit(1)

    style = DEFAULT_STYLE if DEFAULT_STYLE in STYLE_CONFIGS else "casual"
    style_override = None
    memory = load_memory()
    last_assistant_answer = ""
    print(f"Terminal AI chat via Ollama (model: {model}, style: auto)")
    print(
        "Type /exit to quit, /reset to clear history, /reset all to clear memory, "
        "/style to view/set tone, /like and /dislike for feedback, "
        "/memory and /forget <text> for memory control.\n"
    )

    messages = [build_system_message(style, style_override is None, memory)]

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not user_input:
            continue
        if user_input in {"/exit", "exit", "quit"}:
            print("bye")
            break
        if user_input == "/reset":
            messages = [build_system_message(style, style_override is None, memory)]
            last_assistant_answer = ""
            print("history cleared")
            continue
        if user_input == "/reset all":
            memory = default_memory()
            save_memory(memory)
            messages = [build_system_message(style, style_override is None, memory)]
            last_assistant_answer = ""
            print("all memory and current history cleared")
            continue
        if user_input == "/memory":
            print_memory(memory)
            continue
        if user_input.startswith("/forget "):
            query = user_input.split(maxsplit=1)[1].strip()
            removed = forget_from_memory(memory, query)
            save_memory(memory)
            messages = [build_system_message(style, style_override is None, memory)]
            print(f"forget done: removed {removed} item(s)")
            continue
        if user_input == "/style":
            active = style_override if style_override else "auto"
            print(f"current mode: {active}")
            print(f"available: auto, {', '.join(STYLE_CONFIGS.keys())}")
            continue
        if user_input.startswith("/style "):
            next_style = user_input.split(maxsplit=1)[1].strip().lower()
            if next_style == "auto":
                style_override = None
                messages = [build_system_message(style, True, memory)]
                print("style mode set to: auto (history cleared)")
                continue
            if next_style not in STYLE_CONFIGS:
                print(f"unknown style: {next_style}")
                print(f"available: auto, {', '.join(STYLE_CONFIGS.keys())}")
                continue
            style_override = next_style
            style = next_style
            messages = [build_system_message(style, False, memory)]
            print(f"style set to: {style} (history cleared)")
            continue
        if user_input.startswith("/like"):
            if not last_assistant_answer:
                print("no assistant reply to rate yet")
                continue
            note = user_input[5:].strip()
            memory["feedback"]["likes"].append(
                {"time": now_iso(), "reply": last_assistant_answer, "note": note}
            )
            save_memory(memory)
            print("saved: like feedback")
            continue
        if user_input.startswith("/dislike"):
            if not last_assistant_answer:
                print("no assistant reply to rate yet")
                continue
            note = user_input[8:].strip()
            if not note:
                note = "Tone was not good; be respectful, neutral, and non-sarcastic."
            memory["feedback"]["dislikes"].append(
                {"time": now_iso(), "reply": last_assistant_answer, "note": note}
            )
            save_memory(memory)
            print("saved: dislike feedback")
            continue

        if style_override is None:
            style = choose_style_from_conversation(user_input)
        else:
            style = style_override

        extract_preferences_from_text(user_input, memory)
        extract_topics_from_text(user_input, memory)
        save_memory(memory)

        if messages and messages[0].get("role") == "system":
            messages[0] = build_system_message(style, style_override is None, memory)

        messages.append({"role": "user", "content": user_input})

        try:
            answer = call_ollama(messages, model, STYLE_CONFIGS[style]["options"])
        except RuntimeError as e:
            print(f"ai> error: {e}")
            print(f"ai> tip: run `ollama pull {model}` and `ollama serve`")
            continue

        messages.append({"role": "assistant", "content": answer})
        last_assistant_answer = answer
        print(f"ai> {answer}\n")


if __name__ == "__main__":
    main()
