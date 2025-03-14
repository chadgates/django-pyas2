from django.apps import AppConfig


class Pyas2Config(AppConfig):
    """App config for the pyas2 app."""

    name = "pyas2"
    verbose_name = "pyAS2 File Transfer Server"

    def ready(self):
        # Import signal handlers to register them
        import pyas2.signals
