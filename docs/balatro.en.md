# Playing Balatro with you

[中文](balatro.md) · **English**

Right-click her or the tray icon and tick "Play Balatro with me". She reads the game and plays it through the
BalatroBot mod, talking about her moves in her bubble (say, "keeping the pair of kings for a full house"): at least
15 seconds apart so that you can keep up, except when she answers your suggestion or starts a new blind.
While she plays, whatever you tell her with "Talk to her" is a suggestion she weighs for her next move.
Untick the same item to stop.

She never looks at the screen and never touches the mouse or keyboard: the game is read and played only through the
mod's interface on `127.0.0.1`, so you can keep using your computer. The game has to stay open, but it need not be in
front and can even be minimized (tested on 2026-11-02); close it and she stops.

She is no expert: in tests she usually loses around antes 1-4, at best on the boss of ante 4, and winning all 8 antes is not
realistic. This is company and commentary, not a way to beat the game.

## What to install first (you do this; the pet never changes the game)

These versions were tested on 2026-10-31 (Balatro 1.0.1o, Steam). **The newest Steamodded 26.x does not work with
BalatroBot 1.5.2** (starting a run fails with `viewed_back` being nil), so use the one below.

| Part | Version | Where it goes |
|---|---|---|
| [Lovely Injector](https://github.com/ethangreen-dev/lovely-injector/releases) | v0.10.0 (`lovely-x86_64-pc-windows-msvc.zip`) | `winmm.dll` from the zip into the game folder (Steam: right-click Balatro, Manage, Browse local files) |
| [Steamodded](https://github.com/Steamodded/smods/releases) | 1.0.0-beta-1620a | unzip the source, rename the folder to `smods`, put it in `%APPDATA%\Balatro\Mods\` |
| [BalatroBot](https://github.com/coder/balatrobot/releases) | v1.5.2 | only `balatrobot.json`, `balatrobot.lua` and `src\lua\`, into `%APPDATA%\Balatro\Mods\balatrobot\` |

Then start Balatro from Steam as usual; the mod listens on `127.0.0.1:12346` (BalatroBot's own Python launcher is not needed).
Back up `%APPDATA%\Balatro` (your saves and settings) before installing mods.

## What the mod changes in the game

Once loaded, BalatroBot mutes the game, sets the game speed to 4x and turns off the tutorial hints. That is the mod's
doing, not the pet's, and it stays so whenever the mod is installed, also when you play yourself. Uninstall it to stop that;
if the sound or speed does not come back afterwards, set them again in the game's options.

## Uninstalling

1. Close Balatro.
2. Delete `winmm.dll` from the game folder, and `%APPDATA%\Balatro\config\Steamodded.jkr` if it is there (the mod left it).
3. In `%APPDATA%\Balatro\Mods`, delete the `smods`, `balatrobot` and `lovely` folders; keep any other mods, and delete the
   folder itself if it is empty.

Your saves stay as they are; uninstalling does not touch your progress. **Do not** put an old backup over
`%APPDATA%\Balatro` just to uninstall: that loses all progress since the backup. Do it only if you really want to go back
to before the install, and save a copy of the current folder first; if Steam Cloud reports a conflict, keep the local files.

## How she plays

- At the main menu she starts a run with `balatro_deck` (the Blue Deck by default) on White Stake; a run in progress is
  continued; if the game shows a finished run when she starts, she goes back to the menu and starts a new one.
- For a hand she is told the best poker hand in hand and what it scores (counting only jokers tied to a poker hand), how much is still needed and
  how much each hand left must make; when that is not enough she is reminded to discard for a bigger hand first.
- Choosing the blind (always played, never skipped), cashing out and using planet cards follow fixed rules, without the model. A
  planet card is used as soon as she has it, except with the Observatory voucher, which makes holding one worthwhile.
- Tarot cards: the prompt says whether each needs cards and how many. Those needing none (The High Priestess, The Emperor, The Hermit,
  Temperance, Judgement, The Wheel of Fortune) are used as soon as they would do something. Enhancing ones are used while playing a hand:
  The Magician, The Empress, The Hierophant and Justice on cards that score, The Chariot and The Devil on a card kept in hand (steel and
  gold work while held). The others (The Fool, The Lovers, Strength, The Hanged Man, Death, The Tower, the four changing suits) are hers to
  decide. Not when a suggestion from you is waiting; once the game refuses one, no card is used by itself for the rest of the game.
- Playing or discarding, the shop and opened packs take one call each to the model you chose (the game as text, no screenshot).
  Her move is checked against what the current screen allows before it is sent; a move that is not allowed, or a failed call,
  falls back to simple rules (the best poker hand in hand; leave the shop; skip the pack).
- She cannot see face-down cards: the mod reports their real value, but the pet neither tells the model nor counts them.
- When she speaks Chinese, card, poker hand and blind names are the game's own: the mod only reports English names, so on
  starting she reads the game's Chinese language file from the `Balatro.exe` Steam installed (read only, never run or changed).
  If it cannot be read, the model puts them into Chinese itself, which may differ from the game.
- In the shop she is told how interest works, what she would get now and what is left after buying each item, to weigh purchases.
- A local rule guards the money: a purchase must leave at least $5 × the current ante (up to the full interest, usually $25);
  with fewer than 3 jokers a joker is exempt; she rerolls only with the full interest covered (a free reroll is always fine).
  If she tries to buy below that, she leaves the shop for this move. A suggestion from you lifts the rule for that move, so she
  buys what you ask for. The Green Deck pays no interest, so the rule does not apply.
- With fewer than 3 jokers and one she can afford and fit in the shop, she is told to buy it first; if she goes to leave without
  buying anything, the pet buys the cheapest for her. Not when the move follows a suggestion from you.
- Money above the full interest (usually $25) earns nothing: if she goes to leave without buying, the pet spends it for her, keeping the
  full interest. In order: a joker with room for it (those tied to a poker hand first), a planet, a voucher, or a reroll while a joker could
  still fit. Packs are left to her. Not when the move follows a suggestion from you.
- With at least 2 jokers she picks a poker hand to build this run around and remembers it, favouring it when buying and changing
  it only if she clearly should; she plays a bigger hand she already holds rather than break it up. The pet works out what to go
  on: which hands she played most, which are leveled up, and which the jokers she owns favour. The next run starts afresh.
- The local rules keep watch over what she plays: cards worth less than 60% of the best hand, and not enough to beat the blind, are
  replaced by the best hand. The estimate counts jokers tied to a poker hand (+100 chips on a three of a kind, say); it cannot work
  out the others, hence the margin. Not when the move follows a suggestion from you.
- The local rules see to bosses with rules on what you play: The Psychic (5 cards), The Eye (no poker hand twice), The Mouth (only one
  poker hand). The best hand is only chosen from what can score, and a move that would score nothing becomes the best hand (not when
  it follows a suggestion from you).
- Discards are watched too, unless the move follows a suggestion from you: discarding from a straight or better, or from a hand already worth enough, becomes
  playing it; playing a lone high card that does not beat the blind, with discards left, becomes a discard that keeps the best hand and
  what is closest to a flush or a straight. She decides the other discards and the purchases, and talks.
- If a model call fails she does not rush a move: she asks again after 15, 30 and 60 seconds, and only then uses the rules.
- If the game refuses a move (not enough money, say) she says why and decides again; after 3 refusals in a row the rules take
  over, and after 6, or if the game cannot be reached, she stops playing.
- After `balatro_target_ante` antes (8 by default) or a lost run she sums up and stops: no endless mode, no new run on her own.
- Pausing (Ctrl+Alt+P) stops at the current move at once; resuming carries on.

## Settings (for now only in `%APPDATA%\ClaudePet\config.json`)

| Key | Default | Meaning |
|---|---|---|
| `balatro_deck` | `"BLUE"` | the deck of a new run: RED, BLUE, YELLOW, GREEN, BLACK, MAGIC, NEBULA, GHOST, ABANDONED, CHECKERED, ZODIAC, PAINTED, ANAGLYPH, PLASMA, ERRATIC |
| `balatro_target_ante` | `8` | the ante to stop after (1-8) |
| `balatro_port` | `12346` | the mod's port, the same as BalatroBot's `BALATROBOT_PORT` (1024-65535) |
| `balatro_thinking_tokens` | `0` | with the Claude subscription, how many tokens of hidden reasoning a move may take (0-8000). "Way of playing" on the settings' General page changes it; see Usage below |

## Usage

Every move in a hand or the shop is one model call, usually one to two hundred a run. With the Claude subscription that
uses your subscription allowance; with an API key it is billed per use.

Left alone, the model first reasons for thousands of hidden tokens, so a two-line answer takes about a minute. That is
why it is off for playing by default. "Way of playing" on the settings' General page chooses (with the Claude subscription
only; a change during a game applies from the next move). Measured on 2026-11-02 with Haiku, on the same hand:

| Way of playing | `balatro_thinking_tokens` | Time per move | Output tokens per move |
|---|---|---|---|
| Relaxed (default) | `0` | 4-6 s | about 50-260 |
| Careful | `2000` | 14-24 s | about 1300-2300 |
| no limit (her other conversations) | - | 29-61 s | about 3300-7400 |
