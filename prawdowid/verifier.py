from prawdowid.contract import CheckResult, Status


async def verify(text: str) -> CheckResult:
    """The one entry point every channel calls. Stub until the pipeline exists."""
    return CheckResult(
        status=Status.CANNOT_CHECK,
        message="Weryfikacja nie jest jeszcze podłączona, więc nie możemy teraz ocenić tej treści.",
    )
