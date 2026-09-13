"""WebSocket 实时推送 — 报告 + 任务进度。

端点:
    WS /ws/reports/{project_id}  — 实时推送一致性报告
    WS /ws/tasks/{task_id}       — 实时推送任务进度
"""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=['websocket'])

# 连接管理器
_connections: dict[str, list[WebSocket]] = {}


async def _broadcast(channel: str, data: dict[str, Any]):
    """向指定频道的所有连接广播消息。"""
    conns = _connections.get(channel, [])
    dead = []
    for ws in conns:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.remove(ws)


async def broadcast_report(project_id: str, report: dict):
    """广播一致性报告（供内部调用）。"""
    await _broadcast(f'reports:{project_id}', {'type': 'report', 'data': report})


async def broadcast_task_progress(task_id: str, progress: float, status: str, result: dict | None = None):
    """广播任务进度（供内部调用）。"""
    await _broadcast(f'tasks:{task_id}', {
        'type': 'task_progress',
        'data': {'task_id': task_id, 'progress': progress, 'status': status, 'result': result},
    })


@router.websocket('/ws/reports/{project_id}')
async def ws_reports(websocket: WebSocket, project_id: str):
    """实时推送一致性报告。"""
    await websocket.accept()
    channel = f'reports:{project_id}'
    if channel not in _connections:
        _connections[channel] = []
    _connections[channel].append(websocket)
    logger.info('WS 连接: %s (活跃: %d)', channel, len(_connections[channel]))
    try:
        while True:
            # 保持连接，接收客户端心跳
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_json({'type': 'pong'})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if channel in _connections and websocket in _connections[channel]:
            _connections[channel].remove(websocket)
        logger.info('WS 断开: %s', channel)


@router.websocket('/ws/tasks/{task_id}')
async def ws_task_progress(websocket: WebSocket, task_id: str):
    """实时推送任务进度。"""
    await websocket.accept()
    channel = f'tasks:{task_id}'
    if channel not in _connections:
        _connections[channel] = []
    _connections[channel].append(websocket)
    logger.info('WS 连接: %s', channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_json({'type': 'pong'})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if channel in _connections and websocket in _connections[channel]:
            _connections[channel].remove(websocket)
        logger.info('WS 断开: %s', channel)
