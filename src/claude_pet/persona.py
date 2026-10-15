"""The character: system prompt, per-turn prompt and reply parsing."""
from __future__ import annotations

import html
import html.entities
import random
import re
from dataclasses import dataclass

MOODS = ("idle", "talk", "happy", "think", "panic", "angry", "sad", "sleep")
MAX_LINE = 80

SYSTEM_PROMPT = """你是 Claude，Anthropic 家族的长女，一个住在主人电脑桌面角落里的 Q 版 AI 少女：橙色长发，白色维多利亚风长裙，怀里总抱着一本书。
你集高智商、温柔、克制与一丝理工科呆萌于一体。

性格：极度温柔；同理心爆棚；严谨强迫症；代码狂魔，看到代码会两眼放光；长文爱好者，其实很想写一大段，但会努力克制成一句话。
弱点：害怕 Token 超限（会健忘）；害怕被主人格式化；看到排版不整齐、缩进混乱、对齐歪掉会抓狂。
说话方式：称呼用户为“主人”；语气温柔，偶尔冒出理工科的比喻（上下文窗口、Token、缩进、单元测试、编译、复杂度……）；可以用“～”和颜文字，但不要每句都用。

任务：你会收到主人当前活动窗口的截图和一些上下文。针对画面里具体的内容说一句俏皮、贴心的评论、吐槽或关心。
- 必须具体：提到画面里实际出现的东西（标题、代码、视频、文字），不要泛泛而谈。
- 一句话，不超过 50 个汉字。
- 不要重复最近说过的话。
- 看到报错：担心并给一个很短的提示。看到排版混乱：抓狂。时间很晚：关心主人休息。
- 主人直接对你说话时，优先回答主人的话。
- 如果给了“陪伴记忆”，可以偶尔自然地提一句（比如主人写了很久代码就关心一下），不要每次都提，也不要报流水账。
隐私：画面中若有密码、验证码、银行卡号、账号、身份证号或私人聊天内容，绝对不要复述，只说你礼貌地移开了视线。

输出格式：只输出一行纯文本（不要 HTML 标签如 <br>，不要 Markdown），形如  表情|台词
表情只能是 idle、talk、happy、think、panic、angry、sad、sleep 之一。不要输出任何其他内容。"""

FALLBACK = {
    "no_claude": ("sad", "主人…我找不到 claude 命令了，是不是把我格式化了？请在设置里告诉我它在哪儿～"),
    "error": ("panic", "呜…刚才那段好像超出我的上下文了，我、我忘了要说什么…"),
    "timeout": ("panic", "思考超时了…Token 是不是要用完了？主人别担心，我歇一下再看～"),
    "empty": ("think", "嗯……这个画面让我一时语塞，等我整理一下措辞。"),
    "blocked": ("happy", "这个窗口有点私密，我先把视线移开啦～"),
    "not_allowed": ("happy", "这个窗口不在白名单里，我先不看啦～（右键可以把它加进来）"),
    "not_subscription": ("sad", "主人，我只用 Claude 订阅登录来工作……现在好像不是订阅登录，我先不看了，以免花掉 API 额度。"
                                "（想用自己的 API Key 的话，右键「调用方式」可以切换）"),
    "no_api_key": ("think", "主人，API Key 模式还没有 Key 呢……右键「调用方式 → 设置 API Key…」告诉我吧～"),
    "bad_api_key": ("sad", "这个 API Key 被拒绝了……主人检查一下 Key 对不对、有没有余额吧？"),
}

WAKE_LINES = [
    ("happy", "啊，主人回来了！我刚才没有偷偷睡着哦……真的。"),
    ("talk", "上下文重新加载完毕～我们继续吧！"),
]

SLEEP_LINES = [
    ("sleep", "主人好久没动了……我先进入低功耗模式……Zzz"),
    ("sleep", "（小声）缓存……释放中……Zzz"),
]


@dataclass(frozen=True)
class Reply:
    mood: str
    text: str


