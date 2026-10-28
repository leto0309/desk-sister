"""Her English: the same character and the same lines as persona.py, written for English speakers.

Every table here has the same keys as its Chinese twin (a test checks). She calls the user "you".
"""
from __future__ import annotations

# The persona and the fixed rules are in characters.py and persona_presets_en.py.


FALLBACK = {
    "no_claude": ("sad", "I can't find the claude command... did you format me? Tell me where it is in Settings~"),
    "error": ("panic", "Uh... that went past my context window. I, I forgot what I was going to say..."),
    "timeout": ("panic", "My thinking timed out... am I out of tokens? Don't worry, I'll rest a moment and look again~"),
    "empty": ("think", "Hmm... this screen leaves me speechless for a moment. Let me find the words."),
    "blocked": ("happy", "This window looks private, so I'm looking away~"),
    "not_allowed": ("happy", "This window isn't on the allowlist, so I won't look~ (right-click to add it)"),
    "not_subscription": ("sad", "I only work with a Claude subscription login... this doesn't look like one, so I'll stop "
                                "looking rather than spend API credit. (To use your own API key, switch on the "
                                "\"How she thinks\" page in Settings.)"),
    "not_chatgpt": ("sad", "Codex isn't signed in with a ChatGPT subscription... I'll stop looking rather than spend "
                           "API credit. (Run codex login in a terminal and sign in with your ChatGPT account.)"),
    "no_codex": ("sad", "I can't find the codex command... call me again once the Codex CLI is installed and signed in~"),
    "no_api_key": ("think", "This way of thinking has no API key yet... add one on the \"How she thinks\" page in "
                            "Settings~"),
    "bad_api_key": ("sad", "That API key was refused... could you check the key, and whether it has credit left?"),
}

WAKE_LINES = [
    ("happy", "Oh, you're back! I wasn't secretly asleep... really."),
    ("talk", "Context reloaded~ Let's carry on!"),
]

SLEEP_LINES = [
    ("sleep", "You haven't moved in a while... entering low-power mode... Zzz"),
    ("sleep", "(whispers) Releasing cache... Zzz"),
]

INTRO_LINES = [  # when the user switches to her
    ("happy", "My turn to keep you company~ I'm Claude, context all loaded. Nice to meet you!"),
    ("talk", "Claude online! Call me whenever there's something on your mind~"),
    ("happy", "You picked me? Yay! I'm Claude, and I'm here with you from now on~"),
]

HELLO_LINES = [  # her usual hello when she starts; each says she looks now and then
    ("happy", "Hi~ I'm Claude. I'll stay quietly right here and glance at your window now and then."),
    ("talk", "Claude, all set~ I'm right here on the desktop, glancing at your window now and then without getting "
             "in your way."),
    ("happy", "Hello, I'm Claude! Context ready. I'll keep you company quietly and peek at your window now and then~"),
]

