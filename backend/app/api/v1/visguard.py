"""VisGuard API — 角色视觉一致性（能力矩阵架构）。

端点:
    GET    /api/v1/visguard/capabilities                 — 能力发现（前端协商可用能力与默认值）
    POST   /api/v1/visguard/characters                   — 注册角色（含首张参考图）
    GET    /api/v1/visguard/characters?project_id=       — 角色列表
    DELETE /api/v1/visguard/characters/{character_id}    — 删除角色
    POST   /api/v1/visguard/characters/{character_id}/images — 追加参考图
    POST   /api/v1/visguard/similarity                   — 图片 → 相似角色
    GET    /api/v1/visguard/status                       — 服务状态
    POST   /api/v1/visguard/openai/*            — OpenAI 兼容端点（独立路由 visguard_openai.py，见兼容声明）

约定:
- 全部端点要求 JWT（get_current_user_id）；project_id 需归属当前用户（403 拒绝越权）。
- 能力矩阵全部关闭或 CLIP/faiss 依赖不可用 → 503（fail-graceful，不 crash）。
- 图片以 multipart/form-data 上传（浏览器友好），内部统一转 RGB PIL Image；
  单张大小限制 visguard_max_upload_mb，超限抛 400。
- 重计算（CLIP 编码 / FAISS 检索 / 指纹）通过线程池执行，避免阻塞事件循环。
- 业务异常统一走 core.exceptions.VisGuardError 层级（含稳定 code + status_code）。
- NSFW 检测（app.state.content_safety 启用时）在全部图片入口勾稽，不过 422。
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user_id, get_db_session_depends
from app.config import settings
from app.models.project import Project
from app.services.visguard import get_visguard_service, reset_visguard_service  # noqa: F401 - 供管理端调用
from app.services.visguard.character_bank import CharacterNotFoundError
from app.services.visguard.core.capabilities import get_capabilities
from app.services.visguard.core.exceptions import (
    InvalidImageError,
    VisGuardError,
)
from app.services.visguard.image_utils import base64_to_image, bytes_to_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/v1/visguard', tags=['visguard'])


# =============================================================================
# 依赖辅助
# =============================================================================

def _service_or_503():
    """获取服务单例；未启用时抛 503。"""
    service = get_visguard_service()
    if service is None:
        raise HTTPException(status_code=503, detail='VisGuard 未启用（能力矩阵全部关闭）')
    return service


def _map_visguard_error(e: VisGuardError) -> HTTPException:
    """VisGuard 统一异常 → HTTP（稳定 status_code + code: detail 透传）。"""
    return HTTPException(status_code=e.status_code, detail=str(e))


async def _owned_project(
    project_id: str,
    db: AsyncSession,
    user_id: str,
) -> Project:
    """校验项目存在且归属当前用户，否则抛 404/403。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='项目不存在')
    if project.user_id != user_id:
        raise HTTPException(status_code=403, detail='无权访问该项目')
    return project


def _read_image(file: UploadFile):
    """读取上传文件并按约定转为 RGB PIL Image。

    大小限制（visguard_max_upload_mb）在解码前拦截，避免大文件解码浪费内存。
    非法图片 / 超限统一抛 InvalidImageError（400）。
    """
    data = file.file.read()
    max_bytes = getattr(settings, 'visguard_max_upload_mb', 10) * 1024 * 1024
    if len(data) > max_bytes:
        raise InvalidImageError(
            f'图片超过大小限制（{getattr(settings, "visguard_max_upload_mb", 10)}MB）'
        )
    try:
        return bytes_to_image(data)
    except ValueError as e:
        raise InvalidImageError(str(e)) from e


