def enforce_safe_mode(safe_mode: bool) -> None:
    if not safe_mode:
        raise RuntimeError("SAFE_MODE=false jest zablokowany. Program służy wyłącznie do analizy i alertów.")
