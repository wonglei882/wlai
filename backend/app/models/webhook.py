"""Webhook 配置模型 — 外部系统回调注册。

当一致性 Agent 检测到问题或完成修复时，通过 Webhook 通知外部系统。
支持 HMAC-SHA256 签名验证。
"""

import uuid

from sqlalchemy import Column, String, Text, DateTime, Boolean
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.sql import func

from app.models.base import Base


class WebhookConfig(Base):
    """Webhook 回调配置。"""

    __tablename__ = 'webhook_configs'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)

    # 回调 URL
    url = Column(String(2000), nullable=False, comment='回调 URL')

    # 订阅事件类型（JSON 数组，兼容 SQLite/PostgreSQL）
    # ['issue_detected', 'fix_completed', 'report_ready', 'scan_finished']
    events = Column(
        JSON,
        nullable=False,
        default=list,
        comment='订阅事件列表',
    )

    # HMAC 签名密钥（外部系统用于验证请求来源）
    secret = Column(String(200), nullable=False, comment='HMAC-SHA256 签名密钥')

    # 状态
    is_active = Column(Boolean, default=True, comment='是否启用')
    last_triggered_at = Column(DateTime, comment='最近一次触发时间')
    last_status = Column(String(20), comment='最近一次回调状态: success/failed/timeout')

    # 元数据
    description = Column(Text, comment='描述（可选）')
    metadata_json = Column(JSON, default=dict, comment='扩展元数据')

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<WebhookConfig(id={self.id}, url={self.url[:50]})>'
