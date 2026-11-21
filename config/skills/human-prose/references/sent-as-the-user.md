# Text the user sends as themselves

Use this for a Slack or chat message, or a comment, that goes out under the user's name. Why: a draft in a generic voice doesn't sound like the user.

## Pick the register by where it goes

| Where | Voice |
|---|---|
| Direct message | Direct, warm, loose, low ceremony. Mostly lowercase starts, dropped apostrophes ("dont", "thats"), no period on short lines; "yea", "np", "tho", "kinda". Quick acknowledgments of one to four words ("got it", "makes sense"). One thought may run across several short messages. Opens with "ah", "yes", "ok" or straight into the fact; no sign-off. |
| Channel | Direct and confident, friendly and explanatory. Capitalized full sentences with periods. One to three sentences per message, one claim per message. Concedes a point before adding their own ("That's a good point. … But …"). Links on their own line or with one line of context. No bullets. |
| Public (PR reviews, issue comments, anything outside the team chat) | Formal: full capitalized sentences, no slang ("lmk", "tho", "yea", "lol"), no casual opener or closer. Start from the channel voice and lean more formal. |

Pick by the destination, never by the recipient's own style. Why: the user called a PR review drafted in their direct-message voice "too informal", because PR feedback is public. Keep the text direct in every register.

## Draft it; never send it

Create a Slack message the user authored as a draft in the target DM or channel (`slack_send_message_draft`) and let the user send it. Never send it with `slack_send_message`. Why: that tool appends a "Sent using Claude" trailer the user can't turn off, which reads as noise on a message they wrote.

If the user wants to see it first, put the draft in their own self-DM, then a draft in the recipient's DM after they approve. Never send a self-DM preview: the tool can't delete a sent message.

Done when the draft sits in the right conversation, unsent.
