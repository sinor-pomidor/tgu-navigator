"""Роутер проверки работоспособности приложения."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Возвращает статус приложения.

    Используется для мониторинга и быстрой проверки запуска сервиса.
    """
    return {"status": "ok"}
