# A review of someone's PR

Why these rules: every sentence the author reads costs their attention, and a review full of noise teaches them to skip the next one.

1. Back every sentence with a check you ran: each finding, the mechanism and consequence it states, any claim about the suggested fix, and every note or "checked and fine" line. Run each check against the base branch, the PR head, and the head with your suggested fix. Reading the code, or other reviewers agreeing, is not a check. When the check would cost more than the sentence is worth, drop the sentence. Why: one unchecked note in an earlier review was wrong, and it cost the whole review the author's trust.
2. Lead each finding with its consequence: what breaks, for whom (a user, a tester, a future maintainer), tied to the PR's goal where you can. Then say which reading applies, the mechanism, and the fix. Drop a finding with no consequence you can state. Why: a finding without a "why" reads as noise, and it leaves the author unsure whether the behaviour you describe is fine or a flaw.
3. Turn a claim about what a person would do ("a tester will log it as failed") into the symptom you reproduced, or drop it.
4. An approval lists the checks behind it, each line opening with what you did, under a lead-in that frames them as verification. Leave out what the author can see for themselves: the PR's tests, its description, CI, mergeability. Why: a bare approval feels empty, and a list of things the author already sees is noise.
5. Settle every open item before writing: check it until it is a finding or ruled out. The review has no "Open questions" section and no closing offer to walk through or discuss anything. Anything still unsettled goes in your reply to the user, never in the review. Why: an open-questions section only signals a check nobody ran.

Done when every sentence in the review names or follows from a check you ran, and the review ends on its last finding or check.
