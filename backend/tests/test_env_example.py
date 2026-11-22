from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
SECRET_KEYS = {
    "GEMINI_API_KEY",
    "TURNSTILE_SECRET_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_PUBLIC_KEY",
}


def test_env_example_contains_no_secrets() -> None:
    values = dict(
        line.split("=", 1)
        for line in ENV_EXAMPLE.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    leaked = sorted(key for key in SECRET_KEYS if values.get(key, "").strip())
    assert not leaked, f".env.example must leave these blank: {leaked}"
