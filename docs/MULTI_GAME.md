# Multiple games in one installation

One installation can host any number of games. Every game is isolated:

| | Per game | Shared across games |
|---|---|---|
| Questions & answers | ✅ each question belongs to exactly one game | |
| Results / statistics | ✅ every session records its game | |
| Look (theme: colours, logos, fonts) | ✅ optional per game, else the active theme | theme library |
| Sponsor / branding slides | ✅ a slide can belong to one game, or be shared | |
| Texts & rules (title, timer, retries, points …) | ✅ optional overrides, else global Game settings | global defaults |
| Staff accounts | ✅ can be limited to chosen games | |
| Categories, characters, media library, interaction schemes | | ✅ |

## Creating a game (admin)
1. **Games → + New game.** Name (EN/AR), link name, optional cover, theme and per-game overrides.
2. **Branding slides →** pick the game in the selector and add its sponsor slides
   (or tick *Shown in → this game* in the slide form). Turn off *Also show the shared slides* in the game's settings
   if the customer should not see the shared ones.
3. **Questions →** pick the game in the selector; new questions go into it.
4. **Users → + New user →** *Game access → Only the games ticked* to give a customer's employee access to that game only.

A game appears on the player screen only when it is enabled **and** has at least one published question.

## Running games for different customers at the same time
Each screen opens its own link and is fully independent (sessions never share state):

* `https://your-domain/game/?game=football`
* `https://your-domain/game/?game=guess-the-player`

A link with `?game=` goes straight to that game (its own branding slides, theme and rules, no game-selection screen).
`/game/` without a parameter shows a game-selection screen when more than one game is playable
(and the default game when only one is).

## Access password per game (players type only a password)
In **Games → Edit → Access password**, set a password for a game. Then:
* Opening that game (`/game/?game=<name>`, or choosing it from the game-selection screen) shows a **password screen** in the game's own theme (EN/AR). No username.
* Each game has its **own** password; two games may use the same one. Leave it empty for open access.
* Passwords are stored hashed (bcrypt), are never shown again in the admin (the field is write-only), and need at least 4 characters.
* After a correct password the screen stays unlocked for **12 hours** (kept per browser tab session, so idle resets and page reloads
  do not ask again; closing the browser does). **Changing or removing the password immediately locks every screen that was unlocked.**
* A locked game exposes nothing else to the public: no sponsor slides, rules or question counts, and sessions cannot be started
  without the unlock token (enforced by the server, not just the screen).
* Brute-force protection: after 5 wrong attempts the game refuses further attempts for 5 minutes (this also briefly blocks the
  legitimate user, by design).
* Admin previews (the *Preview* buttons) bypass the password for signed-in staff.
* Reminder: a short password such as `@123` is easy to guess. It stops casual access, not a determined attacker; use something longer for anything sensitive.

## Staff accounts per game
* **Admin** – always everything, including Games, Users, Themes and global settings.
* **Editor / Viewer with "all games"** – as before.
* **Editor / Viewer limited to games** – sees only those games in Games, Questions, Results, Dashboard and Branding slides.
  The server enforces this: requests for another game's questions, results or slides return *403*.
  An editor of one game can create questions and slides for that game only; shared slides, game creation, themes,
  global settings and user management stay with administrators.
  The media library, categories and characters are shared and visible to all staff.

## Upgrading an existing installation
Migrations 4 and 5 run automatically at start-up: a default game ("Football Challenge", link name `football`) is created and all
existing questions, results and sponsor slides are assigned to it (slides stay shared). Nothing changes for players until a second game exists.

## Delete rules
A game can be deleted only if it has no questions and no recorded sessions (otherwise disable it). The default game can't be deleted or disabled; make another game the default first.


## Game types ("behaviours")
Each game has a **type**, chosen when it is created (fixed once it has questions). More types can be added later.

| Type | What the player does |
|---|---|
| **Quiz** | Picks the right answer, scores points (the original game). |
| **Vault** | Sees an object/question (image or text). A correct answer spins the dial, opens the vault and reveals **that question's prize**; a wrong answer leaves it locked. |

### Vault games
* **Games → New game → Game type: Vault.** Defaults to one question per round (change *Questions per round* to play several vaults in a row).
* In **Questions**, a vault game's questions have a **🏆 Prize** section: prize name (EN/AR), optional description and image. Every question can have a different prize ("each answer a different gift"). A vault question can't be published without a prize name in each language it supports.
* The prize is revealed by the **server only after a correct answer**: it is never sent with the question, so it can't be read from the browser beforehand.
* Per-game vault texts (win title, "stays locked" message, how long the prize stays on screen, final heading) are in the game's settings.
* The end screen lists the prizes won. **Results → Details** records which prize each answer won (`prize_name`), so staff can hand out gifts and reconcile.
* Not included (ask if needed): prize stock/limits ("only 3 iPhones"), winner contact capture, or giving prizes only to a perfect score.
