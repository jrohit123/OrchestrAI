-- Godrej only: the chat bot may read the residents table's mobile numbers and broker names (the owner's decision, with
-- core-0021). housing-0005 had listed first_owner_mobile and brokers_name as orgs.settings.ai_sql.hidden_columns;
-- this removes that list. Nothing else in settings changes. To block a column again, add it to that list.
-- Safe to run twice.

UPDATE public.orgs
   SET settings = settings #- '{ai_sql,hidden_columns}'
 WHERE settings -> 'ai_sql' ? 'hidden_columns';
