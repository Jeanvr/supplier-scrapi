from __future__ import annotations

from importlib import import_module


def load_provider(provider_key: str):
    normalized = (provider_key or "").strip().lower()
    if not normalized:
        raise ValueError("provider vacío")

    try:
        module = import_module(f"src.providers.{normalized}.provider")
    except ModuleNotFoundError as exc:
        raise ValueError(f"Proveedor no soportado: {normalized}") from exc

    provider = getattr(module, "PROVIDER", None)
    if provider is None:
        raise ValueError(f"El proveedor {normalized} no define PROVIDER")

    return provider