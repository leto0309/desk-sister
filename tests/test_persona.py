from claude_pet.persona import MAX_LINE, MOODS, Reply, build_user_text, fallback, parse_reply


def test_parses_mood_and_line():
    assert parse_reply("angry|主人！这缩进是两格和四格混用的吧！") == Reply("angry", "主人！这缩进是两格和四格混用的吧！")


def test_unknown_mood_falls_back_to_talk():
    assert parse_reply("excited|好耶") == Reply("talk", "好耶")


def test_missing_separator_keeps_whole_line():
    assert parse_reply("主人在看视频呀") == Reply("talk", "主人在看视频呀")


def test_tolerates_fullwidth_bar_quotes_fences_and_extra_lines():
    raw = "```\n好的\nHappy｜“今天的代码好整齐～”\n```"
    assert parse_reply(raw) == Reply("happy", "今天的代码好整齐～")


def test_empty_or_blank_line_is_rejected():
    assert parse_reply("") is None
    assert parse_reply("happy|   ") is None


def test_long_line_is_truncated():
    reply = parse_reply("talk|" + "长" * 200)
    assert len(reply.text) == MAX_LINE and reply.text.endswith("…")


def test_fallbacks_use_known_moods():
    for kind in ("no_claude", "error", "timeout", "empty", "blocked"):
        assert fallback(kind).mood in MOODS


def test_user_text_includes_context_and_history():
    text = build_user_text("main.py - VS Code", "Code.exe", "23:40", ["上一句"], user_message="你好")
    assert "main.py - VS Code" in text and "Code.exe" in text and "23:40" in text
    assert "- 上一句" in text and "你好" in text
    assert "没有截图" in build_user_text("", "", "10:00", [], has_image=False)


def test_html_formatting_never_reaches_the_bubble():
    raw = "happy|主人，v0.3.9 正在下载校验，磁盘剩 47GB 绰绰有余～ </br>"
    assert parse_reply(raw) == Reply("happy", "主人，v0.3.9 正在下载校验，磁盘剩 47GB 绰绰有余～")
    assert parse_reply("talk|第一句<br>第二句<BR />第三句< / br >") == Reply("talk", "第一句 第二句 第三句")
    assert parse_reply("think|这段<b>代码</b>的<span style='color:red'>缩进</span>&nbsp;歪了") == Reply(
        "think", "这段代码的缩进 歪了")
    assert parse_reply("talk|&lt;br&gt;好&amp;好") == Reply("talk", "好&好")


def test_text_that_only_looks_like_html_is_kept():
    assert parse_reply("think|1 < 2，而 a<b 也成立") == Reply("think", "1 < 2，而 a<b 也成立")
    assert parse_reply("happy|List<T> 和 Map<K, V> 好整齐") == Reply("happy", "List<T> 和 Map<K, V> 好整齐")
    assert parse_reply("talk|<script>不是格式标签") == Reply("talk", "<script>不是格式标签")


def test_a_reply_of_only_tags_is_empty():
    assert parse_reply("talk|</br><p></p>") is None
    assert parse_reply("<br>") is None


def test_the_prompt_asks_for_plain_text():
    from claude_pet.persona import SYSTEM_PROMPT

    assert "不要 HTML" in SYSTEM_PROMPT and "Markdown" in SYSTEM_PROMPT


def test_generics_and_paragraphs_survive():
    assert parse_reply("think|List<U> 和 Set<S> 还有 Box<b> 都很整齐") == Reply("think", "List<U> 和 Set<S> 还有 Box<b> 都很整齐")
    assert parse_reply("talk|<p>执行 git</p><p>status 查看状态</p>") == Reply("talk", "执行 git status 查看状态")
    assert parse_reply("talk|看<div>这里</div>和<i>那里</i>") == Reply("talk", "看 这里 和那里")


def test_generics_next_to_formatting_and_bare_ampersands_survive():
    assert parse_reply("think|Box<b> 和 <b>代码</b>") == Reply("think", "Box<b> 和 代码")
    assert parse_reply("talk|<b><i>很</i>整齐</b>") == Reply("talk", "很整齐")
    assert parse_reply("talk|检查 C:\\work\\&copy.txt 和 ?a=1&not=2") == Reply("talk", "检查 C:\\work\\&copy.txt 和 ?a=1&not=2")
    assert parse_reply("talk|&copy; 2026 &#x1F600; &#65;") == Reply("talk", "© 2026 😀 A")


def test_only_real_entities_and_never_a_line_break():
    assert parse_reply("talk|检查 C:\\work\\&copycat;.txt") == Reply("talk", "检查 C:\\work\\&copycat;.txt")
    assert parse_reply("talk|先保存&#10;再退出") == Reply("talk", "先保存 再退出")
    assert parse_reply("talk|&#10;你好&#x0D;呀&#x7F;") == Reply("talk", "你好 呀")

