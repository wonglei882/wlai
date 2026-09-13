"""提示词编译器 — 根据角色卡+画风卡+分镜 → 生成出图/视频提示词。

核心逻辑:
1. 注入画风基础提示词 (style.base_prompt)
2. 注入出场角色的固定外貌描述 (char.appearance_prompt)
3. 注入镜头特定内容 (shot.visual_description + action)
4. 合并负面词 (style.negative_prompt + negative_lib + char.negative_traits)
5. 输出目标格式 (MJ/SD/即梦/可灵)
"""

from typing import Any

import logging

logger = logging.getLogger(__name__)


class PromptCompiler:
    """提示词编译器 — 将设定圣经 + 分镜编译为 AI 可用的提示词。"""

    async def compile_shot_prompt(
        self,
        shot: dict[str, Any],
        character_cards: list[dict[str, Any]],
        style: dict[str, Any],
        negative_lib: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """编译单镜头提示词。

        Args:
            shot: 镜头数据（含 visual_description, character_action, dialogue）
            character_cards: 出场角色卡列表
            style: 画风卡数据
            negative_lib: 全局负面词库（可选）

        Returns:
            {'positive': str, 'negative': str, 'seed': int|None, 'metadata': dict}
        """
        # 1. 画风基础提示词
        parts: list[str] = []
        base_prompt = style.get('base_prompt', '')
        if base_prompt:
            parts.append(base_prompt)

        # 画风风格名
        style_name = style.get('style_name', '')
        if style_name:
            parts.append(style_name)

        # 2. 角色外貌描述（固定注入）
        for char in character_cards:
            appearance = char.get('appearance_prompt', '')
            if appearance:
                parts.append(appearance)
            else:
                # 无 appearance_prompt 时从字段拼接
                char_desc = self._build_character_description(char)
                if char_desc:
                    parts.append(char_desc)

        # 3. 镜头特定内容
        visual_desc = shot.get('visual_description', '')
        if visual_desc:
            parts.append(visual_desc)

        action = shot.get('character_action', '')
        if action:
            parts.append(action)

        # 景别
        scene_type = shot.get('scene_type', '')
        if scene_type:
            parts.append(scene_type)

        # 镜头运动
        camera = shot.get('camera_movement', '')
        if camera:
            parts.append(camera)

        # 4. 合并负面词
        negative_parts: list[str] = []
        style_negative = style.get('negative_prompt', '')
        if style_negative:
            negative_parts.append(style_negative)

        if negative_lib:
            lib_prompts = negative_lib.get('prompts', [])
            if isinstance(lib_prompts, list):
                negative_parts.extend(lib_prompts)

        for char in character_cards:
            char_negative = char.get('negative_traits', [])
            if isinstance(char_negative, list):
                negative_parts.extend(char_negative)

        # 5. 组装结果
        positive = ', '.join(filter(None, parts))
        negative = ', '.join(filter(None, negative_parts))

        seed = style.get('seed')

        return {
            'positive': positive,
            'negative': negative,
            'seed': seed,
            'metadata': {
                'style': style.get('style_name', ''),
                'characters': [c.get('name', '') for c in character_cards],
                'shot_number': shot.get('shot_number'),
            },
        }

    async def compile_for_platform(self, compiled: dict[str, Any], platform: str) -> str:
        """将编译结果适配为不同平台格式。

        Args:
            compiled: compile_shot_prompt() 的返回值
            platform: 'midjourney' | 'stable_diffusion' | 'jimeng' | 'kling'

        Returns:
            平台特定格式的提示词字符串
        """
        positive = compiled.get('positive', '')
        negative = compiled.get('negative', '')
        seed = compiled.get('seed')

        if platform == 'midjourney':
            return self._format_midjourney(positive, negative, seed)
        elif platform == 'stable_diffusion':
            return self._format_stable_diffusion(positive, negative, seed)
        elif platform == 'jimeng':
            return self._format_jimeng(positive, negative)
        elif platform == 'kling':
            return self._format_kling(positive, negative, seed)
        else:
            # 默认返回正向提示词
            return positive

    # -------------------------------------------------------------------------
    # 内部方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_character_description(char: dict[str, Any]) -> str:
        """从角色卡字段拼接外貌描述。"""
        parts = []
        name = char.get('name', '')
        hair = char.get('hair', '')
        eyes = char.get('eyes', '')
        outfit = char.get('outfit', '')
        accessories = char.get('accessories', [])

        if hair:
            parts.append(hair)
        if eyes:
            parts.append(f'eyes: {eyes}')
        if outfit:
            parts.append(f'wearing {outfit}')
        if isinstance(accessories, list) and accessories:
            parts.append(f'accessories: {", ".join(accessories)}')

        if not parts:
            return ''
        desc = ', '.join(parts)
        return f'{name}: {desc}' if name else desc

    @staticmethod
    def _format_midjourney(positive: str, negative: str, seed: int | None) -> str:
        """Midjourney 格式: prompt --ar 9:16 --niji 6 [--seed XXX]"""
        result = f'{positive} --ar 9:16 --niji 6'
        if seed:
            result += f' --seed {seed}'
        if negative:
            result += f' --no {negative}'
        return result

    @staticmethod
    def _format_stable_diffusion(positive: str, negative: str, seed: int | None) -> str:
        """SD 格式: (prompt), [negative], steps, cfg, seed"""
        lines = [f'Positive: ({positive})']
        if negative:
            lines.append(f'Negative: [{negative}]')
        if seed:
            lines.append(f'Seed: {seed}')
        lines.append('Steps: 30, CFG: 7.5')
        return '\n'.join(lines)

    @staticmethod
    def _format_jimeng(positive: str, negative: str) -> str:
        """即梦格式: 中文描述格式"""
        result = f'画面描述：{positive}'
        if negative:
            result += f'\n避免元素：{negative}'
        return result

    @staticmethod
    def _format_kling(positive: str, negative: str, seed: int | None) -> str:
        """可灵视频生成格式"""
        result = f'视频描述：{positive}'
        if negative:
            result += f'\n避免元素：{negative}'
        if seed:
            result += f'\n种子：{seed}'
        result += '\n时长：3-5秒\n分辨率：1080x1920'
        return result
