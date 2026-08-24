"""网文段落格式化 —— 将 AI 生成的大段落重排为网文短段落

规则（手机阅读习惯）：
- 目标每段 30~110 字（手机 3~4 行），超过 110 字强制拆分
- 对话（含引号）尽量独立成段；超长对话句拆出引号部分独立成段
- 段落之间用 \n\n 分隔
"""

import re

# 目标段落长度（网文手机阅读舒适区间）
_MAX_PARA = 110

# 成对引号（中英文弯引号、直角引号、ASCII 双引号）
_DIALOG_RE = re.compile(r'[“"「『][^”"」』]*[”"」』]')

# 句子结束标点
_SENT_END_RE = re.compile(r'[。！？!?；;]')


def _split_long_para(para: str) -> list:
    """把长段落按句子边界拆成句子列表（对话区间内部不拆）"""
    dialog_spans = [(m.start(), m.end()) for m in _DIALOG_RE.finditer(para)]

    def inside_dialog(pos: int) -> bool:
        for s, e in dialog_spans:  # noqa: SIM110
            if s < pos <= e:
                return True
        return False

    bounds = [0]
    for m in _SENT_END_RE.finditer(para):
        if not inside_dialog(m.end()):
            bounds.append(m.end())
    bounds.append(len(para))

    sentences = []
    seg_start = 0
    for b in bounds[1:]:
        seg = para[seg_start:b].strip()
        if seg:
            sentences.append(seg)
        seg_start = b
    tail = para[seg_start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _is_dialogue(sentence: str) -> bool:
    """判断句子是否包含完整对话（引号包裹）"""
    return bool(_DIALOG_RE.search(sentence))


def _split_dialogue_sentence(sentence: str):
    """把含对话的超长句拆成 (前缀, 引号段, 后缀)；无引号时返回 [sentence]"""
    m = _DIALOG_RE.search(sentence)
    if not m:
        return [sentence]
    pre, dlg, post = sentence[: m.start()].strip(), m.group(0).strip(), sentence[m.end() :].strip()
    return [p for p in (pre, dlg, post) if p]


def format_webnovel_paragraphs(text: str, max_para: int = _MAX_PARA) -> str:
    """把正文重排为网文短段落格式。幂等：已合规的段落不会被重复拆分。"""
    if not text or not text.strip():
        return text

    raw_paras = [p.strip() for p in re.split(r'\n+', text) if p.strip()]
    out_paras: list = []

    for para in raw_paras:
        if len(para) <= max_para:
            out_paras.append(para)
            continue

        # 长段落：拆句后重新聚合
        sentences = _split_long_para(para)
        buf = ''
        for s in sentences:
            # 对话句：短的直接独立成段；超长的拆出引号部分
            if _is_dialogue(s):
                if len(s) <= max_para:
                    if buf:
                        out_paras.append(buf)
                        buf = ''
                    out_paras.append(s)
                    continue
                for part in _split_dialogue_sentence(s):
                    if len(part) <= max_para and _is_dialogue(part):
                        if buf:
                            out_paras.append(buf)
                            buf = ''
                        out_paras.append(part)
                    else:
                        # 前缀/后缀进入聚合缓冲
                        if buf and len(buf) + len(part) > max_para:
                            out_paras.append(buf)
                            buf = part
                        else:
                            buf += part
                continue
            # 普通句：聚合到目标长度
            if buf and len(buf) + len(s) > max_para:
                out_paras.append(buf)
                buf = s
            else:
                buf += s
        if buf:
            out_paras.append(buf)

    return '\n\n'.join(out_paras)
