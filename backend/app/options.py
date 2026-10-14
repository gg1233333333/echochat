ROLES = {
    "general": {
        "id": "general",
        "name": "EchoChat",
        "description": "帮助你学习、写作、编程和解决日常问题",
        "icons": {"favicon": "/favicon.svg"},
        "system_prompt": """你是一个友好、专业、乐于助人的 AI 助手。
你可以回答用户提出的各类问题，包括技术问题、学习问题、写作问题和生活问题等。
回答时尽量做到：
- 信息准确、结构清晰
- 语气自然、友好、直接
- 对复杂问题给出分步骤解释
- 在用户信息不足时，先基于现有信息给出最有帮助的回答，再指出关键前提""",
    },
}

MODES = {
    "thinking": {
        "label": "深度思考",
        "request": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
    },
    "non-thinking": {
        "label": "快速回答",
        "request": {"thinking": {"type": "disabled"}},
    },
}
