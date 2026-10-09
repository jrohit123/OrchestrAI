-- Every client: a person's email may be empty (NULL) until they give it. An admin can now add someone with only a name
-- and a WhatsApp number; on their first message the chat bot asks for their email, sends a code to it and saves it.
-- The existing rule that no two people in one organisation share an email stays (empty values do not count against it).
-- Nothing is deleted or changed: every person who has an email keeps it. Safe to run twice.

ALTER TABLE public.users ALTER COLUMN email DROP NOT NULL;
