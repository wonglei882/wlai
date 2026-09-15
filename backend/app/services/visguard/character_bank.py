"""VisGuard 角色资产库 — 角色参考图管理与相似度比对。

组合 ClipEncoder（特征提取）+ FaissIndex（近邻检索）：
- 注册角色（含首张参考图）→ 编码 → 入库
- 追加参考图 → 编码 → 入库（同一角色多向量）
- 删除角色 → 移除该角色全部向量 + 图片目录
- 相似度查询 → 图片编码 → FAISS 近邻 → 按角色聚合 top-N

目录结构（按 project 隔离，角色数据私有不上云）::

    DATA_DIR/visguard/{project_id}/
    ├── characters.json            # 角色元数据
    ├── images/{character_id}/     # 参考图原图
    │   └── {image_id}.png
    └── index/                     # FaissIndex（index.faiss + meta.json）

异常约定：CLIP / faiss 不可用时抛出对应 UnavailableError，由 API 层转为 503，
不静默吞掉（调用方需要明确知道"依赖缺失"与"角色不存在"的区别）。
"""

import json
import logging
import shutil
import uuid
from datetime import UTC
from pathlib import Path

from PIL import Image

from app.services.visguard.clip_encoder import ClipEncoder
from app.services.visguard.faiss_index import FaissIndex
from app.services.visguard.image_utils import image_sha256, image_to_bytes, resize_image

logger = logging.getLogger(__name__)


class CharacterNotFoundError(KeyError):
    """角色不存在。"""


