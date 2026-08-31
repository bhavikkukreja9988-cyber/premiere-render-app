# Edge Functions

Not used in this milestone. Per the plan (section 3 / 64), large Premiere
project files and MP4 results are transferred directly to/from Supabase
Storage — never proxied through an Edge Function. Auth, database access and
Storage are handled entirely by the client SDK (`src/remote/`).

This folder is kept as the conventional Supabase location in case a future
milestone needs a server-side function (for example, a moderation or
notification hook). None exists today.
