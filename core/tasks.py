# core/tasks.py

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    """Estado estándar de una tarea de Ron."""  

    QUEUED = "queued"        # Creada, esperando empezar
    RUNNING = "running"      # En ejecución
    COMPLETED = "completed"  # Terminó OK
    FAILED = "failed"        # Terminó con error
    CANCELLED = "cancelled"  # Cancelada por el usuario o el sistema


@dataclass
class RonTask:
    """
    Representa una tarea de Ron, tanto del lado servidor como local (Electron).

    Esta clase es el modelo de verdad. El frontend recibe este mismo contenido
    serializado a JSON (via .to_dict()).
    """

    id: str                      # ID único de la tarea (p.ej. uuid4)
    user: str                    # Nombre de usuario / perfil de Ron
    kind: str                    # Tipo: "analyze_file", "local:analyze_file", "diagnose_system", etc.
    description: str             # Descripción human-readable para mostrar en la UI

    source: str = "local"        # "local" (Electron/cliente) o "server" (tarea en backend)
    status: TaskStatus = TaskStatus.QUEUED
    progress: int = 0            # 0–100 (aprox; puede quedarse en 0 o 100 si no hay progreso granular)

    params: Dict[str, Any] = field(default_factory=dict)  # Parámetros de la tarea (ruta de archivo, etc.)
    result_summary: Optional[str] = None                  # Resumen pensado para el usuario
    error: Optional[str] = None                           # Mensaje de error en caso de FAILED

    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)

    def touch(self) -> None:
        """Actualiza la marca de tiempo de updated_at."""
        self.updated_at = _now_utc()

    def set_status(self, status: TaskStatus, *, progress: Optional[int] = None) -> None:
        """Actualiza el estado (y opcionalmente el progreso)."""
        self.status = status
        if progress is not None:
            self.progress = max(0, min(100, int(progress)))
        self.touch()

    def set_result(self, summary: Optional[str] = None, error: Optional[str] = None) -> None:
        """
        Define el resumen final y/o el error. Normalmente se usará al finalizar la tarea.
        """
        if summary is not None:
            self.result_summary = summary
        if error is not None:
            self.error = error
        self.touch()

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializa la tarea a un dict listo para convertir a JSON.

        Importante: las fechas se exportan como ISO 8601 en UTC,
        para que el frontend siempre reciba strings.
        """
        data = asdict(self)
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RonTask":
        """
        Crea una RonTask desde un dict (por si en algún momento
        guardamos tareas en disco o en memoria persistente).
        """
        status_raw = payload.get("status", TaskStatus.QUEUED)
        status = (
            status_raw
            if isinstance(status_raw, TaskStatus)
            else TaskStatus(status_raw)
        )

        created_at_raw = payload.get("created_at")
        updated_at_raw = payload.get("updated_at")

        def _parse_dt(v: Any) -> datetime:
            if isinstance(v, datetime):
                return v
            if isinstance(v, str):
                try:
                    # fromisoformat soporta offset tipo +00:00
                    return datetime.fromisoformat(v)
                except Exception:
                    return _now_utc()
            return _now_utc()

        return cls(
            id=payload["id"],
            user=payload.get("user", "default"),
            kind=payload.get("kind", "generic"),
            description=payload.get("description", ""),
            source=payload.get("source", "local"),
            status=status,
            progress=int(payload.get("progress", 0)),
            params=dict(payload.get("params", {})),
            result_summary=payload.get("result_summary"),
            error=payload.get("error"),
            created_at=_parse_dt(created_at_raw),
            updated_at=_parse_dt(updated_at_raw),
        )