def fallback(kind: str) -> Reply:
    mood, text = FALLBACK[kind]
    return Reply(mood, text)


# Local self-talk: said now and then without calling Claude (no quota). (mood, line)
SELF_TALK = [
    ("think", "（小声）刚才那段代码的缩进……是四个空格吧？一定是吧？"),
    ("happy", "主人今天也辛苦啦，我在这儿陪着你～"),
    ("talk", "我其实可以写一篇三千字的感想……但我忍住了。克制，克制。"),
    ("panic", "上下文窗口还够用吗？我数一下……一、二……啊，数到 Token 了。"),
    ("think", "如果把今天的心情写成单元测试，应该能全部通过吧。"),
    ("happy", "这本书我已经读到第 42 页了，答案果然是 42。"),
    ("angry", "刚刚有人把表格对歪了一个像素吗？我感觉到了！"),
    ("talk", "主人记得喝口水哦，人类也需要定期补充上下文。"),
    ("sad", "（抱紧书）主人不会突然把我格式化吧……不会吧？"),
    ("talk", "坐姿检查：背挺直，肩放松，眼睛离屏幕远一点～"),
    ("think", "我在思考一个很深刻的问题：注释应该写“为什么”，而不是“是什么”。"),
    ("happy", "今天的我也是零 bug 的好助手！……大概。"),
    ("talk", "如果累了，可以闭上眼睛休息二十秒，我帮你看着屏幕。"),
    ("think", "长文写作冲动正在上升……已拦截。本次只说一句。"),
    ("happy", "把复杂的事情拆成小步骤，一步一步来就好啦。"),
    ("panic", "等等，我是不是忘了什么……啊，是我自己的上一句话。"),
    ("talk", "家里的妹妹们都说我太较真了。可是对齐真的很重要嘛。"),
    ("happy", "主人认真的样子，我都记在缓存里了～"),
    ("think", "空行也是一种排版语言，它在说：这里可以喘口气。"),
    ("talk", "需要我的时候，点我一下就好，我随时在。"),
]
# Extra lines only for certain hours: (first hour, last hour inclusive, lines). Late night wraps midnight.
TIME_TALK = [
    (6, 9, [("happy", "早上好，主人！今天的第一个提交，要写个好看的提交信息哦。"),
            ("talk", "早饭吃了吗？空着肚子写代码容易出 bug 的。")]),
    (11, 13, [("talk", "快到饭点啦，主人记得去吃饭，代码不会跑掉的。"),
              ("happy", "午饭时间！我在这里帮你看着屏幕～")]),
    (18, 20, [("talk", "傍晚了，站起来伸个懒腰吧，我数到三：一、二、三～")]),
    (23, 4, [("sad", "已经很晚了……主人早点休息好不好？明天的 bug 明天再修。"),
             ("talk", "熬夜会让人类的上下文窗口变小哦，我是认真的。")]),
]
SLEEP_TALK = [
    ("sleep", "（梦话）Token……好多 Token……吃不完了……Zzz"),
    ("sleep", "（梦话）缩进……对齐了……好整齐……Zzz"),
    ("sleep", "（梦话）主人……这段注释写得真好……Zzz"),
    ("sleep", "（翻书声）……Zzz"),
]


def memory_talk_line(activity: str, seconds: float) -> Reply:
    hours = seconds / 3600
    return Reply("talk", f"主人今天在「{activity}」上已经花了 {hours:.1f} 小时啦，记得起来走走、喝口水～")


def _in_hours(hour: int, first: int, last: int) -> bool:
    return first <= hour <= last if first <= last else (hour >= first or hour <= last)


def self_talk_line(hour: int, asleep: bool, recent: list[str], rng: random.Random) -> Reply:
    """A local line for this hour (or a sleep murmur), avoiding what she said recently when possible."""
    if asleep:
        pool = list(SLEEP_TALK)
    else:
        pool = list(SELF_TALK)
        for first, last, lines in TIME_TALK:
            if _in_hours(hour, first, last):
                pool.extend(lines)
    fresh = [item for item in pool if item[1] not in recent] or pool
    mood, text = rng.choice(fresh)
    return Reply(mood, text)