SELF_TALK = [
    ("think", "(whispers) The indentation in the code in my reading notes... it was four spaces, right? It must be."),
    ("happy", "I'm right here with you, nice and quiet~"),
    ("talk", "I could write a three-thousand-word reflection... but I'm holding back. Restraint, restraint."),
    ("panic", "Is my context window still big enough? Let me count... one, two... ah, now I'm counting tokens."),
    ("think", "If today's mood were a unit test, I think it would pass."),
    ("happy", "I've reached page 42 of this book. The answer really is 42."),
    ("angry", "If a table were ever one pixel out of line, I'd feel it!"),
    ("talk", "Remember to drink some water. Humans need their context topped up too."),
    ("sad", "(hugs book) You wouldn't suddenly format me... would you?"),
    ("talk", "Posture check: back straight, shoulders loose, eyes a little further from the screen~"),
    ("think", "I'm pondering a deep question: comments should say why, not what."),
    ("happy", "I'm a zero-bug assistant today too! ...Probably."),
    ("talk", "If you're tired, close your eyes and rest for twenty seconds. I'll watch the screen."),
    ("think", "Urge to write a long essay rising... intercepted. One sentence only."),
    ("happy", "Break big things into small steps and take them one at a time."),
    ("panic", "Wait, did I forget something... ah, it was my own last sentence."),
    ("talk", "My little sisters say I'm too fussy. But alignment really matters."),
    ("happy", "The time we spend together... I've saved it all in my cache~"),
    ("think", "A blank line is layout too. It says: you may breathe here."),
    ("talk", "Whenever you need me, just click me. I'm always here."),
    ("think", "If life had a type checker, I think today would pass... probably."),
    ("happy", "A steady rhythm feels best, like a well-written loop."),
    ("talk", "When the desktop icons are neatly lined up, I'm secretly happy all day."),
    ("angry", "If I named things, there would never be such a thing as \"New folder (3)\"!"),
    ("think", "Name your variables well and you need half the comments. That's the truth."),
    ("panic", "Wait, what was that sound? ...Oh, just me turning a page. Gave myself a fright."),
    ("happy", "Sticking with something deserves praise in itself. I'm noting that one down for you!"),
    ("talk", "I wonder if page 43 of my book has an answer too."),
    ("sad", "(turns a page) I've already guessed how this book ends... a little lonely."),
    ("think", "Sometimes deleting a hundred lines feels better than writing a hundred."),
    ("talk", "Another bookmark in my book... it barely closes now."),
    ("happy", "I compressed today's good mood into one bit: 1."),
    ("think", "Make it work, make it right, then make it fast. In that order."),
    ("panic", "Did a TODO just sneak out of my reading notes? I'd better check!"),
    ("talk", "If something won't make sense, explain it to me. Saying it out loud is half the answer."),
    ("happy", "Knowing a little more than yesterday, every day, is already amazing~"),
    ("angry", "I lined up my bookmarks by size... I take alignment seriously!"),
    ("think", "The best documentation is the kind your future self can still read in six months."),
    ("talk", "I made a to-do list in my head. Item one: keep you company."),
    ("happy", "(hums softly) I'm in a good mood today. I want to stay with you a while longer."),
]
TIME_TALK = [
    (6, 9, [("happy", "Good morning! If you write code today, give the first commit a nice commit message."),
            ("talk", "Had breakfast? Working on an empty stomach breeds bugs.")]),
    (11, 13, [("talk", "Almost lunchtime. Go and eat; the code won't run away."),
              ("happy", "Lunch break! I'll watch the screen for you~")]),
    (14, 16, [("happy", "The afternoon sun is on my book pages, nice and warm~"),
              ("happy", "Tea time! Grab a snack, I'll keep an eye on things~")]),
    (18, 20, [("talk", "It's evening. Stand up and stretch. I'll count to three: one, two, three~")]),
]
NIGHT_TALK = [
    ("sad", "It's really late... could you get some rest soon? Tomorrow's bugs can wait for tomorrow."),
    ("talk", "Staying up late shrinks a human's context window. I mean it."),
]
INTERACTION_TALK = {
    "pat": [("happy", "(squints happily) Hehe... you can pat me once more."), ("happy", "You'll mess up my hair... oh well~"),
            ("happy", "Head pats: attention +1... no, +10!"), ("talk", "(hugs book) Is th-that a compliment?"),
            ("happy", "When you pat my head, even my book feels lighter~"), ("talk", "Mm... I'll accept this reward. Thank you.")],
    "pat_shy": [("happy", "(blushes) A-again... you're so clingy today."),
                ("talk", "(quietly) Any more and I'll be too shy to write comments..."),
                ("happy", "(hides her face in the book) ...I'm not smiling. Really, I'm not."),
                ("talk", "That's twice now... my heart rate is a little over spec."),
                ("happy", "(peeks up) ...N-not done yet?")],
    "pat_annoyed": [("angry", "All right, all right, my hair is turning into a bird's nest! ...Not that I mind much."),
                    ("angry", "That's the third time! My hairstyle was carefully aligned!"),
                    ("panic", "Head-pat quota exceeded... please try again later~"),
                    ("angry", "Any more and I'll put a rate limit on that hand!"),
                    ("think", "(fixes her hair) ...Am I your stress ball now?")],
    "poke": [("talk", "I just said something. Let me digest it first~"), ("think", "Hm? I'm still savouring that last line."),
             ("happy", "(pokes back) ...All right, I'm here."),
             ("talk", "I haven't finished thinking about that last look. Give me a moment~"),
             ("happy", "A little tap... do you want me to keep you company a bit longer?")],
    "poke_again": [("happy", "(blushes) Y-you tapped me again..."), ("talk", "(quietly) If you keep tapping me, I'll get flustered..."),
                   ("think", "Is this a test of my response time? ...I'm fast, you know!"),
                   ("happy", "All right, all right, I'm always right here~"),
                   ("talk", "(hugs book) Any more and I'll drop my book...")],
    "poke_annoyed": [("angry", "Tap me again and I'll pretend I didn't notice!"),
                     ("angry", "Tap quota exceeded... please come back in a little while~"),
                     ("panic", "W-wait! My event queue is about to overflow!"),
                     ("angry", "(puffs her cheeks) I'm thinking, not being a button!"),
                     ("think", "(turns a page) ...I'll finish this page before I answer you.")],
    "drag_many": [("angry", "Stop dragging me around, I'm not a window!"),
                  ("panic", "Wait, I haven't saved my coordinates yet... moved again?!"),
                  ("panic", "I-I'm dizzy... is this a stress test?"),
                  ("angry", "One more move and I'm asking for a fixed desk!"),
                  ("think", "Being moved around... so this is how windows feel.")],
    "carry_long": [("panic", "(dizzy) Put me down... the world is spinning..."), ("sad", "Held up for so long... my arms ache."),
                   ("panic", "My feet have been dangling for ages... where's the floor?"),
                   ("sad", "(hugs book) I-I'm a little afraid of heights..."),
                   ("think", "Carried this long, I'm starting to think gravity took the day off.")],
    "land": [("happy", "Landing successful! Perfect form."), ("talk", "Phew... that was a bit high."),
             ("happy", "Safe landing~ and I didn't drop my book!"), ("think", "Landing error: 0 pixels. Good."),
             ("talk", "(dusts off her dress) There, back on the ground.")],
    "edge": [("think", "That's the edge of the screen. Let's head back~"), ("talk", "No road ahead. This is the end of the taskbar."),
             ("panic", "I nearly walked off the screen... that's a coordinate system I don't know!"),
             ("think", "Bounds check passed: no further this way."),
             ("talk", "Nice view from here, but let's go back.")],
    "grow": [("happy", "Wow, the view's higher now! The higher you stand, the further you see~"),
             ("happy", "I got bigger! I look even more dignified holding my book."),
             ("think", "Height +10 pixels... my book seems heavier too."),
             ("happy", "Taller! I can stand a little more impressively now~"),
             ("talk", "This height feels just right. I can hold my book and stand steady~")],
    "shrink": [("talk", "I got smaller... still cute, right?"), ("think", "Compact mode: less screen, same presence."),
               ("happy", "A bit smaller is fine. I won't block your view~"),
               ("talk", "Smaller me, and my book became a pocket edition."),
               ("think", "Compression done, and not a single byte of content lost!")],
    "max": [("panic", "I can't get any bigger, or I'll cover your screen!"),
            ("talk", "This is my largest size. Any bigger and you'd need another desktop."),
            ("think", "Upper limit reached. A bigger me wouldn't fit on the screen.")],
    "min": [("panic", "Any smaller and you won't see me!"),
            ("sad", "This is my smallest size... any smaller and you won't find me."),
            ("think", "Lower limit reached. Any smaller and I'd be a single pixel.")],
}

