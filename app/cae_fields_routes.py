"""Read-only postprocessing routes: no solver or device execution capability."""
from pathlib import Path
import json
import threading
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from utils.cae_field_view import load_fields, section, render_png
from utils.paths import resolve_path

router = APIRouter()
_POSTPROCESS_ADMISSION = threading.BoundedSemaphore(1)


def _data(path):
    root = resolve_path('.')
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return load_fields(candidate, [root / 'artifacts', root / 'runs'])
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/cae/results')
def results_page():
    return FileResponse(resolve_path('web/templates/cae_fields.html'), media_type='text/html')


@router.get('/api/cae/fields')
def fields(path: str):
    return _data(path)


@router.get('/api/cae/fields/metadata')
def fields_metadata(path: str):
    data = _data(path)
    return {'status': data.get('status'), 'frames': [
        {'frame_index': i, 'step': frame.get('step'), 'time': frame.get('time'),
         'fields': {name: {k: field.get(k) for k in ('units', 'components', 'association')}
                    for name, field in frame['fields'].items()}}
        for i, frame in enumerate(data.get('frames', []))]}


@router.get('/api/cae/fields/section')
def fields_section(path: str, field: str, frame: int = 0, axis: str = 'z', position: float = 0, component: int = -1, scale: float = 0):
    if not _POSTPROCESS_ADMISSION.acquire(blocking=False):
        raise HTTPException(429, 'Field postprocessing busy; retry after current request')
    try:
        return section(_data(path), axis=axis, position=position, frame=frame, field=field, component=component, scale=scale)
    except ImportError as exc:
        raise HTTPException(503, 'Install requirements-cae-viewer.txt for volume postprocessing') from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        _POSTPROCESS_ADMISSION.release()


@router.get('/api/cae/fields/render')
def fields_render(path: str, field: str, frame: int = 0, component: int = -1, scale: float = 0, edges: bool = False,
                  minimum: float | None = None, maximum: float | None = None, transparent: bool = False,
                  axis: str = 'none', position: float = 0, camera: str | None = None, overlay: bool = False):
    if not _POSTPROCESS_ADMISSION.acquire(blocking=False):
        raise HTTPException(429, 'Field postprocessing busy; retry after current request')
    try:
        png = render_png(_data(path), frame=frame, field=field, component=component, scale=scale, edges=edges,
                         minimum=minimum, maximum=maximum, transparent=transparent, axis=axis, position=position,
                         camera=json.loads(camera) if camera else None, overlay=overlay)
        return Response(png, media_type='image/png', headers={'Content-Disposition': 'attachment; filename="analysis-contour-4k.png"',
                        'Cache-Control': 'private, max-age=3600'})
    except ImportError as exc:
        raise HTTPException(503, 'Install requirements-cae-viewer.txt for volume postprocessing') from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        _POSTPROCESS_ADMISSION.release()