class CharacterBank:
    """单项目的角色资产库（线程安全：底层 ClipEncoder/FaissIndex 各自持锁）。"""

    def __init__(
        self,
        project_id: str,
        base_dir: str | Path,
        clip: ClipEncoder,
        default_threshold: float = 0.7,
    ):
        self.project_id = project_id
        self.root = Path(base_dir) / project_id
        self.images_dir = self.root / 'images'
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._characters_file = self.root / 'characters.json'

        self.clip = clip
        self.default_threshold = default_threshold
        self.index = FaissIndex(self.root / 'index')

        self._characters: dict[str, dict] = {}
        self._load_characters()

    # ------------------------------------------------------------------
    # 持久化 characters.json
    # ------------------------------------------------------------------

    def _load_characters(self) -> None:
        try:
            if self._characters_file.exists():
                with open(self._characters_file, encoding='utf-8') as f:
                    self._characters = json.load(f).get('characters', {})
        except Exception as e:  # noqa: BLE001 - 损坏则重置，避免阻塞服务
            logger.warning('[VisGuard] 角色元数据读取失败，重置: %s', e)
            self._characters = {}

    def _save_characters(self) -> None:
        tmp = self._characters_file.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'characters': self._characters}, f, ensure_ascii=False, indent=2)
        tmp.replace(self._characters_file)

    # ------------------------------------------------------------------
    # 角色 CRUD
    # ------------------------------------------------------------------

    def register(self, name: str, image: Image.Image, description: str = '') -> dict:
        """注册新角色（含首张参考图）。

        Raises:
            ClipUnavailableError: CLIP 不可用。
            FaissUnavailableError: faiss 不可用。
        """
        character_id = uuid.uuid4().hex[:12]
        created_at = _now_iso()

        # 先编码（依赖探活在最前面，失败时不产生半成品角色）
        image = resize_image(image)
        vector = self.clip.encode_image(image)

        # 存图（ID 与索引行一致，便于追溯）
        image_id = self._store_image(character_id, image)

        # 入库
        self.index.add(vector, character_id, image_id)

        self._characters[character_id] = {
            'id': character_id,
            'name': name,
            'description': description,
            'created_at': created_at,
            'image_count': 1,
        }
        self._save_characters()
        logger.info('[VisGuard] 注册角色: %s (%s)', name, character_id)
        return dict(self._characters[character_id])

    def add_image(self, character_id: str, image: Image.Image) -> dict:
        """给已注册角色追加参考图。

        Raises:
            CharacterNotFoundError: 角色不存在。
        """
        if character_id not in self._characters:
            raise CharacterNotFoundError(f'角色不存在: {character_id}')

        image = resize_image(image)
        vector = self.clip.encode_image(image)
        image_id = self._store_image(character_id, image)
        self.index.add(vector, character_id, image_id)

        self._characters[character_id]['image_count'] += 1
        self._save_characters()
        return {
            'character_id': character_id,
            'image_id': image_id,
        }

    def delete(self, character_id: str) -> bool:
        """删除角色（移除向量 + 图片目录 + 元数据）。不存在返回 False。"""
        if character_id not in self._characters:
            return False

        removed = self.index.delete_character(character_id)
        img_dir = self.images_dir / character_id
        if img_dir.exists():
            shutil.rmtree(img_dir, ignore_errors=True)
        del self._characters[character_id]
        self._save_characters()
        logger.info(
            '[VisGuard] 删除角色 %s（移除 %d 条向量）', character_id, removed
        )
        return True

    def get(self, character_id: str) -> dict | None:
        """获取角色信息（含向量条数）。"""
        info = self._characters.get(character_id)
        if info is None:
            return None
        result = dict(info)
        result['embedding_count'] = sum(
            1 for row in self._rows() if row['character_id'] == character_id
        )
        return result

    def list_characters(self) -> list[dict]:
        """全部角色（按创建顺序），附带向量条数。"""
        rows = self._rows()
        result = []
        for cid, info in self._characters.items():
            item = dict(info)
            item['embedding_count'] = sum(
                1 for row in rows if row['character_id'] == cid
            )
            result.append(item)
        return result

    # ------------------------------------------------------------------
    # 相似度比对
    # ------------------------------------------------------------------

    def find_similar(
        self,
        image: Image.Image,
        top_k: int = 5,
        threshold: float | None = None,
    ) -> list[dict]:
        """图片 → 相似角色列表（按角色聚合，分数降序）。

        Args:
            image: 待比对图片。
            top_k: 返回前 N 个角色。
            threshold: 相似度阈值（0-1），低于则过滤；None 用默认阈值。

        Returns:
            list[dict]: [{character_id, name, score, image_id, image_ids}]，
            分数已归一化到 [0,1]（余弦相似度映射）。
        """
        thr = self.default_threshold if threshold is None else threshold
        vector = self.clip.encode_image(image)

        # 多取一些近邻再按角色聚合，避免单角色图片多时占满 top_N
        candidates = self.index.search(vector, top_k=top_k * 3)
        if not candidates:
            return []

        # 按角色聚合：保留最高分 + 命中图片集合
        best: dict[str, dict] = {}
        for row in candidates:
            score = _cosine_to_score(row['score'])
            cid = row['character_id']
            agg = best.setdefault(cid, {
                'character_id': cid,
                'score': score,
                'image_ids': [],
            })
            if score > agg['score']:
                agg['score'] = score
            if row['image_id'] not in agg['image_ids']:
                agg['image_ids'].append(row['image_id'])

        results = []
        for cid, agg in best.items():
            if agg['score'] < thr:
                continue
            info = self._characters.get(cid)
            if info is None:  # 索引残留（异常状态）——跳过并记日志
                logger.warning('[VisGuard] 索引行指向不存在的角色: %s', cid)
                continue
            results.append({
                'character_id': cid,
                'name': info.get('name', cid),
                'score': round(agg['score'], 4),
                'image_ids': agg['image_ids'],
            })

        results.sort(key=lambda r: r['score'], reverse=True)
        return results[:top_k]

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _store_image(self, character_id: str, image: Image.Image) -> str:
        """保存参考图到 images/{character_id}/，返回 image_id。"""
        image_id = uuid.uuid4().hex[:12]
        img_dir = self.images_dir / character_id
        img_dir.mkdir(parents=True, exist_ok=True)
        (img_dir / f'{image_id}.png').write_bytes(image_to_bytes(image))
        return image_id

    def _rows(self) -> list[dict]:
        """直接读 FaissIndex 元数据行（faiss 不可用时返回空，不抛错）。"""
        return list(self.index._meta)  # noqa: SLF001 - 同包内读取元数据

    def image_fingerprint(self, image: Image.Image) -> str:
        """参考图内容指纹（去重辅助，供调用方判断是否重复导入）。"""
        return image_sha256(image)


def _cosine_to_score(cosine: float) -> float:
    """余弦相似度 [-1,1] → [0,1] 分数（与 VisionResult.consistency_score 约定一致）。"""
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec='seconds')