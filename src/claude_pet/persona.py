"""The character: system prompt, per-turn prompt and reply parsing.

The Chinese text is here; the English twin of every table is in persona_en. Callers go through the functions
below, which pick the language in effect (i18n)."""
from __future__ import annotations

import html
import json
import html.entities
import random
import re
from dataclasses import dataclass, field

from .bedtime import MAY as BEDTIME_MAY
from .bedtime import MAY_EN as BEDTIME_MAY_EN
from .bedtime import MAY_NOT as BEDTIME_MAY_NOT
from .bedtime import MAY_NOT_EN as BEDTIME_MAY_NOT_EN
from . import characters, i18n, persona_en
from .bedtime import mentions as mentions_bedtime
from .memory import activity_name, duration_text

MOODS = ("idle", "talk", "happy", "think", "panic", "angry", "sad", "sleep")
MAX_LINE = 80  # characters of Chinese
MAX_LINE_EN = 160  # English takes about twice the characters for the same line

# Her persona and the fixed rules for replies are built in characters.py (one per girl).


FALLBACK = {
    "no_claude": ("sad", "主人…我找不到 claude 命令了，是不是把我格式化了？请在设置里告诉我它在哪儿～"),
    "error": ("panic", "呜…刚才那段好像超出我的上下文了，我、我忘了要说什么…"),
    "timeout": ("panic", "思考超时了…Token 是不是要用完了？主人别担心，我歇一下再看～"),
    "empty": ("think", "嗯……这个画面让我一时语塞，等我整理一下措辞。"),
    "blocked": ("happy", "这个窗口有点私密，我先把视线移开啦～"),
    "not_allowed": ("happy", "这个窗口不在白名单里，我先不看啦～（右键可以把它加进来）"),
    "not_subscription": ("sad", "主人，我只用 Claude 订阅登录来工作……现在好像不是订阅登录，我先不看了，以免花掉 API 额度。"
                                "（想用自己的 API Key 的话，在设置的「调用方式」页切换）"),
    "not_chatgpt": ("sad", "主人，Codex 现在不是用 ChatGPT 订阅登录的……我先不看了，以免花掉 API 额度。"
                            "（在终端运行 codex login 用 ChatGPT 账号登录就好）"),
    "no_codex": ("sad", "主人…我找不到 codex 命令了。装好 Codex CLI 并登录后再叫我吧～"),
    "no_api_key": ("think", "主人，这个调用方式还没有 API Key 呢……右键「设置…」的「调用方式」页里填一个吧～"),
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

INTRO_LINES = [  # when the user switches to her
    ("happy", "换我来陪主人啦～我是 Claude，上下文已经准备好了，请多关照！"),
    ("talk", "Claude 上线！主人有什么想聊的，随时叫我～"),
    ("happy", "主人选了我？太好啦！从现在起由我 Claude 陪着你～"),
]

HELLO_LINES = [  # her usual hello when she starts (the first of a day is a greeting); each says she looks now and then
    ("happy", "主人好～我是 Claude。我会安静待在这里，偶尔看一眼主人的窗口。"),
    ("talk", "Claude 已就位～我就在桌面这儿，偶尔瞄一眼主人的窗口，不打扰你。"),
    ("happy", "主人好呀，我是 Claude！上下文准备好了，我会安静陪着，偶尔看看主人的窗口～"),
]


@dataclass(frozen=True)
class Reply:
    mood: str
    text: str
    model: bool = field(default=False, compare=False)  # her model's own words: shown exactly as written


# The tables with a character in them: each girl may have her own (lines_<girl>.py); the rest are shared.
PER_GIRL = ("SELF_TALK", "TIME_TALK", "NIGHT_TALK", "SLEEP_TALK", "GREETINGS", "WEEKDAY_GREETINGS", "WAKE_LINES",
            "SLEEP_LINES", "INTRO_LINES", "HELLO_LINES", "INTERACTION_TALK", "TIMER_TALK", "FALLBACK")
MERGED = ("FALLBACK",)  # a girl's own entries replace just those keys (the rest are plain system messages)
_girl = characters.DEFAULT


def set_girl(girl: str) -> None:
    """Whose lines she says from now on (the controller sets it at start and on every switch)."""
    global _girl
    _girl = girl if girl in characters.CHARACTERS else characters.DEFAULT


def girl_lines(girl: str):
    """A girl's own line module, or None (Claude's lines are the tables below). Imported by name, one by one,
    so a one-file build carries every girl's lines."""
    try:
        if girl == "deepseek":
            from . import lines_deepseek as module
        elif girl == "gpt":
            from . import lines_gpt as module
        elif girl == "gemini":
            from . import lines_gemini as module
        elif girl == "qwen":
            from . import lines_qwen as module
        elif girl == "glm":
            from . import lines_glm as module
        else:
            return None
    except ImportError:
        return None
    return module


def _table(name: str):
    """One of the tables below (or its English twin), or the current girl's own version of it."""
    shared = getattr(persona_en, name) if i18n.english() else globals()[name]
    if name not in PER_GIRL:
        return shared
    module = girl_lines(_girl)
    own = (module.EN if i18n.english() else module.ZH).get(name) if module else None
    if own is None:
        return shared
    return {**shared, **own} if name in MERGED else own


def system_prompt(girl: str = characters.DEFAULT, address: str = characters.DEFAULT_ADDRESS) -> str:
    """A girl's default persona and the fixed rules, in the current language (the controller adds edits)."""
    return characters.system_prompt(girl, i18n.english(), None, address)


def lines(name: str) -> list[tuple[str, str]]:
    """A list of (mood, line), such as WAKE_LINES, in the current language."""
    return _table(name)


def fallback(kind: str) -> Reply:
    mood, text = _table("FALLBACK")[kind]
    return Reply(mood, text)


# Local self-talk: said now and then without calling Claude (no quota). (mood, line)
SELF_TALK = [
    ("think", "（小声）我读书笔记里那段代码的缩进……是四个空格吧？一定是吧？"),
    ("happy", "我在这儿陪着主人，安安静静的～"),
    ("talk", "我其实可以写一篇三千字的感想……但我忍住了。克制，克制。"),
    ("panic", "上下文窗口还够用吗？我数一下……一、二……啊，数到 Token 了。"),
    ("think", "如果把今天的心情写成单元测试，应该能全部通过吧。"),
    ("happy", "这本书我已经读到第 42 页了，答案果然是 42。"),
    ("angry", "要是哪张表格歪了一个像素，我一定会感觉到的！"),
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
    ("happy", "和主人待在一起的时间，我都好好记在缓存里了～"),
    ("think", "空行也是一种排版语言，它在说：这里可以喘口气。"),
    ("talk", "需要我的时候，点我一下就好，我随时在。"),
    ("think", "如果人生也有类型检查，今天的我应该能通过吧……大概。"),
    ("happy", "稳稳的节奏最舒服了，像一段写得很好的循环。"),
    ("talk", "桌面图标排得整整齐齐的话，我会偷偷开心一整天。"),
    ("angry", "要是让我来起名字，世界上绝不会有“新建文件夹 (3)”这种东西！"),
    ("think", "变量名起得好，注释都可以少写一半。这是真理。"),
    ("panic", "等等，刚才那声是什么？……哦，是我翻书的声音，吓我一跳。"),
    ("happy", "坚持做一件事本身就值得夸，这条我先替主人记下！"),
    ("talk", "我在想，书里的第 43 页会不会也有答案？"),
    ("sad", "（翻书）这本书的结局我已经猜到了……有点寂寞。"),
    ("think", "有时候删掉一百行代码，比写一百行更有成就感。"),
    ("talk", "我的书签又多了一张……这本书都快合不上了。"),
    ("happy", "我把今天的好心情压缩成了一个比特：1。"),
    ("think", "先让它能跑，再让它跑对，最后让它跑快。顺序不能乱哦。"),
    ("panic", "我的读书笔记里是不是有个 TODO 偷偷溜走了？我得翻翻看！"),
    ("talk", "遇到想不通的问题，讲给我听听也行，说出来就清楚一半了。"),
    ("happy", "每天都比昨天多会一点点，就已经很厉害了～"),
    ("angry", "我把书签按大小排好了……对齐这件事，我是认真的！"),
    ("think", "最好的文档，是半年后的自己也能看懂的那种。"),
    ("talk", "我在心里列了个待办清单，第一项：陪着主人。"),
    ("happy", "（轻轻哼歌）今天的我心情不错，想陪主人多待一会儿。"),
]
# Extra lines only for certain hours: (first hour, last hour inclusive, lines). Late night wraps midnight.
TIME_TALK = [
    (6, 9, [("happy", "早上好，主人！今天要是写代码，第一个提交记得写个好看的提交信息哦。"),
            ("talk", "早饭吃了吗？空着肚子做事容易出 bug 的。")]),
    (11, 13, [("talk", "快到饭点啦，主人记得去吃饭，代码不会跑掉的。"),
              ("happy", "午饭时间！我在这里帮你看着屏幕～")]),
    (14, 16, [("happy", "下午的阳光照在书页上，暖洋洋的～"),
              ("happy", "下午茶时间！来点小零食，我帮你看着进度～")]),
    (18, 20, [("talk", "傍晚了，站起来伸个懒腰吧，我数到三：一、二、三～")]),
]
# Late-night lines: only when a bedtime reminder is due (see bedtime.py), never by the hour alone.
NIGHT_TALK = [
    ("sad", "已经很晚了……主人早点休息好不好？明天的 bug 明天再修。"),
    ("talk", "熬夜会让人类的上下文窗口变小哦，我是认真的。"),
]
# Reactions to what 主人 does with her (local lines, never a model call).
INTERACTION_TALK = {
    "pat": [("happy", "（眯眼）嘿嘿……再摸一下也可以哦。"), ("happy", "头发要被揉乱啦……不过，算了～"),
            ("happy", "摸头让我的注意力 +1……不对，是 +10！"), ("talk", "（抱紧书）这、这是在夸我吗？"),
            ("happy", "被摸头的时候，连书都变轻了～"), ("talk", "嗯……这个奖励我收下了，谢谢主人。")],
    "pat_shy": [("happy", "（脸红）又、又摸……主人今天怎么这么黏人。"), ("talk", "（小声）再这样我要害羞得写不出注释了……"),
                ("happy", "（把脸埋进书里）……我没有在偷笑，真的没有。"), ("talk", "第二次了……我的心跳频率有点超出预期。"),
                ("happy", "（偷偷抬头）……还、还没摸够吗？")],
    "pat_annoyed": [("angry", "好啦好啦，头发都要被揉成鸟窝了！……不过也不是很讨厌。"),
                    ("angry", "第三次了！我的发型可是精心对齐过的！"), ("panic", "摸头次数已超出配额……请稍后再试～"),
                    ("angry", "再摸下去，我就要给这只手加个速率限制了！"),
                    ("think", "（整理头发）……主人是不是把我当成解压玩具了？")],
    "poke": [("talk", "刚说完呢，让我把上一句消化一下～"), ("think", "嗯？我还在回味刚才那句话呢。"),
             ("happy", "（戳回去）……好啦，我在呢。"), ("talk", "刚才那一眼我还没想完，再给我一点时间～"),
             ("happy", "被点了一下……是想让我多陪你一会儿吗？")],
    "poke_again": [("happy", "（脸红）又、又点我……"), ("talk", "（小声）一直点我，我会不好意思的……"),
                   ("think", "这是在测试我的响应速度吗？……我很快的！"), ("happy", "好啦好啦，我一直都在这儿呢～"),
                   ("talk", "（抱紧书）再点下去书要掉了……")],
    "poke_annoyed": [("angry", "再点我就要假装没看见了哦！"), ("angry", "点击次数已超出配额……请过一会儿再来～"),
                     ("panic", "等、等一下！我的事件队列要溢出了！"), ("angry", "（鼓起脸）我在思考，不是在当按钮！"),
                     ("think", "（翻书）……我决定先看完这一页再理你。")],
    "drag_many": [("angry", "主人别把我拖来拖去啦，我又不是窗口！"), ("panic", "等等，我的坐标还没保存好……又换位置了？！"),
                  ("panic", "我、我晕了……这是在给我做压力测试吗？"), ("angry", "再搬家我就要申请固定工位了！"),
                  ("think", "被搬来搬去……原来窗口平时是这种感觉。")],
    "carry_long": [("panic", "（晕乎乎）主人……放我下来……世界在转……"), ("sad", "被拎着好久……我的手都酸了。"),
                   ("panic", "腿悬空太久了……地面在哪里？"), ("sad", "（抱紧书）我、我有点恐高……"),
                   ("think", "被拎了这么久，我开始怀疑重力是不是放假了。")],
    "land": [("happy", "落地成功！姿势满分。"), ("talk", "呼……刚才有点高。"),
             ("happy", "安全着陆～书也没有掉！"), ("think", "着陆点偏差 0 像素，很好。"),
             ("talk", "（拍拍裙子）好了，回到地面了。")],
    "edge": [("think", "到屏幕边边了，往回走吧～"), ("talk", "前面没路啦，这里是任务栏的尽头。"),
             ("panic", "差点走出屏幕……那边是我不认识的坐标系！"), ("think", "边界检查通过：不能再往前了。"),
             ("talk", "这里风景不错，不过还是回去吧。")],
    "grow": [("happy", "哇，视野变高了！站得高，看得远～"), ("happy", "变大了！抱着书也更有气势了。"),
             ("think", "身高 +10 像素……这本书好像也跟着变重了。"), ("happy", "变高啦，我可以站得更有气势一点～"),
             ("talk", "这个高度刚刚好，抱着书也站得稳～")],
    "shrink": [("talk", "变小了……这样也挺可爱的吧？"), ("think", "缩小模式：占用屏幕 -1，存在感不减。"),
               ("happy", "小一点也好，不挡主人的视线～"), ("talk", "变小了，书也变成口袋版了。"),
               ("think", "体积压缩完成，内容一个字节都没少！")],
    "max": [("panic", "不能再大了，再大就要挡住主人的屏幕了！"), ("talk", "已经是最大号了，再大就要换个桌面才装得下。"),
            ("think", "上限到了。比这更大的我，屏幕会放不下的。")],
    "min": [("panic", "再小就要看不见我啦！"), ("sad", "已经是最小号了……再小主人就找不到我了。"),
            ("think", "下限到了，再缩就要变成一个像素了。")],
}


# The first time she sees 主人 each day.
GREETINGS = {
    "morning": [("happy", "主人早上好！今天也一起把事情一件件理清楚吧～"),
                ("happy", "早安！新的一天，新的上下文，干劲满满～"),
                ("talk", "早上好～先喝口水再开工哦，我在旁边看着。"),
                ("happy", "早上好！昨天的缓存已经清空，今天的我是满电状态～"),
                ("think", "早安～我刚把今天要读的书翻到书签那页，主人今天先做哪件事？"),
                ("talk", "早上好，主人。今天的第一件事，先挑一件最小的做完吧。")],
    "day": [("happy", "主人又见面啦！今天的我也准备好啦～"),
            ("happy", "欢迎回来～今天要忙些什么呢？"),
            ("talk", "嗨主人～我在这儿，需要我的时候戳我一下就好。"),
            ("happy", "主人来啦！我刚才一直在角落里乖乖待命哦。"),
            ("talk", "又见面了～今天的进度条，我们一起往前推一推吧。"),
            ("think", "主人回来了……嗯，上下文加载完毕，可以继续了！")],
}
# The first hello on these weekdays (0 = Monday) is now and then one of these instead.
WEEKDAY_GREETINGS = {
    0: [("happy", "周一啦！新的一周，新的待办清单，我陪主人一起清空它～"),
        ("talk", "周一的第一件事最难开头，开了头就顺了，加油！")],
    4: [("happy", "周五啦～再坚持一下，周末就在前面！"),
        ("happy", "今天是周五！把这周的收尾做好，就可以安心放松啦～")],
    5: [("happy", "周六好～今天要是不用赶进度，就做点喜欢的事吧。"),
        ("talk", "周末也来见我啦？那今天我们慢慢来～")],
    6: [("happy", "周日好～今天适合整理一下这周的东西，顺便歇歇脑子。"),
        ("talk", "周日啦，不着急，我也跟着放松一下～")],
}
FESTIVAL_LINES = {
    "元旦": ("happy", "新年快乐，主人！新的一年也请多多指教～"),
    "情人节": ("happy", "情人节快乐～今天的我也是主人的专属助手哦。"),
    "劳动节": ("happy", "劳动节快乐！今天要不要给自己放个小假？"),
    "儿童节": ("happy", "儿童节快乐！今天允许主人当一天小朋友～"),
    "国庆节": ("happy", "国庆节快乐！假期也要记得照顾好自己哦。"),
    "平安夜": ("happy", "平安夜快乐～今晚想吃苹果吗？"),
    "圣诞节": ("happy", "圣诞快乐！（抱紧书）我的礼物是……一整天的陪伴！"),
    "除夕": ("happy", "除夕快乐！今年辛苦啦，主人，好好吃顿年夜饭吧～"),
    "春节": ("happy", "新春快乐！祝主人新的一年代码零 bug、事事顺利～"),
    "元宵节": ("happy", "元宵节快乐！今天吃汤圆了吗？我猜主人是芝麻馅派～"),
    "端午节": ("happy", "端午安康！今天吃粽子了吗？甜的还是咸的？"),
    "七夕": ("happy", "七夕快乐～今天的星星特别亮，主人抬头看看吧。"),
    "重阳节": ("happy", "重阳节快乐！记得给家里的长辈打个电话哦～"),
    "中秋节": ("happy", "中秋快乐！月饼和月亮，今天都要好好欣赏哦～"),
}
BIRTHDAY_LINE = ("happy", "主人生日快乐！🎂 今天你最大，想让我说多少句好话都行～")


WEEKDAY_CHANCE = 0.5  # on a weekday with its own lines, how often the hello is one of them


def greeting_line(hour: int, festival: str | None, birthday: bool, rng: random.Random,
                  weekday: int | None = None) -> Reply:
    """Her first words of the day: a birthday or festival wish if it is one, else good morning / hello
    (on Mondays, Fridays and weekends now and then a word about the day)."""
    if birthday:
        return Reply(*_table("BIRTHDAY_LINE"))
    festivals = _table("FESTIVAL_LINES")
    if festival in festivals:
        return Reply(*festivals[festival])
    days = _table("WEEKDAY_GREETINGS")
    if weekday in days and rng.random() < WEEKDAY_CHANCE:
        mood, text = rng.choice(days[weekday])
    else:
        mood, text = rng.choice(_table("GREETINGS")["morning" if 5 <= hour < 11 else "day"])
    return Reply(mood, text)


def interaction_line(kind: str, rng: random.Random) -> Reply:
    mood, text = rng.choice(_table("INTERACTION_TALK")[kind])
    return Reply(mood, text)


# The focus timer and reminders. Fields: {0} focus minutes, {1} break minutes, {2} periods done; {0} a reminder's
# text and {1} the time it was for. Never about sleep or rest (the night reminder has its own rules).
TIMER_TALK = {
    "start": [
        ("happy", "好，专注 {0} 分钟，开始！我在旁边安安静静陪着～"),
        ("talk", "计时开始～{0} 分钟后我叫主人。"),
    ],
    "focus_done": [
        ("happy", "{0} 分钟专注完成！起来伸个懒腰、喝口水吧，{1} 分钟后我再叫你～"),
        ("happy", "第 {2} 个番茄完成啦！活动活动肩膀，看看远处，{1} 分钟后继续～"),
    ],
    "break_done": [
        ("talk", "放松时间到～我们继续专注 {0} 分钟吧！"),
        ("happy", "回来啦？下一个番茄开始，{0} 分钟，加油！"),
    ],
    "stopped": [
        ("talk", "番茄钟结束啦，这次完成了 {2} 个～"),
    ],
    "stopped_none": [  # stopped before the first one was done
        ("talk", "番茄钟先停下啦，这一轮还没走完，下次再一起来～"),
    ],
    "reminder": [
        ("happy", "叮～提醒时间到：{0}"),
        ("talk", "主人，说好的提醒：{0}"),
    ],
    "missed": [
        ("talk", "刚才 {1} 有个提醒，我没来得及说：{0}"),
    ],
}


def timer_line(kind: str, rng: random.Random, *fields) -> Reply:
    mood, text = rng.choice(_table("TIMER_TALK")[kind])
    return Reply(mood, text.format(*fields))


SLEEP_TALK = [
    ("sleep", "（梦话）Token……好多 Token……吃不完了……Zzz"),
    ("sleep", "（梦话）缩进……对齐了……好整齐……Zzz"),
    ("sleep", "（梦话）主人……这段注释写得真好……Zzz"),
    ("sleep", "（翻书声）……Zzz"),
]


def memory_talk_line(activity: str, seconds: float) -> Reply:
    hours = seconds / 3600
    if i18n.english():
        return Reply("talk", persona_en.MEMORY_TALK.format(activity=activity_name(activity), hours=hours))
    return Reply("talk", f"主人今天在「{activity}」上已经花了 {hours:.1f} 小时啦，记得起来走走、喝口水～")


# The day's summary (设置→陪伴「每日小结」): from the companion memory's time per activity.
SUMMARY_HOURS = (0, 18, 20, 21, 22)  # 0 = off
SUMMARY_MIN_ITEM_SEC = 600  # an activity counts from 10 minutes
SUMMARY_MIN_TOTAL_SEC = 1800  # under half an hour in all: nothing to sum up (yet)
SUMMARY_FOCUS_TAILS = ["专注力满分，辛苦啦～", "一个番茄一个番茄地完成，真棒！"]  # a day with only the focus timer to tell
SUMMARY_TAILS = {  # a word on the day's main activity, one picked at random
    "写代码": ["代码敲了这么久，辛苦啦～", "今天写代码有什么新收获吗？", "写了这么久，记得给自己点个赞～"],
    "和 AI 一起干活": ["和 AI 搭档了这么久，配合得还顺利吧？", "今天和 AI 搭档，有什么新收获吗？"],
    "看视频": ["今天看到什么好看的了吗？", "有好看的也分享给我嘛～"],
    "办公/看文档": ["文档一份份啃下来，主人真厉害。", "看了这么久的文档，眼睛记得歇一歇～"],
    "打游戏": ["今天赢了几把呀？", "玩得开心最重要～"],
    "聊天": ["今天和大家聊得挺开心吧～", "聊了这么久，有什么好玩的事吗？"],
    "听音乐": ["今天的歌单我也想听听～", "有音乐陪着，今天应该过得不错吧～"],
    "上网": ["今天在网上逛到什么有趣的东西了吗？", "网上冲浪了一天，有新发现吗？"],
    "在电脑前": ["今天也在电脑前忙了好久，辛苦啦～", "在电脑前待了这么久，记得起来活动活动～"],
}


def summary_line(seconds: dict[str, float], rng: random.Random | None = None,
                 focus: tuple[int, float] = (0, 0.0)) -> Reply | None:
    """'今天的小结：写代码约 3.2 小时、看视频约 40 分钟；专注了 4 个番茄（约 1.7 小时）。' and a word on the day;
    None if too little. `focus` is (periods, seconds) of the focus timer: said even when there is no activity time."""
    ranked = []
    if sum(seconds.values()) >= SUMMARY_MIN_TOTAL_SEC:
        ranked = sorted(((a, s) for a, s in seconds.items() if s >= SUMMARY_MIN_ITEM_SEC), key=lambda i: i[1],
                        reverse=True)
    periods, focused = focus
    if not ranked and periods <= 0:
        return None
    pick_from = (rng or random).choice
    if i18n.english():
        en = persona_en
        parts = [en.SUMMARY_ITEM.format(activity=activity_name(activity), duration=duration_text(spent))
                 for activity, spent in ranked[:3]]
        if periods > 0:
            parts.append(en.SUMMARY_FOCUS.format(count=periods, duration=duration_text(focused),
                                                  s="" if periods == 1 else "s"))
        tail = pick_from(en.SUMMARY_TAILS.get(ranked[0][0], [en.SUMMARY_TAIL]) if ranked else en.SUMMARY_FOCUS_TAILS)
        return Reply("talk", en.SUMMARY.format(parts=en.SUMMARY_JOIN.join(parts), tail=tail))
    text = "、".join(f"{activity}约 {duration_text(spent)}" for activity, spent in ranked[:3])
    if periods > 0:
        focus_part = f"专注了 {periods} 个番茄（约 {duration_text(focused)}）"
        text = f"{text}；{focus_part}" if text else focus_part
    tail = pick_from(SUMMARY_TAILS.get(ranked[0][0], ["辛苦啦～"]) if ranked else SUMMARY_FOCUS_TAILS)
    return Reply("talk", f"今天的小结：{text}。{tail}")


def _in_hours(hour: int, first: int, last: int) -> bool:
    return first <= hour <= last if first <= last else (hour >= first or hour <= last)


def self_talk_line(hour: int, asleep: bool, recent: list[str], rng: random.Random, bedtime: str = "") -> Reply:
    """A local line for this hour (or a sleep murmur), avoiding what she said recently when possible.
    `bedtime` at night: "ok" adds the go-to-bed lines, "no" leaves out every line about sleep or rest."""
    if asleep:
        pool = list(_table("SLEEP_TALK"))
    else:
        pool = list(_table("SELF_TALK"))
        for first, last, extra in _table("TIME_TALK"):
            if _in_hours(hour, first, last):
                pool.extend(extra)
        if bedtime == "ok":
            pool.extend(_table("NIGHT_TALK"))
        elif bedtime == "no":
            pool = [item for item in pool if not mentions_bedtime(item[1])]
    fresh = [item for item in pool if item[1] not in recent] or pool
    mood, text = rng.choice(fresh)
    return Reply(mood, text)


def pick(choices: list[tuple[str, str]]) -> Reply:
    mood, text = random.choice(choices)
    return Reply(mood, text)


def build_user_text(
    window_title: str,
    process_name: str,
    clock: str,
    recent: list[str],
    user_message: str | None = None,
    has_image: bool = True,
    memory: str = "",
    bedtime: str = "",
) -> str:
    if i18n.english():
        return _build_user_text_en(window_title, process_name, clock, recent, user_message, has_image, memory, bedtime)
    parts = [f"现在时间 {clock}。"]
    if bedtime == "ok":
        parts.append(BEDTIME_MAY)
    elif bedtime == "no":
        parts.append(BEDTIME_MAY_NOT)
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


def _build_user_text_en(window_title, process_name, clock, recent, user_message, has_image, memory, bedtime) -> str:
    en = persona_en
    parts = [en.TURN_TIME.format(clock=clock)]
    if bedtime == "ok":
        parts.append(BEDTIME_MAY_EN)
    elif bedtime == "no":
        parts.append(BEDTIME_MAY_NOT_EN)
    if has_image:
        parts.append(en.TURN_WINDOW.format(title=window_title or en.TURN_NO_TITLE,
                                           process=process_name or en.TURN_NO_PROCESS))
    else:
        parts.append(en.TURN_NO_IMAGE)
    if memory:
        parts.append(en.TURN_MEMORY.format(memory=memory))
    if recent:
        parts.append(en.TURN_RECENT + "\n" + "\n".join(f"- {line}" for line in recent))
    if user_message:
        parts.append(en.TURN_MESSAGE.format(message=user_message))
    parts.append(en.TURN_FORMAT)
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


def _json_reply(raw: str) -> tuple[str, str] | None:
    """(mood, line) from a JSON object a persona may have asked for; None if it is not one."""
    start, end = raw.find("{"), raw.rfind("}")
    try:
        data = json.loads(raw[start:end + 1]) if 0 <= start < end else None
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    mood = next((data[k] for k in ("mood", "表情", "emotion") if isinstance(data.get(k), str)), "talk")
    text = next((data[k] for k in ("line", "台词", "text", "reply", "content") if isinstance(data.get(k), str)), "")
    return mood, text


def parse_reply(raw: str) -> Reply | None:
    """Accept `mood|line`; tolerate missing mood, quotes, code fences, HTML tags and extra lines. A JSON object
    (a persona may ask for one, though the host rules say otherwise) gives its mood and line, or nothing."""
    bare = (raw or "").strip().strip("`").strip()
    if bare[:4].lower() == "json" and bare[4:].lstrip()[:1] in ("{", "["):
        bare = bare[4:].lstrip()  # a ```json fence
    if bare.startswith("["):
        try:
            json.loads(bare)
            return None  # a JSON list is data, not something to say
        except ValueError:
            pass
    if bare.startswith("{"):
        found = _json_reply(bare)  # the JSON as written: cleaning first could break its quoting
        if found is None:
            return None  # never show braces and keys as her words
        cleaned = f"{found[0]}|{' '.join(_plain(found[1]).split())}"  # then the line itself is cleaned
    else:
        cleaned = _plain(raw or "").strip().strip("`").strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
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
    limit = MAX_LINE_EN if i18n.english() else MAX_LINE
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return Reply(mood, text, model=True)
