"""Fixed deployment diagnostics: never include configuration or driver errors."""


class DeploymentError(RuntimeError):
    def __init__(self, code="deployment_unavailable"):
        self.code = code
        super().__init__(code)
