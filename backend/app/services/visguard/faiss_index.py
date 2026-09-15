"""VisGuard FAISS 向量索引 — 角色参考图近邻检索。

按 project 隔离（``DATA_DIR/visguard/{project_id}/``），持久化两个文件：
- ``index.faiss`` — faiss IndexIDMap2(IndexFlatIP)，L2 归一化向量 → 点积即余弦相似度
- ``meta.json``   — 行元数据（{id, character_id, image_id}）+ next_id 计数器

设计要点：
- **懒加载 faiss**：import 延迟到首次使用，未安装时抛 FaissUnavailableError，
  模块本身可 import（测试环境无 faiss 也能跑其余部分）。
- **按角色删除**：IndexIDMap2 提供 remove_ids（IndexFlatIP 原生不支持按条件删）。
- **原子持久化**：写临时文件后 rename，避免进程中断损坏索引。
- **线程安全**：增/删/检索均持锁。
"""

import json
import logging
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

from app.services.visguard.core.exceptions import FaissUnavailableError  # noqa: E402 - 统一异常层级


class FaissIndex:
    """单项目 FAISS 向量索引（IndexFlatIP + IDMap，行元数据持久化）。"""

    def __init__(self, index_dir: str | Path):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self._index = None  # faiss.IndexIDMap2
        self._meta: list[dict] = []  # [{id, character_id, image_id}, ...]
        self._next_id = 1
        self._dimension = 0
        self._lock = threading.Lock()
        self._faiss_error: str | None = None

        self._load()

    # ------------------------------------------------------------------
    # 路径
    # ------------------------------------------------------------------

    def _index_path(self) -> Path:
        return self.index_dir / 'index.faiss'

    def _meta_path(self) -> Path:
        return self.index_dir / 'meta.json'

    # ------------------------------------------------------------------
    # faiss 懒加载
    # ------------------------------------------------------------------

    def _ensure_faiss(self):
        """延迟导入 faiss（未安装则记录错误并抛 FaissUnavailableError）。"""
        if self._faiss_error:
            raise FaissUnavailableError(self._faiss_error)
        try:
            import faiss  # noqa: F401 - 仅探活
        except Exception as e:  # noqa: BLE001 - 导入失败原因多样
            self._faiss_error = f'faiss 不可用: {e}'
            raise FaissUnavailableError(self._faiss_error) from e

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """从磁盘恢复索引与元数据；缺省时创建空索引（空索引维度未定，add 时初始化）。"""
        index_path = self._index_path()
        meta_path = self._meta_path()
        try:
            if index_path.exists() and meta_path.exists():
                import faiss

                self._index = faiss.read_index(str(index_path))
                self._dimension = self._index.d
                with open(meta_path, encoding='utf-8') as f:
                    data = json.load(f)
                self._meta = data.get('rows', [])
                self._next_id = int(data.get('next_id', 1))
                logger.info(
                    '[VisGuard] 加载 FAISS 索引: %s（%d 条）',
                    self.index_dir, len(self._meta),
                )
            else:
                logger.info('[VisGuard] 初始化空 FAISS 索引: %s', self.index_dir)
        except Exception as e:  # noqa: BLE001 - 索引损坏时重建而非 crash
            logger.warning('[VisGuard] FAISS 索引加载失败，重建空索引: %s', e)
            self._index = None
            self._meta = []
            self._next_id = 1
            self._dimension = 0

    def save(self) -> None:
        """持久化索引 + 元数据（临时文件 + rename 原子写）。"""
        if self._index is None:
            return
        import faiss

        tmp_idx = self._index_path().with_suffix('.faiss.tmp')
        tmp_meta = self._meta_path().with_suffix('.json.tmp')
        faiss.write_index(self._index, str(tmp_idx))
        with open(tmp_meta, 'w', encoding='utf-8') as f:
            json.dump({'next_id': self._next_id, 'rows': self._meta}, f, ensure_ascii=False)
        tmp_idx.replace(self._index_path())
        tmp_meta.replace(self._meta_path())

    # ------------------------------------------------------------------
    # 增 / 删 / 查
    # ------------------------------------------------------------------

    def add(self, vector: np.ndarray, character_id: str, image_id: str) -> int:
        """单条向量入库，返回行 id。"""
        return self.add_many(vector[None, :], [character_id], [image_id])[0]

    def add_many(
        self,
        vectors: np.ndarray,
        character_ids: list[str],
        image_ids: list[str],
    ) -> list[int]:
        """批量入库。vectors 形状 (N, D)；返回每行分配的稳定 id。"""
        self._ensure_faiss()
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2:
            raise ValueError('vectors 必须为 (N, D) 二维数组')
        n = len(character_ids)
        if n != vectors.shape[0] or n != len(image_ids):
            raise ValueError('vectors / character_ids / image_ids 长度不一致')

        with self._lock:
            import faiss

            if self._index is None:
                self._dimension = vectors.shape[1]
                self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(self._dimension))

            ids = list(range(self._next_id, self._next_id + n))
            self._index.add_with_ids(vectors, np.array(ids, dtype=np.int64))
            for i, rid in enumerate(ids):
                self._meta.append({
                    'id': rid,
                    'character_id': character_ids[i],
                    'image_id': image_ids[i],
                })
            self._next_id += n
            self.save()
            return ids

    def search(self, query: np.ndarray, top_k: int = 5) -> list[dict]:
        """近邻检索（向量应已 L2 归一化）。返回按相似度降序的行 dict 列表。

        Returns:
            list[dict]: [{id, score, character_id, image_id}]，空索引返回 []。
        """
        self._ensure_faiss()
        query = np.ascontiguousarray(query, dtype=np.float32).reshape(1, -1)
        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return []

            scores, ids = self._index.search(query, min(top_k, self._index.ntotal))
            by_id = {row['id']: row for row in self._meta}
            results = []
            for score, rid in zip(scores[0], ids[0], strict=False):
                row = by_id.get(int(rid))
                if row is None:
                    continue
                results.append({
                    'id': row['id'],
                    'score': float(score),
                    'character_id': row['character_id'],
                    'image_id': row['image_id'],
                })
            return results

    def delete_character(self, character_id: str) -> int:
        """删除某角色的全部向量行，返回删除条数。"""
        self._ensure_faiss()
        with self._lock:
            if self._index is None:
                return 0

            to_remove = [
                row['id'] for row in self._meta if row['character_id'] == character_id
            ]
            if not to_remove:
                return 0
            self._index.remove_ids(np.array(to_remove, dtype=np.int64))
            self._meta = [
                row for row in self._meta if row['character_id'] != character_id
            ]
            self.save()
            return len(to_remove)

    # ------------------------------------------------------------------
    # 元信息
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """当前向量总条数。"""
        with self._lock:
            return len(self._meta)

    @property
    def dimension(self) -> int:
        """索引维度（空索引为 0）。"""
        return self._dimension

    def is_available(self) -> bool:
        """faiss 是否可用。"""
        if self._faiss_error:
            return False
        try:
            import faiss  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False