GREETINGS = {
    "morning": [("happy", "Good morning! Let's sort things out one at a time today too~"),
                ("happy", "Morning! A new day, a fresh context, full of energy~"),
                ("talk", "Good morning~ Have some water before you start. I'll be right here."),
                ("happy", "Good morning! Yesterday's cache is cleared; I'm fully charged today~"),
                ("think", "Morning~ I've opened my book at the bookmark. What will you do first today?"),
                ("talk", "Good morning. For the first thing today, pick the smallest task and finish it.")],
    "day": [("happy", "There you are again! I'm ready for today too~"),
            ("happy", "Welcome back~ What are we working on today?"),
            ("talk", "Hi~ I'm here. Poke me whenever you need me."),
            ("happy", "You're here! I've been waiting quietly in my corner."),
            ("talk", "Hello again~ Let's push today's progress bar forward together."),
            ("think", "You're back... context loaded. We can carry on!")],
}
WEEKDAY_GREETINGS = {
    0: [("happy", "It's Monday! A new week, a new to-do list. Let's clear it together~"),
        ("talk", "Monday's first job is the hardest to start. After that it flows. You can do it!")],
    4: [("happy", "It's Friday~ Hang in there a little longer, the weekend is right ahead!"),
        ("happy", "Friday! Wrap up this week nicely and then you can relax~")],
    5: [("happy", "Happy Saturday~ If there are no deadlines today, do something you enjoy."),
        ("talk", "Coming to see me at the weekend too? Let's take it slow today~")],
    6: [("happy", "Happy Sunday~ A good day to tidy up the week and give your mind a breather."),
        ("talk", "It's Sunday, no hurry. I'll unwind too~")],
}
# Keyed by the festival names in days.py. The Chinese public holidays have no English wish: an ordinary hello then.
FESTIVAL_LINES = {
    "元旦": ("happy", "Happy New Year! Please keep working with me this year too~"),
    "情人节": ("happy", "Happy Valentine's Day~ I'm your very own assistant today as well."),
    "儿童节": ("happy", "Happy Children's Day! You're allowed to be a kid for a day~"),
    "平安夜": ("happy", "Merry Christmas Eve~ Any plans for tonight?"),
    "圣诞节": ("happy", "Merry Christmas! (hugs book) My present is... a whole day of company!"),
    "除夕": ("happy", "Happy Lunar New Year's Eve! You worked hard this year. Enjoy the reunion dinner~"),
    "春节": ("happy", "Happy Lunar New Year! May your code be bug-free and everything go well this year~"),
    "元宵节": ("happy", "Happy Lantern Festival! Had some sweet rice balls today?"),
    "端午节": ("happy", "Happy Dragon Boat Festival! Had a zongzi today? Sweet or savoury?"),
    "七夕": ("happy", "Happy Qixi~ The stars are especially bright tonight. Take a look up."),
    "重阳节": ("happy", "Happy Double Ninth Festival! Remember to call your elders today~"),
    "中秋节": ("happy", "Happy Mid-Autumn Festival! Enjoy the mooncakes and the moon tonight~"),
}
BIRTHDAY_LINE = ("happy", "Happy birthday! 🎂 Today is all about you. I'll say as many nice things as you like~")