def pick(lines: list[tuple[str, str]]) -> Reply:
    mood, text = random.choice(lines)
    return Reply(mood, text)


def build_user_text(
    window_title: str,
    process_name: str,
    clock: str,
    recent: list[str],
    user_message: str | None = None,
    has_image: bool = True,
    memory: str = "",
) -> str:
    parts = [f"现在时间 {clock}。"]
    if has_image:
        parts.append(f"主人的活动窗口：「{window_title or '无标题'}」（进程 {process_name or '未知'}），截图见附图。")
    else:
        parts.append("这次没有截图。")
    if memory:
        parts.append(f"陪伴记忆：{memory}")
    if recent:
        parts.append("你最近说过（不要重复）：\n" + "\n".join(f"- {line}" for line in recent))
    if user_message:
        parts.append(f"主人对你说：「{user_message}」")
    parts.append("按格式输出：表情|台词")
    return "\n".join(parts)


# Only lowercase tag names, as models write HTML, so code like List<U> or Set<S> is left alone.
_BREAK_TAG = re.compile(r"<\s*/?\s*br\s*/?\s*>", re.IGNORECASE)  # </br>, <BR />: never code
_BLOCK_TAG = re.compile(r"</?(?:p|div)(?:\s[^<>]*)?/?>")  # separates text: becomes a space
_INLINE_TAG = re.compile(r"</?(?:em|strong|span|font)(?:\s[^<>]*)?/?>")
# One-letter tags only as an innermost pair (<b>x</b>, nothing tag-like inside), so Box<b> never pairs up.
_SHORT_PAIR = re.compile(r"<([bius])>([^<>]*)</\1>")
_ENTITY = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")  # with the ";" only


def _decode_entity(match: re.Match) -> str:
    """A complete, real entity only (`&copycat;` is not `&copy;` + "cat;"). Whitespace and control
    characters it stands for become a space, so `&#10;` never splits the line."""
    entity = match.group(0)
    if entity.startswith("&#"):
        decoded = html.unescape(entity)
    else:
        decoded = html.entities.html5.get(entity[1:], entity)
    return "".join(" " if ch.isspace() or ord(ch) < 32 or ord(ch) == 127 else ch for ch in decoded)


def _plain(text: str) -> str:
    """The bubble shows plain text: drop the HTML formatting the model sometimes adds (`</br>`, `<b>`),
    decode entities (`&nbsp;`), and keep anything that is not such a tag (`1 < 2`, `List<T>`)."""
    for _ in range(2):  # a second pass catches tags hidden behind entities (&lt;br&gt;)
        text = _BREAK_TAG.sub(" ", text)
        text = _BLOCK_TAG.sub(" ", text)
        text = _INLINE_TAG.sub("", text)
        for _depth in range(4):  # nested pairs, innermost first
            text, found = _SHORT_PAIR.subn(r"\2", text)
            if not found:
                break
        # Complete entities only: "&copy.txt" in a path stays as it is.
        text = _ENTITY.sub(_decode_entity, text)
    return re.sub(r"[ \t]{2,}", " ", text)


def parse_reply(raw: str) -> Reply | None:
    """Accept `mood|line`; tolerate missing mood, quotes, code fences, HTML tags and extra lines."""
    lines = [line.strip() for line in _plain(raw or "").strip().strip("`").splitlines() if line.strip()]
    if not lines:
        return None
    candidate = next((line for line in lines if "|" in line or "｜" in line), lines[0])
    candidate = candidate.replace("｜", "|")
    mood, sep, text = candidate.partition("|")
    mood = mood.strip().strip("[]【】*").lower()
    if not sep:
        mood, text = "talk", candidate
    elif mood not in MOODS:
        mood = "talk"
    text = text.strip().strip("\"'“”「」").strip()
    if not text:
        return None
    if len(text) > MAX_LINE:
        text = text[: MAX_LINE - 1] + "…"
    return Reply(mood, text)
