# ADRs, design docs and wiki pages

A design doc, ADR or wiki page for people is a short, high-level pitch to a cold reader. It answers "why should I care?" first. Why: a page that reads like an execution manual loses the people it is meant to convince, and anything that doesn't help a person understand the proposal only confuses them. A detailed manual for agents belongs in a separate document.

1. Order the page: a short summary of where things are now and where they are going; a short list of what is wrong today; a short list of what the change gains; then everything else.
2. Introduce each concept at a high level first, then break it down. A deep concept takes several steps.
3. Keep sections short, so readers don't tire.
4. Use a diagram whenever the reader would otherwise hold more than two or three things in mind, or scroll back to recall an earlier section.
5. Name things in words, never in keys the reader must hold in their head.
6. Where readers already know of a related effort, mention it wherever the page touches that effort's area. Why: otherwise they conclude the page is unaware of it.

For an ADR, keep the shape in `SKILL.md` (context, decision, consequences) and apply steps 2, 5 and 6.

Done when a reader who knows nothing of the work can say, from the first screen, what changes and why it is worth it.
