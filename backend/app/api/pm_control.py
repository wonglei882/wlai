"""PM-Agent 控制接口（Kill Switch / Pause / Resume）

演进：
- T1.4 升级：状态持久化从「文件」升级为「Redis + 内存」双层结构。
  - 主：Redis（支持多 worker / 分布式部署，跨进程一致性）
  - 备：文件（Redis 不可用时二次降级，保证 Kill Switch 不丢）
  - 内存：运行时缓存，避免每次 is_killed() 都查 Redis
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from pathlib import Path
import json
import logging
import threading

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/pm-control', tags=['PM Control'])

# 文件状态路径（Redis 不可用时的二次降级）
_STATE_FILE = Path(__file__).resolve().parent.parent / 'data' / 'pm_control_state.json'
_REDIS_KEY = 'pm:control_state'  # Redis 主存储 key
_REDIS_TTL = 7 * 24 * 3600  # 7 天 TTL（足够覆盖运维窗口）
_file_lock = threading.Lock()
_redis = None  # 延迟初始化（避免 import 时 Redis 不可用报警）


def _get_redis():
    """延迟获取 redis_client 单例（首次调用时初始化）。"""
    global _redis
    if _redis is None:
        try:
            from app.utils.redis_client import redis_client

            _redis = redis_client
        except Exception as e:
            logger.warning('Redis 客户端初始化失败，将使用文件降级: %s', e)
            _redis = False  # 标记为不可用
    return _redis if _redis is not False else None


def _ensure_data_dir() -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _default_state() -> dict:
    return {'kill_switch': False, 'pause_switch': False, 'killed_at': None, 'paused_at': None}


def _load_state_from_redis() -> dict:
    """从 Redis 加载状态"""
    client = _get_redis()
    if client is None:
        return _default_state()
    try:
        raw = client.get(_REDIS_KEY)
        if raw:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return {
                'kill_switch': data.get('kill_switch', False),
                'pause_switch': data.get('pause_switch', False),
                'killed_at': data.get('killed_at'),
                'paused_at': data.get('paused_at'),
            }
    except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
        logger.warning('PM control state in Redis corrupted, falling back: %s', e)
    return _default_state()


def _load_state_from_file() -> dict:
    """从文件加载状态（Redis 不可用时的二次降级）"""
    try:
        if _STATE_FILE.exists():
            raw = _STATE_FILE.read_text(encoding='utf-8')
            data = json.loads(raw)
            return {
                'kill_switch': data.get('kill_switch', False),
                'pause_switch': data.get('pause_switch', False),
                'killed_at': data.get('killed_at'),
                'paused_at': data.get('paused_at'),
            }
    except (json.JSONDecodeError, OSError, KeyError) as e:
        logger.warning('PM control state file corrupted, resetting: %s', e)
    return _default_state()


def _save_state_to_redis(state: dict) -> None:
    """将状态持久化到 Redis"""
    client = _get_redis()
    if client is None:
        return
    try:
        client.set(_REDIS_KEY, json.dumps(state, ensure_ascii=False), ttl=_REDIS_TTL)
    except Exception as e:
        logger.error('Failed to persist PM control state to Redis: %s', e)


def _save_state_to_file(state: dict) -> None:
    """将状态持久化到文件（二次降级）"""
    _ensure_data_dir()
    try:
        with _file_lock:
            _STATE_FILE.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
    except OSError as e:
        logger.error('Failed to persist PM control state to file: %s', e)


class PMControlState:
    """PM-Agent 全局控制状态（Redis + 文件双层持久化）

    状态读写策略：
    - 读：内存 → Redis → 文件（优先级递减）
    - 写：内存 + Redis + 文件（三处同步）
    - 进程重启：Redis 中状态仍在 → 自动恢复
    - Redis 故障：降级到文件，仍能恢复
    """

    _instance = None
    _kill_switch = False
    _pause_switch = False
    _killed_at = None
    _paused_at = None
    _initialized = False

    @classmethod
    def init_from_file(cls) -> None:
        """启动时从持久化存储恢复状态（应在 register_pm_agent 中调用）

        读取顺序：Redis → 文件（Redis 不可用或没数据时降级到文件）
        """
        if cls._initialized:
            return
        # 优先 Redis
        state = _load_state_from_redis()
        # Redis 没数据或全 False → 试文件（可能是首次迁移到 Redis）
        if not state['kill_switch'] and not state['pause_switch']:
            file_state = _load_state_from_file()
            if file_state['kill_switch'] or file_state['pause_switch']:
                state = file_state
                # 把文件中的状态同步到 Redis（首次迁移）
                _save_state_to_redis(state)
                logger.info('[PM] 把文件中的 Kill/Pause 状态同步到 Redis')

        cls._kill_switch = state['kill_switch']
        cls._pause_switch = state['pause_switch']
        cls._killed_at = state['killed_at']
        cls._paused_at = state['paused_at']
        cls._initialized = True
        if cls._kill_switch:
            logger.critical('[PM] Restored Kill Switch state — PM-Agent remains killed')
        elif cls._pause_switch:
            logger.warning('[PM] Restored Pause state — PM-Agent remains paused')

    @classmethod
    def _persist(cls) -> None:
        """将当前内存状态持久化到 Redis + 文件（双写）"""
        state = {
            'kill_switch': cls._kill_switch,
            'pause_switch': cls._pause_switch,
            'killed_at': cls._killed_at.isoformat() if cls._killed_at else None,
            'paused_at': cls._paused_at.isoformat() if cls._paused_at else None,
        }
        _save_state_to_redis(state)
        _save_state_to_file(state)  # 二次降级备份

    @classmethod
    def is_killed(cls) -> bool:
        return cls._kill_switch

    @classmethod
    def is_paused(cls) -> bool:
        return cls._pause_switch

    @classmethod
    def kill(cls) -> dict:
        cls._kill_switch = True
        cls._pause_switch = False
        cls._killed_at = datetime.now()
        cls._paused_at = None
        cls._persist()
        logger.critical('PM-Agent Kill Switch 已触发')
        return {'status': 'killed', 'killed_at': cls._killed_at.isoformat()}

    @classmethod
    def pause(cls) -> dict:
        cls._pause_switch = True
        cls._paused_at = datetime.now()
        cls._persist()
        logger.warning('PM-Agent 已暂停')
        return {'status': 'paused', 'paused_at': cls._paused_at.isoformat()}

    @classmethod
    def resume(cls) -> dict:
        cls._kill_switch = False
        cls._pause_switch = False
        cls._killed_at = None
        cls._paused_at = None
        cls._persist()
        logger.info('PM-Agent 已恢复运行')
        return {'status': 'resumed'}

    @classmethod
    def get_status(cls) -> dict:
        return {
            'killed': cls._kill_switch,
            'paused': cls._pause_switch,
            'killed_at': cls._killed_at.isoformat() if cls._killed_at else None,
            'paused_at': cls._paused_at.isoformat() if cls._paused_at else None,
        }


class PMStatusResponse(BaseModel):
    """PM-Agent 状态响应"""

    killed: bool
    paused: bool
    killed_at: str | None = None
    paused_at: str | None = None


class PMControlResponse(BaseModel):
    """PM-Agent 控制响应"""

    status: str
    killed_at: str | None = None
    paused_at: str | None = None


@router.post('/kill', response_model=PMControlResponse)
async def kill_pm_agent():
    """紧急中止 PM-Agent。状态持久化到 Redis + 文件，进程重启后仍保持 killed。"""
    if PMControlState.is_killed():
        raise HTTPException(status_code=400, detail='PM-Agent 已经处于 killed 状态')

    result = PMControlState.kill()
    return PMControlResponse(**result)


@router.post('/pause', response_model=PMControlResponse)
async def pause_pm_agent():
    """暂停 PM-Agent。状态持久化到 Redis + 文件。"""
    if PMControlState.is_killed():
        raise HTTPException(status_code=400, detail='PM-Agent 已被 killed，无法暂停')

    if PMControlState.is_paused():
        raise HTTPException(status_code=400, detail='PM-Agent 已经处于 paused 状态')

    result = PMControlState.pause()
    return PMControlResponse(**result)


@router.post('/resume', response_model=PMControlResponse)
async def resume_pm_agent():
    """恢复 PM-Agent。状态从 Redis + 文件清除。"""
    if not PMControlState.is_killed() and not PMControlState.is_paused():
        raise HTTPException(status_code=400, detail='PM-Agent 未处于 killed 或 paused 状态')

    result = PMControlState.resume()
    return PMControlResponse(**result)


@router.get('/status')
async def get_pm_status():
    """获取 PM-Agent 当前状态 + 健康检查 + 熔断器状态。"""
    status = PMControlState.get_status()

    # 附加健康检查信息
    health = {}
    try:
        from app.services.pm.pm_api import get_pm_health

        health = get_pm_health()
    except Exception as e:
        logger.warning('[PM-Control] 健康检查获取失败: %s', e)
        health = {'error': '健康检查不可用'}

    return {**status, 'health': health}
