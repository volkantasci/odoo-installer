"""Adapters: the only code that touches the world (DEVELOPMENT.md §3.1).

Each adapter is used by core/ through a Protocol defined next to it, so tests replace
adapters with fakes and no test ever runs git, docker, or network calls.
"""
