class PricingDomainError(ValueError):
    """A pricing input cannot be evaluated under the documented economic rules."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")