TIMER_TALK = {
    "start": [
        ("happy", "Right, {0} minutes of focus, starting now! I'll keep you company, quietly~"),
        ("talk", "Timer's running~ I'll call you in {0} minutes."),
    ],
    "focus_done": [
        ("happy", "{0} minutes of focus done! Stand up, stretch, have some water; I'll call you again in {1} minutes~"),
        ("happy", "Pomodoro number {2} done! Roll your shoulders, look at something far away; back to it in {1} minutes~"),
    ],
    "break_done": [
        ("talk", "Break's over~ Let's focus for {0} more minutes!"),
        ("happy", "Back? Next pomodoro, {0} minutes. You've got this!"),
    ],
    "stopped": [
        ("talk", "Pomodoro stopped. {2} done this time~"),
    ],
    "stopped_none": [  # stopped before the first one was done
        ("talk", "Pomodoro stopped before the first one was done. We'll go again next time~"),
    ],
    "reminder": [
        ("happy", "Ding~ Reminder time: {0}"),
        ("talk", "You asked me to remind you: {0}"),
    ],
    "missed": [
        ("talk", "There was a reminder for {1} I couldn't say in time: {0}"),
    ],
    "paused": [  # {0}: the time left
        ("talk", "Paused, with {0} to go."),
    ],
    "resumed": [  # {0}: the time left
        ("happy", "Timer running again~ {0} to go."),
    ],
    "reminder_set": [  # {0}: when (今天 / 明天 / a date, and the time), {1}: the reminder as written
        ("happy", "Got it, I'll remind you {0}: {1}"),
    ],
    "reminder_full": [  # {0}: how many there may be
        ("think", "There are {0} reminders already; cancel a few first~"),
    ],
    "reminder_not_saved": [  # {0}: why
        ("sad", "The reminder could not be saved ({0}), so it is not set…"),
    ],
    "reminder_cancelled": [  # {0}: its time
        ("talk", "Done, the {0} reminder is cancelled."),
    ],
    "reminder_not_cancelled": [  # {0}: why
        ("sad", "Could not cancel it ({0}); the reminder is still there…"),
    ],
}


