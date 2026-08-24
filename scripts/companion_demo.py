"""
四维智能创作陪伴能力演示（纯规则路径，无需数据库 / LLM）

演示内容：
  S 苏格拉底：对创作问题生成三级提问链
  T 家教：    同一错误第 1/2/3 次的分层反馈（原则→线索→示例）
  E 百科：    按主题检索种子创作百科
  P 秘书：    按时段问候 + 每日贴心简报

运行：cd backend && python ../scripts/companion_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))


def demo_socratic():
    print('\n' + '=' * 64)
    print('维度 S · 苏格拉底的大脑 — 引导式提问（不直接给答案）')
    print('=' * 64)
    from app.services.companion import build_socratic_chain

    issue = {'type': 'pacing', 'message': '第 12 章写得像流水账，节奏拖沓，读者反馈没动力往下看。'}
    chain = build_socratic_chain(issue)
    print(f'问题类型：{chain["topic"]}')
    for lvl in chain['levels']:
        print(f'  Q{lvl["step"]}. {lvl["question"]}')
    print('（命中 socratic_redirect_if_needed 时，PM 会自动进入引导模式而非自动修复）')


def demo_tutor():
    print('\n' + '=' * 64)
    print('维度 T · 优秀家教的耐心 — 同一错误三次的分层反馈')
    print('=' * 64)
    from app.services.companion import format_tutored_feedback

    issue = {'type': 'dialogue_quality', 'message': '第 15 章对话全是说明文，两个人在各说各话。'}
    for n in (1, 2, 3):
        fb = format_tutored_feedback(issue, experience_level='beginner', attempt_count=n)
        print(f'\n  第 {n} 次犯错 → 反馈层级: {fb["tier"]}（{fb["tier_label"]}）')
        for s in fb['steps']:
            print(f'    · {s}')
        if fb['example']:
            print(f'    示范：{fb["example"]}')
        print(f'    鼓励：{fb["encouragement"]}')


def demo_encyclopedia():
    print('\n' + '=' * 64)
    print('维度 E · 百科全书的储备 — 种子百科检索')
    print('=' * 64)
    from app.services.companion import search_knowledge

    for topic in ('对话', '伏笔', '节奏'):
        hits = search_knowledge(topic, top_k=2)
        print(f'\n  主题「{topic}」：')
        for h in hits:
            print(f'    [{h["score"]:.2f}] {h["name"]} — {h["description"]}')
        if not hits:
            print('    （无命中）')


def demo_secretary():
    print('\n' + '=' * 64)
    print('维度 P · 私人秘书的贴心 — 问候 + 每日简报')
    print('=' * 64)
    from app.services.companion import compose_daily_briefing, personal_greeting

    print(f'\n  问候（14:00）：{personal_greeting(14)}')
    ctx = {'title': '星海拾光', 'chapter_count': 23, 'progress': '46%', 'last_topic': '对话'}
    report = {'issues': [{'message': '第 15 章对话偏说明文'}, {'message': '伏笔「怀表」已搁置 9 章'}]}
    b = compose_daily_briefing(project_ctx=ctx, report=report)
    print(f'  简报（{b["tone"]}）：\n  {b["text"]}')


def main():
    print('=' * 64)
    print('四维智能创作陪伴（Socratic · Tutor · Encyclopedia · Private Secretary）')
    demo_socratic()
    demo_tutor()
    demo_encyclopedia()
    demo_secretary()
    print('\n' + '=' * 64)
    print('演示结束。功能开关：pm_features.yaml → optional.companion.enabled')
    print('=' * 64)


if __name__ == '__main__':
    main()
