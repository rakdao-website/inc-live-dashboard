-- Email of the Spacebring company manager (the license holder's invitation
-- email). Used to find a person's Spacebring company. Additive only.
ALTER TABLE visitors
  ADD COLUMN IF NOT EXISTS manager_email VARCHAR(150);