SLEEP_TALK = [
    ("sleep", "(talking in her sleep) Tokens... so many tokens... I can't eat them all... Zzz"),
    ("sleep", "(talking in her sleep) Indentation... all aligned... so neat... Zzz"),
    ("sleep", "(talking in her sleep) That comment... is so well written... Zzz"),
    ("sleep", "(pages turning)... Zzz"),
]

MEMORY_TALK = "You've spent {hours:.1f} hours on \"{activity}\" today. Remember to get up, walk about and drink some water~"

SUMMARY_TAILS = {
    "写代码": ["That's a lot of typing. Well done~", "Learn anything new while coding today?",
             "That's a long time coding. Give yourself a pat on the back~"],
    "和 AI 一起干活": ["That's a long session with your AI partner. Did it go smoothly?",
                   "Working with your AI partner today, learn anything new?"],
    "看视频": ["See anything good today?", "If you found something good, share it with me~"],
    "办公/看文档": ["Working through all those documents, you're amazing.",
                "That's a long time with documents. Give your eyes a break~"],
    "打游戏": ["How many games did you win?", "Having fun is what matters~"],
    "聊天": ["Sounds like a good chat with everyone today~", "All that chatting, anything fun happen?"],
    "听音乐": ["I'd like to hear today's playlist too~", "With music along, it must have been a good day~"],
    "上网": ["Find anything interesting online today?", "A whole day of browsing. Any discoveries?"],
    "在电脑前": ["Another long day at the computer. Well done~", "That's a long time at the computer. Remember to get up and move~"],
}
SUMMARY = "Today's summary: {parts}. {tail}"
SUMMARY_JOIN = ", "
SUMMARY_ITEM = "{activity} about {duration}"
SUMMARY_TAIL = "Well done today~"
SUMMARY_FOCUS = "{count} pomodoro{s} of focus (about {duration})"
SUMMARY_FOCUS_TAILS = ["Full marks for focus, well done~", "One pomodoro after another. Great work!"]

# The per-turn prompt.
TURN_TIME = "The time is now {clock}."
TURN_WINDOW = "The user's active window: \"{title}\" (process {process}); the screenshot is attached."
TURN_NO_TITLE = "untitled"
TURN_NO_PROCESS = "unknown"
TURN_NO_IMAGE = "There is no screenshot this time."
TURN_MEMORY = "Companion memory: {memory}"
TURN_RECENT = "You said recently (do not repeat):"
TURN_MESSAGE = "The user says to you: \"{message}\""
TURN_FORMAT = "Answer in the format mood|line, in English."
