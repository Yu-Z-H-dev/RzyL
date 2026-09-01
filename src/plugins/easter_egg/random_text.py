import random
from pathlib import Path


def load_random_line(filename: str) -> str | None:
    try:
        text_file = Path(__file__).parent / filename
        with open(text_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return None
        while True:
            line = random.choice(lines).strip()
            if line and not line.startswith("//"):
                return line
    except Exception:
        return None


def load_random_text() -> str | None:
    if random.random() < 0.4:
        sentence = load_random_line("sentences.txt")
        if sentence:
            return f"\n{sentence}"
    return None
