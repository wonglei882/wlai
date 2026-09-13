"""分镜生成器（规则版 MVP） — 将小说/故事文本转换为分镜表。

MVP 规则:
1. 按段落/标点分句
2. 每句 → 1 个镜头（3-5秒）
3. 提取角色名 → 匹配角色卡
4. 台词截断到 15 字
5. 最后一镜加钩子标记
"""

import re
import uuid
from typing import Any

import logging

logger = logging.getLogger(__name__)

# 台词最大字数
MAX_DIALOGUE_CHARS = 15

# 默认镜头时长（秒）
DEFAULT_SHOT_DURATION = 4.0

# 分句标点
_SENTENCE_ENDINGS = re.compile(r'[。！？!?\n]+')

# 景别推断关键词
_SCENE_TYPE_KEYWORDS = {
    '特写': ['眼睛', '手指', '嘴唇', '泪', '手', '表情', '嘴角'],
    '近景': ['说', '笑', '哭', '看', '望', '脸', '头'],
    '中景': ['走', '站', '坐', '转身', '挥手', '拥抱'],
    '全景': ['房间', '大厅', '教室', '办公室', '广场'],
    '远景': ['山', '海', '城市', '天空', '远方', '地平线'],
}

# 镜头运动推断关键词
_CAMERA_MOVEMENT_KEYWORDS = {
    '推': ['靠近', '走近', '聚焦', '凝视'],
    '拉': ['远离', '退后', '全景', '俯瞰'],
    '摇': ['环顾', '四周', '扫视'],
    '跟': ['追', '跟随', '跑'],
    '固定': [],  # 默认
}


class StoryboardGenerator:
    """分镜生成器 — 将文本转换为分镜表（规则版 MVP）。"""

    async def generate_from_text(
        self,
        text: str,
        project_id: str,
        user_id: str,
        episode_id: str | None = None,
        character_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """从文本生成分镜表。

        Args:
            text: 原始小说/故事文本
            project_id: 项目 ID
            user_id: 用户 ID
            episode_id: 集数 ID（可选）
            character_names: 已知角色名列表（用于匹配）

        Returns:
            {'storyboard': dict, 'shots': list[dict]}
        """
        if not text or not text.strip():
            return {'storyboard': {}, 'shots': []}

        char_names = character_names or []

        # 1. 分句
        sentences = self._split_sentences(text)

        # 2. 每句 → 1 个镜头
        shots: list[dict[str, Any]] = []
        for idx, sentence in enumerate(sentences, start=1):
            sentence = sentence.strip()
            if not sentence:
                continue

            shot = self._sentence_to_shot(idx, sentence, char_names)
            shots.append(shot)

        # 3. 最后一镜加钩子标记
        if shots:
            shots[-1]['metadata'] = shots[-1].get('metadata', {})
            shots[-1]['metadata']['is_hook'] = True

        # 4. 组装分镜表
        storyboard = {
            'id': str(uuid.uuid4()),
            'project_id': project_id,
            'episode_id': episode_id,
            'title': f'分镜表 - {len(shots)} 个镜头',
            'source_text': text[:500],  # 截断存储
            'shot_count': len(shots),
            'status': 'draft',
        }

        logger.info(
            '[StoryboardGen] 生成 %d 个镜头 (project=%s)',
            len(shots), project_id,
        )

        return {'storyboard': storyboard, 'shots': shots}

    # -------------------------------------------------------------------------
    # 内部方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """按标点分句，过滤空句。"""
        raw = _SENTENCE_ENDINGS.split(text)
        return [s.strip() for s in raw if s and s.strip()]

    @staticmethod
    def _sentence_to_shot(
        shot_number: int,
        sentence: str,
        character_names: list[str],
    ) -> dict[str, Any]:
        """将单句转换为镜头数据。"""
        # 提取台词（引号内内容）
        dialogue = ''
        dialogue_match = re.search(r'[""「」『』](.+?)[""「」『』]', sentence)
        if dialogue_match:
            dialogue = dialogue_match.group(1)
            if len(dialogue) > MAX_DIALOGUE_CHARS:
                dialogue = dialogue[:MAX_DIALOGUE_CHARS]

        # 推断景别
        scene_type = _infer_scene_type(sentence)

        # 推断镜头运动
        camera_movement = _infer_camera_movement(sentence)

        # 匹配角色
        matched_chars = [
            name for name in character_names
            if name in sentence
        ]

        # 角色动作（简单提取）
        character_action = _extract_action(sentence, matched_chars)

        return {
            'shot_number': shot_number,
            'duration': DEFAULT_SHOT_DURATION,
            'scene_type': scene_type,
            'visual_description': sentence,
            'character_action': character_action,
            'dialogue': dialogue,
            'sound_effect': '',
            'camera_movement': camera_movement,
            'status': 'pending_script',
            'matched_characters': matched_chars,
            'metadata': {},
        }


def _infer_scene_type(sentence: str) -> str:
    """从句子内容推断景别。"""
    for scene_type, keywords in _SCENE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in sentence:
                return scene_type
    return '中景'  # 默认


def _infer_camera_movement(sentence: str) -> str:
    """从句子内容推断镜头运动。"""
    for movement, keywords in _CAMERA_MOVEMENT_KEYWORDS.items():
        for kw in keywords:
            if kw in sentence:
                return movement
    return '固定'  # 默认


def _extract_action(sentence: str, character_names: list[str]) -> str:
    """简单提取角色动作。"""
    # 移除台词部分
    clean = re.sub(r'[""「」『』].+?[""「」『』]', '', sentence).strip()
    if not clean:
        return ''

    # 如果有角色名，提取角色名后的动作描述
    for name in character_names:
        if name in clean:
            # 取角色名后面的部分
            idx = clean.index(name) + len(name)
            action = clean[idx:].strip().lstrip('，,。、')
            return action[:50] if action else ''

    return clean[:50]
