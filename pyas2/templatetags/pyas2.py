from django import template

register = template.Library()


@register.filter
def readfilefield(field):
    """Template filter for rendering data from a file field"""
    try:
        with field.open("r") as f:
            return f.read()
    except FileNotFoundError as e:
        return "File not found."
