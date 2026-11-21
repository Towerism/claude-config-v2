# AI tells: the catalog

Read this at step 3 of SKILL.md, and paste it with the rules into the step 5 review. Each tell is a symptom of one cause: a model fills each slot with the most typical sentence, so the text could be about anything. The fix column says what the sentence usually stood in for.

One tell is weak evidence; humans use every one of them sometimes. Several in one text are what a reader notices. Read the word lists literally: synonyms of listed words aren't implied.

Most entries come from Wikipedia's field guide, [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), checked 2026-11-20; the rows under "How it is built" also come from a blind test of AI and human PR texts. The guide dates its vocabulary by model era. Re-check the word list and the step 3 greps against it when it adds a new era, and by 2027-05-20 at the latest.

## Words and phrases

| Tell | Looks like | Fix |
|---|---|---|
| AI vocabulary | delve, pivotal, underscore, showcase, foster, leverage, robust, seamless, crucial, landscape, multifaceted, intricate, meticulous, quietly, "Additionally," at the start of a sentence | The plain word, or the fact the adjective was hiding ("handles 3 retries" for "robust"). |
| Inflated significance | "plays a key role", "is a testament to", "marks a shift", "reflects broader trends", "sets the stage for" | Say what it does. Cut the claim if there is no fact behind it. |
| Analysis tacked on with -ing | "…, ensuring reliability", "…, highlighting the need for…", "…, making it easier to…" | Delete the tail, or make it its own sentence with the evidence. |
| Fancy stand-ins for "is" and "has" | "serves as", "stands as", "functions as", "boasts", "features", "represents" | "is", "has". |
| Vague connection | "related to", "in connection with", "associated with" | The actual relationship: "caches", "was written by", "breaks when". |
| Corrective framing | "should be treated as X rather than Y", "this does not mean", "should not be confused with", "it's important to note" | State X. Readers rarely held the misreading being corrected. |
| Signposting and chat residue | "Here's what changed", "Let's look at", "In this PR, we", "In summary", "Key takeaways", "I hope this helps", "Happy to adjust" | Delete it and start with the content. |
| Rhetorical setup | "The catch?", "The result:", "Why does this matter?", "So what changed?" | State the answer as a plain sentence. |

## Shape and formatting

| Tell | Looks like | Fix |
|---|---|---|
| Even rhythm | Most sentences fall between about 10 and 20 words; paragraphs have the same number of sentences | Let length follow content: a short sentence for a short fact, a long one where the reasoning needs it. |
| Mirrored paragraphs | Every paragraph opens with a topic sentence and closes by restating it | End the paragraph when its content ends. |
| Bold-label bullets | "- **Speed:** It's faster." on every bullet, bullets of matching length | A sentence or a plain list. Use a table when items share fields. |
| Formatting as decoration | Bold scattered through prose, Title Case Headings, emoji on headings or bullets, a heading over every two paragraphs | Sentence-case headings, bold only for what a skimmer must not miss. |
| Em dashes | Several in a text, punching up clauses where a comma or colon would do. The guide lists this as a sign up to September 2026; newer models avoid dashes, so their absence proves nothing | Use the punctuation the sentence needs. Swapping every dash for a comma is its own pattern. |
| Announce and recap | An opening that says what the text will cover, a closing that repeats it | Start with the first fact; stop after the last one. |
| Paired headings | "Challenges and Opportunities", "Overview and Goals", "Awards and Recognition" | One heading that names what the section says, with a verb where it helps. |

## The text as a whole

These are the hardest to grep and the first a reader feels.

### What it says

| Tell | How to check | Fix |
|---|---|---|
| Swappable sentences | Could the sentence appear unchanged in a text about a different project? | Replace it with the fact only this project has (a number, a file, a name, an incident), or cut it. |
| No author | Nothing in the text shows a person who did the work: no surprise, no dead end, no judgment call, no "I don't know yet" | Add what the author learned or decided, where the reader needs it. A dead end belongs only when the reader would otherwise try it; earlier private versions still stay out. |
| Even hedging | Every claim carries the same mild caution, or none does | Commit where the evidence is solid; hedge only where the source does. |
| Perfect balance | Each option gets equal pros and cons; every concern is answered | Say which option won and why. Leave a real open concern open. |
| Upbeat formula | "Despite these challenges…", then a hopeful outlook | Name the open problem and who owns it, or end on the last fact. |
| Positioning line | "X is for people who…", "This is ideal for teams that…" | Say what it does and what it doesn't; let the reader decide if it fits. |
| Tidy proof | A verification story where everything worked on the first try, told to show that testing happened | Report what was run and what came back, including what failed or wasn't checked. |

### How it is built

| Tell | How to check | Fix |
|---|---|---|
| Smooth all over | No rough edges anywhere: no aside, no specific number, no uneven emphasis | Keep the uneven parts the source has. Leave them in when editing. |
| Stiff register | No contractions ("you have not", "do not") in a text whose voice is casual or first person | Write contractions where you would say them aloud. |
| A reason on every choice | Each decision gets a "because", including ones the reader already knows ("jitter so retries don't all come back at once" for engineers) | Give the reasons the reader lacks. Drop the ones they'd supply themselves. |
| Template order | One paragraph per standard section (problem, solution, alternatives, cost, testing), each the same size | Spend words where the reader's question is. Merge or cut a section that has one sentence to say. |
| Box-ticking sections | A one-sentence "alternatives considered", "non-goals" or "how to test" paragraph that is there because such docs have one | Expand it to what the reader needs to decide, or drop it. |
| Planted specifics | One number per paragraph, spread evenly, as if a rule said "be specific" | Put numbers where the claim depends on them. |

## Not tells

The Wikipedia guide lists these as unreliable, and rewriting them costs clarity for nothing:

- correct grammar, formal or academic wording, and plain bland prose
- transition words such as "Additionally" or "Notably" used once or twice
- a mix of casual and formal tone

Leave such text alone unless a tell above is also present. Never add typos or invented slips to look human: readers spot those too, and a mistake in a technical text costs trust.
