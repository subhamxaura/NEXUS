"""Small clean helper that depends on risky (exercises the dependency graph)."""
from risky import tiny


def greet(name):
    if not name:
        return "hello"
    return f"hello {name} {tiny()}"


print(greet("world"))