async def _run_sync(fn, *args):
    """把 CPU 密集的同步调用放到线程池，避免阻塞事件循环。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


def _similarity_payload(bank, img, top_k: int, threshold: float | None) -> dict:
    """相似度计算（线程池内执行）：指纹 + FAISS 检索合并为一次调用。"""
    return {
        'query_hash': bank.image_fingerprint(img),
        'results': bank.find_similar(img, top_k=top_k, threshold=threshold),
    }


async def _safety_check(request: Request, image) -> None:
    """NSFW 检测勾稽：app.state.content_safety 未注册或未启用时放行（P0-3）。"""
    safety = getattr(request.app.state, 'content_safety', None)
    if safety is None:
        return
    result = await safety.check_image(image)
    if not result.passed:
        raise HTTPException(status_code=422, detail=result.reason)


# =============================================================================
# GET /capabilities — 能力发现
# =============================================================================

@router.get('/capabilities')
async def capabilities(
    user_id: str = Depends(get_current_user_id),
):
    """能力发现：前端 / 其他服务据此协商可用能力与默认参数。

    与 /status 的区别：本端点返回纯能力声明（不含运行时状态），
    便于前端在初始化时一次性拉取并缓存。
    """
    return {
        'enabled': get_visguard_service() is not None,
        'capabilities': get_capabilities(),
        'defaults': {
            'threshold': settings.visguard_default_threshold,
            'max_upload_mb': getattr(settings, 'visguard_max_upload_mb', 10),
            'preprocess_resolution': getattr(settings, 'visguard_preprocess_resolution', 1024),
            'ui_preset': getattr(settings, 'visguard_ui_preset', 'local'),
        },
    }


# =============================================================================
# POST /characters — 注册角色
# =============================================================================

@router.post('/characters', status_code=201)
async def register_character(
    request: Request,
    project_id: str = Form(...),
    name: str = Form(..., min_length=1, max_length=100),
    image: UploadFile = File(...),
    description: str = Form(''),
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """注册角色（含首张参考图）→ 编码入库。"""
    await _owned_project(project_id, db, user_id)
    service = _service_or_503()
    bank = service.get_bank(project_id)

    try:
        img = _read_image(image)
        await _safety_check(request, img)
        character = await _run_sync(
            bank.register,
            name.strip(),
            img,
            description.strip(),
        )
    except VisGuardError as e:
        raise _map_visguard_error(e) from e
    return {'project_id': project_id, 'character': character}


# =============================================================================
# GET /characters — 角色列表
# =============================================================================

@router.get('/characters')
async def list_characters(
    project_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """项目角色列表（按创建顺序，附向量条数）。"""
    await _owned_project(project_id, db, user_id)
    service = _service_or_503()
    bank = service.get_bank(project_id)
    try:
        characters = await _run_sync(bank.list_characters)
    except VisGuardError as e:
        raise _map_visguard_error(e) from e
    return {'project_id': project_id, 'characters': characters}


# =============================================================================
# DELETE /characters/{character_id} — 删除角色
# =============================================================================

@router.delete('/characters/{character_id}')
async def delete_character(
    character_id: str,
    project_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """删除角色（向量 + 图片 + 元数据）。"""
    await _owned_project(project_id, db, user_id)
    service = _service_or_503()
    bank = service.get_bank(project_id)
    try:
        deleted = await _run_sync(bank.delete, character_id)
    except VisGuardError as e:
        raise _map_visguard_error(e) from e
    if not deleted:
        raise HTTPException(status_code=404, detail='角色不存在')
    return {'deleted': True, 'character_id': character_id}


# =============================================================================
# POST /characters/{character_id}/images — 追加参考图
# =============================================================================

@router.post('/characters/{character_id}/images', status_code=201)
async def add_character_image(
    character_id: str,
    request: Request,
    project_id: str = Form(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """给角色追加参考图（同一角色多向量，提高检索鲁棒性）。"""
    await _owned_project(project_id, db, user_id)
    service = _service_or_503()
    bank = service.get_bank(project_id)

    try:
        img = _read_image(image)
        await _safety_check(request, img)
        result = await _run_sync(bank.add_image, character_id, img)
    except CharacterNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except VisGuardError as e:
        raise _map_visguard_error(e) from e
    return {'project_id': project_id, **result}


# =============================================================================
# GET /characters/{character_id}/images — 角色参考图列表
# =============================================================================

@router.get('/characters/{character_id}/images')
async def list_character_images(
    character_id: str,
    project_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """列出角色的所有参考图 ID（供前端加载图片列表）。"""
    await _owned_project(project_id, db, user_id)
    service = _service_or_503()
    bank = service.get_bank(project_id)
    try:
        image_ids = await _run_sync(bank.list_images, character_id)
    except CharacterNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except VisGuardError as e:
        raise _map_visguard_error(e) from e
    return {
        'project_id': project_id,
        'character_id': character_id,
        'image_ids': image_ids,
    }


# =============================================================================
# GET /characters/{character_id}/images/{image_id}/file — 参考图文件
# =============================================================================

@router.get('/characters/{character_id}/images/{image_id}/file')
async def get_character_image_file(
    character_id: str,
    image_id: str,
    project_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """返回参考图 PNG 文件（JWT 鉴权后可直接用于 <img src>）。"""
    await _owned_project(project_id, db, user_id)
    service = _service_or_503()
    bank = service.get_bank(project_id)
    try:
        img_path = await _run_sync(bank.get_image_path, character_id, image_id)
    except CharacterNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except VisGuardError as e:
        raise _map_visguard_error(e) from e
    return FileResponse(img_path, media_type='image/png')


# =============================================================================
# POST /similarity — 图片 → 相似角色
# =============================================================================

@router.post('/similarity')
async def similarity(
    request: Request,
    project_id: str = Form(...),
    image: UploadFile = File(...),
    top_k: int = Form(5, ge=1, le=50),
    threshold: float | None = Form(None, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """比对图片与项目角色库，返回按分数降序的相似角色。"""
    await _owned_project(project_id, db, user_id)
    service = _service_or_503()
    bank = service.get_bank(project_id)

    try:
        img = _read_image(image)
        await _safety_check(request, img)
        payload = await _run_sync(
            _similarity_payload, bank, img, top_k, threshold,
        )
    except VisGuardError as e:
        raise _map_visguard_error(e) from e
    return {'project_id': project_id, **payload}


# =============================================================================
# GET /status — 服务状态
# =============================================================================

@router.get('/status')
async def status(
    user_id: str = Depends(get_current_user_id),
):
    """VisGuard 服务状态（供前端/管理面板展示）。能力矩阵关闭时不报错，返回 enabled=false。"""
    service = get_visguard_service()
    if service is None:
        return {
            'enabled': False,
            'reason': '能力矩阵全部关闭（visguard_*_backend=none）',
        }
    return {
        'enabled': True,
        **service.status(),
    }


# =============================================================================
# 兼容入口：BASE64 方式注册（可选，两端一致）
# =============================================================================

@router.post('/characters/base64', status_code=201, include_in_schema=False)
async def register_character_base64(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db_session_depends),
    user_id: str = Depends(get_current_user_id),
):
    """以 JSON(base64 data URI) 注册角色（兼容非浏览器客户端），隐藏端点。"""
    project_id = payload.get('project_id')
    name = payload.get('name', '').strip()
    image_data = payload.get('image', '')
    if not project_id or not name or not image_data:
        raise HTTPException(status_code=400, detail='project_id / name / image 必填')
    await _owned_project(project_id, db, user_id)
    service = _service_or_503()
    bank = service.get_bank(project_id)

    try:
        # 大小限制与 multipart 路径一致（base64 膨胀 ~33%，按解码后字节校验））
        raw = base64_to_image(image_data)
        await _safety_check(request, raw)
        img_bytes = raw.tobytes()
        max_bytes = getattr(settings, 'visguard_max_upload_mb', 10) * 1024 * 1024
        if len(img_bytes) > max_bytes:
            raise InvalidImageError(
                f'图片超过大小限制（{getattr(settings, "visguard_max_upload_mb", 10)}MB）'
            )
        character = await _run_sync(
            bank.register,
            name,
            raw,
            payload.get('description', '').strip(),
        )
    except CharacterNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except VisGuardError as e:
        raise _map_visguard_error(e) from e
    return {'project_id': project_id, 'character': character}