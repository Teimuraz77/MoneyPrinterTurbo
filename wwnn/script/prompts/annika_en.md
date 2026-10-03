Write Annika's archive segment. It closes the main episode AND is published, unchanged, as a
standalone vertical YouTube Short, so it must work in both places:
- Do not mention Tom, "the rest of the show", "earlier", or "next week". Open as if the viewer
  has just walked into the archive unannounced; close with a polite, faintly disappointed sign-off.
- HARD LIMIT: at most {max_words} spoken words in total (it must stay under {max_seconds} seconds).
  Aim for about {target_words} words. Short sentences. Fast, precise, withering.

ARCHIVE STORIES (cover every one, in this order):
{stories}

STRUCTURE (segments in this order)
1. kind "archive_intro": one or two sentences.
2. One kind "archive_story" per story, item_slot set to the story's slot (e.g. "A1"). Mention
   the year early. Facts first, then the passive-aggressive observation that nothing has changed.
3. kind "signoff": one or two sentences.

For every archive_story give lower_third_title (max 40 characters) and lower_third_sub (max 55
characters, include the year). Also give short_title (max 70 characters, for the Short) and
short_hook (one sentence for the Short's description).
{feedback}
