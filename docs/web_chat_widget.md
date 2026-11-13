# Website chat widget

Institutions add the chat to their own website by pasting one line of code. Visitors talk
to the workspace's agent; when they ask for a person, the conversation appears in the
dashboard inbox and staff replies appear in the visitor's chat window.

## Setting it up (workspace admin)

1. **Channels → Web chat**: tick **Enable this channel** and save.
2. Publish the workspace from the setup guide. Unpublished workspaces never show the chat.
3. In **Put the chat on your website**, list every website address that may show the chat
   (one per line, for example `https://www.clinic.com`). Optional: welcome messages in
   Arabic and English, the language, and the button position. The business name, logo
   and brand colour come from Business settings.
4. Copy the code and paste it just before `</body>` on every page:

   ```html
   <script src="https://YOUR-PLATFORM/api/widget.js" data-workspace="your-workspace" async></script>
   ```

5. **Open a preview** shows the chat on a sample page. Messages sent there are real and
   appear in the inbox.

## How it works

| Address (behind the proxy, under `/api`) | Purpose |
|---|---|
| `GET /widget.js` | The loader. Shows the chat button and opens the chat panel. Cached 5 minutes. |
| `GET /widget/{workspace}/frame` | The chat itself, shown in a frame inside the website. |
| `GET /widget/assets/{frame.js,frame.css,preview.css}` | The frame's script and styles (versioned, cached a day). |
| `GET /widget/{workspace}/preview` | A sample website page with the chat. |
| `POST /channels/web-chat/{workspace}/message` | A visitor sends a message (existing endpoint). |
| `GET /channels/web-chat/{workspace}/messages?visitor_id=…&after=…` | The visitor's own messages, including staff replies. |
| `GET/PUT /channels/web_chat/widget` | Widget settings (workspace admins only). |

- **Only listed websites can show the chat.** The frame is sent with
  `Content-Security-Policy: frame-ancestors 'self' <dashboard> <listed websites>`, so
  browsers refuse to display it anywhere else; the button appears only after the frame
  has loaded. Website entries are strictly validated because they are placed in that header.
  The dashboard address comes from `FRONTEND_URL`.
- **Isolation.** The conversation runs inside the platform's frame, so the website's own
  scripts and styles cannot read or change it. The loader styles its button through the
  DOM rather than `<style>` tags, so it also works on websites with strict security policies
  (those websites must still allow the platform's script and frame).
- **Visitor identity.** Each browser gets a random 42-character visitor id, stored in the
  frame's local storage for that website. Only ids of 32+ random characters can read a
  conversation back; shorter ids (older integrations) can still send messages.
- **Staff replies.** The chat checks for new messages every 4 seconds while open and every
  15 seconds while closed (not at all while the page is hidden), and shows an unread count
  on the button. Rate limits: 40 history checks per minute per visitor, 600 per minute per
  network address, plus the existing 120 messages per minute per address.
- **Bot and team.** When a visitor asks for a person, they get one acknowledgement and the
  bot stays quiet. If nobody from the team replies within a minute, the bot answers the
  visitor's next message (`HANDOFF_AUTO_RETURN_SECONDS`). Once a team member replies (from
  any channel), the conversation is theirs: the bot stays quiet until 15 minutes after their
  last reply (`STAFF_REPLY_HOLD_SECONDS`), or until they resolve the conversation.
- **Languages.** Arabic (right to left) and English. With "Match the website and visitor",
  the chat follows the website's `<html lang>`, then the visitor's browser, then the
  workspace's default language.

## Not included yet

- Visitors are not notified outside the browser (no email or push) when staff reply later.
- No file or image sending, typing indicators from staff, or visitor name/email form.
- Real-time delivery uses short polling; a push connection could replace it at scale.
