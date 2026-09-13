"""镜头状态机 — 7 状态流转控制。

状态流转:
    pending_script → pending_image → pending_review_image
    → pending_video → pending_voice → pending_composite → completed

审核驳回时:
    pending_review_image → pending_image（重新出图）
"""

import logging

logger = logging.getLogger(__name__)

# 合法状态列表
STATES = [
    'pending_script',       # 待写剧本
    'pending_image',        # 待出图
    'pending_review_image', # 待审核首帧
    'pending_video',        # 待生成视频
    'pending_voice',        # 待配音
    'pending_composite',    # 待合成
    'completed',            # 完成
]

# 状态标签（中文）
STATE_LABELS = {
    'pending_script': '待写剧本',
    'pending_image': '待出图',
    'pending_review_image': '待审核首帧',
    'pending_video': '待生成视频',
    'pending_voice': '待配音',
    'pending_composite': '待合成',
    'completed': '已完成',
}

# 合法转换表
TRANSITIONS = {
    'pending_script': ['pending_image'],
    'pending_image': ['pending_review_image'],
    'pending_review_image': ['pending_video', 'pending_image'],  # 驳回→重新出图
    'pending_video': ['pending_voice'],
    'pending_voice': ['pending_composite'],
    'pending_composite': ['completed'],
    'completed': [],  # 终态
}


class ShotStateMachine:
    """镜头状态机 — 控制镜头状态流转。"""

    @staticmethod
    def can_transition(current: str, target: str) -> bool:
        """检查是否可以从 current 转换到 target。"""
        if current not in TRANSITIONS:
            return False
        return target in TRANSITIONS[current]

    @staticmethod
    def transition(current: str, target: str) -> str:
        """执行状态转换，返回新状态。

        Raises:
            ValueError: 非法转换
        """
        if not ShotStateMachine.can_transition(current, target):
            allowed = TRANSITIONS.get(current, [])
            raise ValueError(
                f'非法状态转换: {current} → {target}，'
                f'允许: {allowed}'
            )
        logger.info('镜头状态: %s → %s', STATE_LABELS.get(current, current), STATE_LABELS.get(target, target))
        return target

    @staticmethod
    def get_label(state: str) -> str:
        """获取状态中文标签。"""
        return STATE_LABELS.get(state, state)

    @staticmethod
    def is_terminal(state: str) -> bool:
        """是否为终态。"""
        return state == 'completed'

    @staticmethod
    def get_allowed_transitions(current: str) -> list[str]:
        """获取当前状态允许转换到的目标状态列表。"""
        return TRANSITIONS.get(current, [])
