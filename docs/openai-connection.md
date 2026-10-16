# OpenAI account connection

The researcher application's **Settings → Research engine** (and the developer
inspector's **Ask / perform a task** dialog) connects a local ChatGPT/Codex
account through the official sign-in flow. Claude Code is the other engine; see
[Claude Code connection](claude-connection.md). It shows the saved account and plan,
disconnected and pending states, a sign-in link, cancellation and connection
errors. Account checks run in the background; graph browsing does not start them.

Click **Connect ChatGPT account**, then **Continue to OpenAI sign-in**. Complete
sign-in on OpenAI's website and return to the inspector. Codex manages the
credentials on this computer. The inspector never asks for a ChatGPT password,
collects raw OAuth tokens or saves them in the ontology. Other local Codex
sessions share the same saved account. An existing account cannot be replaced
from this UI; API-key execution is not a fallback for subscription work.

Connecting only sets up the account. Each question then runs on the selected
engine with the saved sign-in; every call checks the sign-in again, and
background work keeps a quota reserve (see [the core loop](core-loop.md)).
Questions and answers stay on this computer under `.oopc/`; their content is
sent to OpenAI only as the research session itself, and never enters a public
graph release or knowledge snapshot.

Connection requests use the app's loopback, origin and CSRF checks. The
connection process has bounded reads, waits and lifetime, and closes with the
server. No account logout, credential reset or usage purchase is exposed.

The integration uses `account/read`, `account/login/start`,
`account/login/completed` and `account/login/cancel` from the
[official Codex app-server authentication API](https://developers.openai.com/codex/app-server#auth-endpoints).
The implementation requests ChatGPT managed authentication, leaves credential
storage to Codex and accepts only official HTTPS sign-in destinations.

Live research has been run on macOS. The offline graph reader and replay need
no account. A synthetic sign-in test does not establish a live OAuth login or
answer quality.
